from django.core.cache import cache
from django.http import QueryDict
from django.test import TestCase

from camp.apps.emissions import cepam, stats
from camp.apps.emissions.models import CountyInventory, EmissionsRecord, Facility
from camp.apps.emissions.pollutants import POLLUTANTS, get_pollutant
from camp.apps.regions.models import Region


def scope(**params):
    """A resolved Scope from query parameters, as a request would give them (strings)."""
    query = QueryDict(mutable=True)
    for key, value in params.items():
        query[key] = str(value)
    return stats.resolve_scope(query)


class StatsTestCase(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        self.kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        self.plant = Facility.objects.get(name='TEST PLANT')
        self.cement = Facility.objects.get(name='TEST CEMENT')
        self.gas = Facility.objects.get(name='TEST GAS STATION')


class PollutantTests(TestCase):
    def test_units(self):
        assert POLLUTANTS['nox'].unit == 'tons'
        assert POLLUTANTS['nox'].display(2) == 2
        assert POLLUTANTS['benzene'].unit == 'lbs'
        assert POLLUTANTS['benzene'].display(0.001) == 2
        assert POLLUTANTS['pm'].label == 'Total PM'
        assert 'pm25' not in POLLUTANTS

    def test_get_pollutant_falls_back_to_the_kind_default(self):
        assert get_pollutant('rog').key == 'rog'
        assert get_pollutant('bogus').key == 'nox'
        assert get_pollutant('nox', toxic=True).key == 'benzene'
        assert get_pollutant('formaldehyde', toxic=True).key == 'formaldehyde'


class ScopeTests(StatsTestCase):
    def test_defaults(self):
        s = scope()
        assert s.year == 2024
        assert s.county is None
        assert s.pollutant.key == 'nox'
        assert not s.minor and not s.toxics

    def test_bad_values_fall_back(self):
        s = scope(year=1999, county='nowhere', pollutant='bogus')
        assert (s.year, s.county, s.pollutant.key) == (2024, None, 'nox')

    def test_toxics_and_county(self):
        s = scope(toxics=1, county='fresno', minor=1)
        assert s.toxics and s.minor
        assert s.pollutant.key == 'benzene'
        assert s.county == self.fresno

    def test_query_drops_defaults(self):
        assert scope().query() == ''
        assert scope(year=2023, county='fresno').query() == '?year=2023&county=fresno'
        assert scope().query(pollutant='rog') == '?pollutant=rog'
        assert scope(toxics=1).query() == '?toxics=1'


class TotalsAndRanksTests(StatsTestCase):
    def test_totals_exclude_minor_sources_by_default(self):
        totals = stats.totals(scope())
        assert totals['facilities'] == 2
        assert totals['nox'] == 106.0
        assert totals['rog'] is None
        assert stats.totals(scope(minor=1))['facilities'] == 3
        assert stats.totals(scope(minor=1))['rog'] == 0.2

    def test_county_scope(self):
        assert stats.totals(scope(county='kern'))['nox'] == 100.0

    def test_ranks(self):
        assert stats.ranks(scope()) == {self.cement.pk: 1, self.plant.pk: 2}

    def test_ties_share_a_rank(self):
        EmissionsRecord.objects.filter(facility=self.plant, year=2024).update(nox=100)
        assert stats.ranks(scope()) == {self.cement.pk: 1, self.plant.pk: 1}

    def test_facility_table_filters_and_sorts(self):
        names = [r.facility.name for r in stats.facility_table(scope())]
        assert names == ['TEST CEMENT', 'TEST PLANT']
        assert [r.facility.name for r in stats.facility_table(scope(), sort='name')] == ['TEST CEMENT', 'TEST PLANT']
        assert [r.facility.name for r in stats.facility_table(scope(), q='plant')] == ['TEST PLANT']
        assert [r.facility.name for r in stats.facility_table(scope(), sector='cement-minerals')] == ['TEST CEMENT']
        assert [r.facility.name for r in stats.facility_table(scope(), district='KER')] == ['TEST CEMENT']
        assert [r.facility.name for r in stats.facility_table(scope(), city='fresno')] == ['TEST PLANT']

    def test_with_ranks(self):
        s = scope()
        rows = stats.with_ranks(stats.facility_table(s), stats.ranks(s))
        assert [(rank, record.facility.name) for rank, record in rows] == [(1, 'TEST CEMENT'), (2, 'TEST PLANT')]


class BreakdownTests(StatsTestCase):
    def test_sector_breakdown(self):
        rows = stats.sector_breakdown(scope())
        assert rows[0]['sector'] == Facility.Sector.CEMENT_MINERALS
        assert rows[0]['value'] == 100.0
        assert round(rows[0]['share'], 3) == round(100 / 106, 3)
        assert rows[0]['facilities'] == 1

    def test_county_breakdown_ignores_the_county_scope(self):
        rows = stats.county_breakdown(scope(county='fresno'))
        assert {row['county'] for row in rows} == {self.fresno, self.kern}

    def test_county_breakdown_for_a_sector(self):
        rows = stats.county_breakdown(scope(), sector='glass')
        assert [(row['county'], row['value']) for row in rows] == [(self.fresno, 6.0)]

    def test_by_year(self):
        assert stats.by_year(scope()) == [{'year': 2023, 'value': 3.0}, {'year': 2024, 'value': 106.0}]
        assert stats.by_year(scope(), facility=self.plant) == [{'year': 2023, 'value': 3.0}, {'year': 2024, 'value': 6.0}]
        assert stats.by_year(scope(), sector='cement-minerals') == [{'year': 2024, 'value': 100.0}]

    def test_sector_trends(self):
        trends = stats.sector_trends(scope())
        assert trends['glass'] == [{'year': 2023, 'value': 3.0}, {'year': 2024, 'value': 6.0}]


class CountyContextTests(StatsTestCase):
    def inventory(self, county, source_type, nox):
        CountyInventory.objects.create(
            county=county, year=2024, inventory=cepam.INVENTORY, source_type=source_type,
            eic=f'{county.pk}-{source_type}', nox=nox,
        )

    def test_context_in_tons_per_year(self):
        self.inventory(self.fresno, 'stationary', 0.1)
        self.inventory(self.fresno, 'mobile', 0.9)
        self.inventory(self.kern, 'stationary', 1.0)
        context = stats.county_context(scope())
        assert round(context['total'], 6) == 2.0 * 365
        parts = {part['source_type']: part for part in context['parts']}
        assert round(parts['stationary']['tons'], 6) == round(1.1 * 365, 6)
        assert round(parts['mobile']['share'], 6) == round(0.9 / 2.0, 6)
        assert parts['areawide']['tons'] == 0
        assert context['facilities'] == 106.0
        assert context['base_year'] == cepam.BASE_YEAR

    def test_county_scope_uses_that_county_only(self):
        self.inventory(self.fresno, 'stationary', 0.1)
        self.inventory(self.kern, 'stationary', 1.0)
        assert round(stats.county_context(scope(county='kern'))['total'], 6) == 365.0

    def test_none_for_toxics_or_missing_years(self):
        self.inventory(self.fresno, 'stationary', 0.1)
        assert stats.county_context(scope(toxics=1)) is None
        assert stats.county_context(scope(year=2023)) is None


class FacilityDetailStatsTests(StatsTestCase):
    def test_facility_ranks(self):
        rows = {row['pollutant'].key: row for row in stats.facility_ranks(self.cement, 2024)}
        assert rows['nox']['value'] == 100.0
        assert (rows['nox']['county_rank'], rows['nox']['county_count']) == (1, 1)
        assert (rows['nox']['sector_rank'], rows['nox']['sector_count']) == (1, 1)
        assert rows['nox']['county_share'] == 1.0
        assert rows['rog']['value'] is None

    def test_facility_toxics_in_lbs(self):
        rows = stats.facility_toxics(self.plant, 2024)
        assert [(row['pollutant'].key, row['value']) for row in rows] == [('benzene', 2.0)]
        assert rows[0]['previous'] is None

    def test_large_changes(self):
        # nox 3 -> 6 is +100%; pm 0.8 -> 1.0 (+25%) and pm10 0.5 -> 0.6 (+20%) are under the 50% threshold.
        changes = stats.large_changes(self.plant, 2024)
        assert [(c['pollutant'].key, c['year'], c['previous_year'], round(c['pct'])) for c in changes] == [('nox', 2024, 2023, 100)]

    def test_large_changes_ignores_a_base_under_min_base(self):
        EmissionsRecord.objects.filter(facility=self.plant, year=2023).update(sox=0.05)
        EmissionsRecord.objects.filter(facility=self.plant, year=2024).update(sox=1.0)
        changes = stats.large_changes(self.plant, 2024)
        assert 'sox' not in [c['pollutant'].key for c in changes]

    def test_large_changes_only_covers_the_shown_year(self):
        # The nox 3 -> 6 (+100%) change is between 2023 and 2024; asking about
        # 2023 (no 2022 record to compare against) must not surface it.
        assert stats.large_changes(self.plant, 2023) == []
