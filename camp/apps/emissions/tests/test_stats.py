from django.core.cache import cache
from django.http import QueryDict
from django.test import TestCase

from camp.apps.emissions import cepam, stats
from camp.apps.emissions.models import CountyInventory, EmissionsRecord, Facility, ToxicPollutant
from camp.apps.emissions.pollutants import NH3, POLLUTANTS, PRECURSORS, get_pollutant
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
        assert POLLUTANTS['cancer'].unit == 'share' and POLLUTANTS['cancer'].unit_label == 'share of Valley total'
        assert POLLUTANTS['chronic'].weighted and not POLLUTANTS['nox'].weighted
        assert POLLUTANTS['pm'].label == 'Total PM'
        assert 'pm25' not in POLLUTANTS

    def test_get_pollutant_falls_back_to_the_kind_default(self):
        assert get_pollutant('rog').key == 'rog'
        assert get_pollutant('bogus').key == 'nox'
        assert get_pollutant('cancer').key == 'nox'


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
        assert s.pollutant.key == 'cancer'
        assert s.county == self.fresno

    def test_query_drops_defaults(self):
        assert scope().query() == ''
        assert scope(year=2023, county='fresno').query() == '?year=2023&county=fresno'
        assert scope().query(pollutant='rog') == '?pollutant=rog'
        assert scope(toxics=1).query() == '?toxics=1'


