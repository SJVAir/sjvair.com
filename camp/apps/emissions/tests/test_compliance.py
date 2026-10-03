from datetime import date
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase

from camp.apps.emissions import compliance, stats
from camp.apps.emissions.models import AirComplianceFacility, ComplianceEvent, Facility
from camp.apps.emissions.tests.test_stats import scope


def track(facility, pgm_sys_id, *, hpv='No Violation Identified', reported_through=None, name=None, **fields):
    """A matched ICIS row for `facility`."""
    return AirComplianceFacility.objects.create(
        facility=facility, pgm_sys_id=pgm_sys_id, registry_id='110000000001', name=name or facility.name,
        current_hpv=hpv, match_method='parsed', reported_through=reported_through, **fields,
    )


def event(row, kind, when, **fields):
    return ComplianceEvent.objects.create(icis_facility=row, kind=kind, date=when, agency='L', external_id=f'{kind}-{when}', **fields)


class ComplianceTestCase(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.plant = Facility.objects.get(name='TEST PLANT')
        self.station = Facility.objects.get(name='TEST GAS STATION')
        self.cement = Facility.objects.get(name='TEST CEMENT')


class CardTests(ComplianceTestCase):
    def test_none_without_a_match(self):
        assert compliance.facility_card(self.plant) is None
        AirComplianceFacility.objects.create(pgm_sys_id='CAKCA1', name='UNMATCHED')
        assert compliance.facility_card(self.cement) is None

    def test_rollups_count_back_from_reported_through(self):
        row = track(self.plant, 'CASJV00006019C0001', hpv='Unaddressed-Local', reported_through=date(2024, 6, 30), title_v=True, pollutant_class='Major')
        event(row, 'inspection', date(2019, 6, 30))   # a day before the window: out
        event(row, 'inspection', date(2019, 7, 1))    # the window's first day: in
        event(row, 'inspection', date(2024, 3, 15))
        event(row, 'nov', date(2023, 5, 2))
        event(row, 'formal', date(2024, 6, 30), penalty=Decimal('12500.50'))
        event(row, 'formal', date(2015, 1, 1), penalty=Decimal('99999'))
        event(row, 'hpv', date(2024, 4, 1), description='High-priority violation')
        card = compliance.facility_card(self.plant)
        assert card['primary'] == row and card['reported_through'] == date(2024, 6, 30) and card['since'] == date(2019, 7, 1)
        assert (card['inspections'], card['novs'], card['formals'], card['penalties']) == (2, 1, 1, Decimal('12500.50'))
        assert [e.date for e in card['events']][:2] == [date(2024, 6, 30), date(2024, 4, 1)]
        assert len(card['events']) == 7
        # Shown: the window's enforcement. More: its inspections and anything older.
        assert [(e.kind, e.date) for e in card['shown']] == [('formal', date(2024, 6, 30)), ('hpv', date(2024, 4, 1)), ('nov', date(2023, 5, 2))]
        assert [(e.kind, e.date) for e in card['more']] == [
            ('inspection', date(2024, 3, 15)), ('inspection', date(2019, 7, 1)), ('inspection', date(2019, 6, 30)), ('formal', date(2015, 1, 1))]
        assert card['names'] == []

    def test_names_as_reported_and_show_all_split(self):
        row = track(self.plant, 'CASJV00006019C0001', reported_through=date(2024, 1, 1), name='PREVIOUS OWNER LLC')
        for day in range(1, 31):
            event(row, 'inspection', date(2023, 1, day))
        card = compliance.facility_card(self.plant)
        assert card['names'] == ['PREVIOUS OWNER LLC']
        assert card['shown'] == [] and len(card['more']) == 30

    def test_two_icis_rows_merge(self):
        old = track(self.plant, 'CASJV00006019C0001', reported_through=date(2020, 1, 1))
        new = track(self.plant, 'CASJV00006019C0009', reported_through=date(2024, 1, 1), hpv='Addressed-Local')
        event(old, 'nov', date(2019, 6, 1))
        event(new, 'nov', date(2023, 6, 1))
        card = compliance.facility_card(self.plant)
        assert card['primary'] == new and card['novs'] == 2 and len(card['events']) == 2

    def test_cache_clears_on_import(self):
        track(self.plant, 'CASJV00006019C0001', reported_through=date(2024, 1, 1))
        assert compliance.facility_card(self.plant)['novs'] == 0
        event(AirComplianceFacility.objects.get(), 'nov', date(2023, 1, 1))
        assert compliance.facility_card(self.plant)['novs'] == 0
        compliance.clear_caches()
        assert compliance.facility_card(self.plant)['novs'] == 1


class AreaAndFilterTests(ComplianceTestCase):
    def test_area_summary(self):
        assert compliance.area_summary(scope(year=2024)) is None
        track(self.plant, 'CASJV00006019C0001', hpv='Unaddressed-Local')
        track(self.station, 'CASJV00006029S0002')
        AirComplianceFacility.objects.create(pgm_sys_id='CAKCA1', name='UNMATCHED')  # never counted
        # 2024, major sources: TEST PLANT and TEST CEMENT; the station is minor.
        assert compliance.area_summary(scope(year=2024)) == {'facilities': 2, 'tracked': 1, 'unaddressed': 1}
        assert compliance.area_summary(scope(year=2024, minor=1)) == {'facilities': 3, 'tracked': 2, 'unaddressed': 1}
        assert compliance.area_summary(scope(year=2024, county='kern')) is None

    def test_facility_table_filter(self):
        track(self.plant, 'CASJV00006019C0001', hpv='Unaddressed-Local')
        track(self.cement, 'CAKCA1', hpv='Addressed-Local')
        names = lambda **kw: [r.facility.name for r in stats.facility_table(scope(year=2024), **kw)]
        assert names(compliance='any') == ['TEST CEMENT', 'TEST PLANT']
        assert names(compliance='hpv') == ['TEST PLANT']
        assert names(compliance='bogus') == names()


class PageTests(ComplianceTestCase):
    def detail(self, facility):
        return self.client.get(facility.get_absolute_url()).content.decode()

    def test_no_card_without_a_match(self):
        content = self.detail(self.plant)
        assert 'Compliance (federal Clean Air Act reporting)' not in content
        assert 'No violation' not in content and 'ECHO' not in content

    def test_card(self):
        row = track(self.plant, 'CASJV00006019C0001', hpv='Unaddressed-Local', reported_through=date(2024, 6, 30),
                    title_v=True, pollutant_class='Major', name='TEST PLANT INC')
        event(row, 'inspection', date(2024, 3, 15), action_type='FCE On-Site')
        event(row, 'nov', date(2023, 5, 2), action_type='Notice of Violation')
        event(row, 'formal', date(2024, 6, 30), action_type='Administrative - Formal (Settlement)', penalty=Decimal('12500.50'))
        content = self.detail(self.plant)
        assert 'Compliance (federal Clean Air Act reporting)' in content
        assert '<span class="tag">Title V</span>' in content and '<span class="tag">Major</span>' in content
        assert 'High-priority violation: unaddressed' in content
        assert 'Last 5 years: 1 inspection · 1 notice of violation · 1 formal action, $12,501 in penalties' in content
        assert 'href="https://echo.epa.gov/detailed-facility-report?fid=110000000001">Full record at EPA ECHO →</a>' in content
        assert 'Reported to EPA through June 30, 2024.' in content
        assert 'as reported to EPA: TEST PLANT INC' in content
        table = content[content.index('compliance-events'):]
        # The table is the enforcement, newest first; the inspection is behind the toggle.
        assert table.index('Administrative - Formal') < table.index('Notice of Violation') < table.index('1 more event: inspections and anything older') < table.index('FCE On-Site')
        assert '<p class="title is-4">$12,501</p>' in content

    def test_show_all_and_addressed_badge(self):
        row = track(self.plant, 'CASJV00006019C0001', hpv='Addressed-EPA', reported_through=date(2024, 1, 1))
        for day in range(1, 31):
            event(row, 'inspection', date(2023, 1, day))
        content = self.detail(self.plant)
        assert 'High-priority violation: addressed' in content
        assert '<details class="compliance-more">' in content and '30 more events: inspections and anything older' in content
        assert 'No notices of violation, formal actions or high-priority violations in the last 5 years.' in content

    def test_none_badge(self):
        track(self.plant, 'CASJV00006019C0001', reported_through=date(2024, 1, 1))
        assert 'No violation identified' in self.detail(self.plant)

    def test_region_line(self):
        from django.urls import reverse
        from camp.apps.regions.models import Region
        fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        facilities = fresno.get_emissions_tab_url('facilities')
        assert '<p class="heading">Tracked by EPA</p>' not in self.client.get(facilities, {'year': '2024'}).content.decode()
        track(self.plant, 'CASJV00006019C0001', hpv='Unaddressed-Local')
        content = self.client.get(facilities, {'year': '2024'}).content.decode()
        assert '<p class="heading">Tracked by EPA</p><p class="title">1</p>' in content
        assert '1 with an unaddressed violation</a>' in content
        # The county's own Facilities tab, filtered to them.
        assert f'href="{facilities}?year=2024&amp;compliance=hpv"' in content or f'href="{facilities}?compliance=hpv"' in content
        assert '<p class="heading">Tracked by EPA</p>' not in self.client.get(kern.get_emissions_tab_url('facilities'), {'year': '2024'}).content.decode()
        near = self.client.get(reverse('emissions:near-me-facilities'), {'lat': '36.737', 'lng': '-119.787', 'radius': '1', 'year': '2024'}).content.decode()
        assert '<p class="heading">Tracked by EPA</p>' in near and 'county=' not in near.split('compliance=hpv')[1][:40]

    def test_about_and_integrations(self):
        from django.urls import reverse
        content = self.client.get(reverse('emissions:about')).content.decode()
        assert '<h2 id="compliance">Compliance</h2>' in content
        assert 'Only large sources are here.' in content and 'No compliance data has been imported yet.' in content
        from camp.apps.emissions.models import SourceImport
        SourceImport.objects.create(source='icis-air', data_through=date(2025, 12, 31))
        content = self.client.get(reverse('emissions:about')).content.decode()
        assert 'Reported through Dec. 31, 2025.' in content
        assert 'EPA ECHO' in self.client.get('/about/integrations/').content.decode()