class ToxicResolutionTests(StatsTestCase):
    def test_weighted_keys_slugs_and_legacy_keys(self):
        assert stats.resolve_toxic('cancer').weight_field == 'cancer_weight'
        assert stats.resolve_toxic('chronic').unit == 'share'
        benzene = stats.resolve_toxic('benzene')
        assert benzene.key == 'benzene' and benzene.pollutant_id == 1 and benzene.unit == 'lbs'
        ToxicPollutant.objects.filter(pk=1).update(slug='benzene-x')
        assert stats.resolve_toxic('benzene').key == 'benzene-x'          # a legacy key resolves by CARB id
        assert stats.legacy_toxic_slug({'toxics': '1', 'pollutant': 'benzene'}) == 'benzene-x'
        assert stats.legacy_toxic_slug({'pollutant': 'benzene'}) is None
        assert stats.legacy_toxic_slug({'toxics': '1', 'pollutant': 'cancer'}) is None

    def test_unknown_and_precursor_fall_back_to_cancer(self):
        assert stats.resolve_toxic('bogus').key == 'cancer'
        assert stats.resolve_toxic('ammonia').key == 'cancer'
        assert scope(toxics=1).pollutant.key == 'cancer'
        assert scope(toxics=1, pollutant='diesel-pm').pollutant.key == 'diesel-pm'

    def test_toxic_options_order_and_precursor_exclusion(self):
        keys = [p.key for p in stats.toxic_options(2024)]
        assert keys == ['cancer', 'chronic', 'diesel-pm', 'benzene', 'isopropyl-alcohol']
        assert [p.key for p in stats.toxic_options(2023)] == ['cancer', 'chronic', 'benzene']

    def test_query_drops_the_toxics_default(self):
        assert scope(toxics=1).query() == '?toxics=1'
        assert scope(toxics=1, pollutant='benzene').query() == '?pollutant=benzene&toxics=1'


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

    def test_with_ranks(self):
        s = scope()
        rows = stats.with_ranks(stats.facility_table(s), stats.ranks(s))
        assert [(rank, record.facility.name) for rank, record in rows] == [(1, 'TEST CEMENT'), (2, 'TEST PLANT')]

    def test_one_toxic_in_pounds(self):
        s = scope(toxics=1, pollutant='benzene')
        assert stats.totals(s)['value'] == 2.0
        assert stats.totals(scope(toxics=1, pollutant='benzene', minor=1))['value'] == 2.5
        assert stats.ranks(s) == {self.plant.pk: 1}
        # The cement plant has no benzene row: its value is None, not missing.
        assert dict(stats.values(s)) == {self.plant.pk: 2.0, self.cement.pk: None}

    def test_weighted_values_are_shares_that_sum_to_one(self):
        # 2024 cancer weights: plant 0.4466, cement 23.1, gas station 0.11165 (fixture comments).
        total = 23.65825
        everyone = scope(toxics=1, minor=1)
        shares = dict(stats.values(everyone))
        assert abs(shares[self.cement.pk] - 23.1 / total) < 1e-9
        assert abs(shares[self.plant.pk] - 0.4466 / total) < 1e-9
        assert abs(sum(shares.values()) - 1.0) < 1e-9
        assert abs(stats.totals(everyone)['value'] - 1.0) < 1e-9
        # Minor sources off: the shares are of the same Valley total, so they no longer sum to one.
        assert abs(stats.totals(scope(toxics=1))['value'] - (23.1 + 0.4466) / total) < 1e-9
        assert stats.ranks(scope(toxics=1)) == {self.cement.pk: 1, self.plant.pk: 2}
        totals = stats.valley_totals('cancer_weight')
        assert set(totals) == {2023, 2024}
        assert abs(totals[2023] - 0.2233) < 1e-9 and abs(totals[2024] - total) < 1e-9

    def test_chronic_measure(self):
        shares = dict(stats.values(scope(toxics=1, pollutant='chronic', minor=1)))
        total = 2.0 * 0.005706666666666667 + 10 * 0.003424 + 0.5 * 0.005706666666666667
        assert abs(shares[self.cement.pk] - 0.03424 / total) < 1e-9

    def test_precursor_is_not_a_toxic(self):
        # Ammonia has weights 0 and kind precursor: 100 lbs of it move nothing.
        ToxicPollutant.objects.filter(carb_id='7664417').update(cancer_weight=5.0)
        cache.clear()
        assert abs(stats.valley_totals('cancer_weight')[2024] - 23.65825) < 1e-9

    def test_facility_table_sorts_on_the_measure(self):
        names = [r.facility.name for r in stats.facility_table(scope(toxics=1))]
        assert names == ['TEST CEMENT', 'TEST PLANT']
        assert [r.facility.name for r in stats.facility_table(scope(toxics=1), sort='value')] == ['TEST PLANT', 'TEST CEMENT']
        assert abs(stats.facility_table(scope(toxics=1))[0].value - 23.1 / 23.65825) < 1e-9

    def test_share_baseline_floor(self):
        assert stats.comparable_baseline(0.0002, 'share') and not stats.comparable_baseline(0.00005, 'share')


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

    def test_by_year_and_breakdowns_for_a_weighted_measure(self):
        s = scope(toxics=1, minor=1)
        assert [(row['year'], round(row['value'], 6)) for row in stats.by_year(s)] == [(2023, 1.0), (2024, 1.0)]
        assert round(stats.by_year(scope(toxics=1), facility=self.plant)[1]['value'], 6) == round(0.4466 / 23.65825, 6)
        sectors = {row['sector']: row for row in stats.sector_breakdown(s)}
        assert round(sectors['cement-minerals']['value'], 6) == round(23.1 / 23.65825, 6)
        assert round(sectors['cement-minerals']['share'], 6) == round(23.1 / 23.65825, 6)
        counties = {row['county']: row['value'] for row in stats.county_breakdown(s)}
        assert round(counties[self.kern], 6) == round((23.1 + 0.11165) / 23.65825, 6)

    def test_toxics_breakdown(self):
        breakdown = stats.toxics_breakdown(scope(toxics=1))
        assert [part['name'] for part in breakdown['parts']] == ['Diesel PM', 'Benzene']
        assert round(breakdown['parts'][0]['share'], 6) == round(23.1 / (23.1 + 0.4466), 6)
        assert breakdown['parts'][1]['slug'] == 'benzene'
        assert round(breakdown['valley_share'], 6) == round((23.1 + 0.4466) / 23.65825, 6)
        assert stats.toxics_breakdown(scope(toxics=1, county='fresno', year=2023))['parts'][0]['name'] == 'Benzene'
        assert stats.toxics_breakdown(scope(toxics=1, county='fresno', year=2023, pollutant='benzene')) is not None  # any toxics scope, not only the weighted ones
        top = stats.toxics_breakdown(scope(toxics=1, minor=1), top=1)
        assert [part['name'] for part in top['parts']] == ['Diesel PM', 'Other']


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

    def test_facility_toxics_rows(self):
        rows = stats.facility_toxics(self.plant, 2024)
        assert [row['pollutant'].slug for row in rows] == ['benzene', 'isopropyl-alcohol']   # no ammonia; weighted first
        benzene, isopropyl = rows
        assert (benzene['value'], benzene['previous'], benzene['previous_year']) == (2.0, 1.0, 2023)
        assert round(benzene['share'], 6) == round(0.4466 / 23.65825, 6)
        assert benzene['has_cancer_value'] and benzene['hazard']
        assert isopropyl['share'] is None and not isopropyl['has_cancer_value'] and not isopropyl['hazard']
        assert isopropyl['previous'] is None and isopropyl['previous_year'] == 2023
        assert stats.facility_toxics(self.cement, 2023) == []

    def test_hot_spots(self):
        record = self.plant.emissions.get(year=2024)
        assert stats.hot_spots(record) is None
        EmissionsRecord.objects.filter(pk=record.pk).update(total_score=12.5, hra=4.27)
        record.refresh_from_db()
        assert stats.hot_spots(record) == {'total_score': 12.5, 'hra': 4.27, 'chindex': None, 'ahindex': None}
        assert stats.hot_spots(None) is None

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


class PrecursorTests(StatsTestCase):
    def test_nh3_is_a_criteria_side_pollutant_in_tons(self):
        assert NH3.key == 'nh3' and NH3.precursor and not NH3.toxic and not NH3.weighted
        assert NH3.unit == 'tons' and NH3.unit_label == 'tons/yr'
        assert get_pollutant('nh3') is NH3 and PRECURSORS == [NH3]
        s = scope(pollutant='nh3')
        assert s.pollutant is NH3 and not s.toxics
        assert s.query() == '?pollutant=nh3'
        assert scope(toxics=1, pollutant='nh3').pollutant.key == 'cancer'  # never a toxic

    def test_values_are_lbs_over_2000(self):
        # The fixture: TEST PLANT reported 100 lbs of ammonia in 2024; nobody else reported any.
        s = scope(pollutant='nh3')
        assert dict(stats.values(s)) == {self.plant.pk: 0.05, self.cement.pk: None}
        assert stats.totals(s)['value'] == 0.05
        assert stats.ranks(s) == {self.plant.pk: 1}
        assert [r.facility.name for r in stats.facility_table(s)] == ['TEST PLANT', 'TEST CEMENT']
        assert stats.by_year(s, facility=self.plant) == [{'year': 2023, 'value': 0.0}, {'year': 2024, 'value': 0.05}]
        sectors = {row['sector']: row['value'] for row in stats.sector_breakdown(s)}
        assert sectors['glass'] == 0.05 and sectors['cement-minerals'] == 0.0

    def test_county_context_is_none_for_ammonia(self):
        CountyInventory.objects.create(county=self.fresno, year=2024, inventory=cepam.INVENTORY, source_type='mobile', eic='723', nox=1.0)
        assert stats.county_context(scope(pollutant='nox', county='fresno')) is not None
        assert stats.county_context(scope(pollutant='nh3', county='fresno')) is None

    def test_facility_ranks_append_an_ammonia_row(self):
        rows = stats.facility_ranks(self.plant, 2024)
        assert [row['pollutant'].key for row in rows] == ['nox', 'rog', 'pm', 'pm10', 'sox', 'co', 'tog', 'nh3']
        nh3 = rows[-1]
        assert nh3['value'] == 0.05 and (nh3['county_rank'], nh3['county_count']) == (1, 1)
        assert (nh3['sector_rank'], nh3['sector_count']) == (1, 1) and nh3['county_share'] == 1.0
        assert [row['pollutant'].key for row in stats.facility_ranks(self.cement, 2024)][-1] == 'tog'
        assert stats.precursor_row(self.cement, 2024) is None
