from datetime import timedelta

from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from camp.apps.accounts.models import User
from camp.apps.alerts.models import Subscription
from camp.apps.entries.models import PM25
from camp.apps.monitors.airgradient.models import AirGradient
from camp.apps.monitors.bam.models import BAM1022
from camp.apps.monitors.cimis.models import CIMIS
from camp.apps.monitors.models import Host, LatestEntry, Monitor
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.monitors.vozbox.models import VOZBox
from camp.apps.qaqc.models import HealthCheck
from camp.apps.regions.models import Boundary, Region
from camp.apps.regions.panels import panels_for
from camp.apps.reports.base import REPORTS
from camp.apps.reports.panels import CommunityCoveragePanel, CountyCoveragePanel


class StaffClientMixin:
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_superuser(
            email='admin@example.com',
            password='password',
            phone='+15595551234',
            full_name='Admin',
        )
        self.client.force_login(self.user)


class ReportIndexTests(StaffClientMixin, TestCase):
    def test_index_renders_for_staff(self):
        response = self.client.get(reverse('reports:index'))
        assert response.status_code == 200
        assert b'Reports' in response.content

    def test_index_redirects_anonymous(self):
        self.client.logout()
        response = self.client.get(reverse('reports:index'))
        assert response.status_code == 302
        assert '/login/' in response['Location']

    def test_admin_index_lists_every_report(self):
        response = self.client.get(reverse('admin:index'))
        assert response.status_code == 200
        content = response.content.decode()
        assert '<h2>Reports</h2>' in content
        for report in REPORTS:
            assert reverse(f'reports:{report.slug}') in content
            assert report.title in content

    def test_index_redirects_non_staff(self):
        self.user.is_staff = False
        self.user.save()
        response = self.client.get(reverse('reports:index'))
        assert response.status_code == 302
        assert '/login/' in response['Location']


class SubscriptionCountyStatsTests(StaffClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.fresno = PurpleAir.objects.create(name='Fresno PA', sensor_id=1, position=Point(-119.75, 36.75), location='outside')
        self.kern = PurpleAir.objects.create(name='Kern PA', sensor_id=2, position=Point(-119.0, 35.4), location='outside')
        Subscription.objects.create(user=self.user, monitor=self.fresno, level='unhealthy')

    def test_rows_count_monitors_and_subscriptions_per_county(self):
        response = self.client.get(reverse('reports:subscription-county-stats'))
        assert response.status_code == 200
        rows = {row['county']: row for row in response.context['rows']}
        assert rows['Fresno'] == {'county': 'Fresno', 'total_monitors': 1, 'subscription_monitors': 1, 'total_subscriptions': 1}
        assert rows['Kern'] == {'county': 'Kern', 'total_monitors': 1, 'subscription_monitors': 0, 'total_subscriptions': 0}


    def test_old_admin_url_redirects(self):
        response = self.client.get(reverse('admin:alerts_subscription_county_stats'))
        assert response.status_code in (301, 302)
        assert response['Location'] == reverse('reports:subscription-county-stats')

    def test_listed_on_index(self):
        response = self.client.get(reverse('reports:index'))
        assert reverse('reports:subscription-county-stats') in response.content.decode()


def touch(monitor, timestamp):
    """Give a monitor a PM2.5 entry and matching LatestEntry at `timestamp`."""
    entry = PM25.objects.create(monitor=monitor, sensor='a', timestamp=timestamp, value=5.0, stage=PM25.Stage.RAW)
    LatestEntry.objects.update_or_create(
        monitor=monitor, entry_type=PM25.entry_type, processor='',
        defaults={'entry_id': entry.pk, 'timestamp': timestamp, 'stage': PM25.Stage.RAW},
    )
    return entry


class NetworkOverviewTests(StaffClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        now = timezone.now()
        self.pa_fresno = PurpleAir.objects.create(name='PA Fresno', sensor_id=1, position=Point(-119.75, 36.75), location='outside', is_sjvair=True)
        self.pa_kern = PurpleAir.objects.create(name='PA Kern', sensor_id=2, position=Point(-119.0, 35.4), location='outside')
        self.bam = BAM1022.objects.create(name='BAM Fresno', position=Point(-119.76, 36.76), location='outside', is_sjvair=True)
        self.hidden = PurpleAir.objects.create(name='Hidden', sensor_id=3, position=Point(-119.77, 36.77), location='outside', is_hidden=True)
        touch(self.pa_fresno, now - timedelta(minutes=10))
        touch(self.pa_kern, now - timedelta(days=3))

    def test_sjvair_only_toggle(self):
        response = self.client.get(reverse('reports:network-overview'), {'sjvair_only': '1'})
        rows = {row['type']: row for row in response.context['rows']}
        assert response.context['tiles']['total'] == 2
        assert rows['PurpleAir']['total'] == 1
        assert rows['All types']['total'] == 2

    def test_tiles(self):
        response = self.client.get(reverse('reports:network-overview'))
        assert response.status_code == 200
        assert response.context['tiles'] == {'total': 3, 'active': 1, 'sjvair': 2}

    def test_rows_by_type_and_county(self):
        response = self.client.get(reverse('reports:network-overview'))
        rows = {row['type']: row for row in response.context['rows']}
        assert rows['PurpleAir']['Fresno'] == 1
        assert rows['PurpleAir']['Kern'] == 1
        assert rows['PurpleAir']['total'] == 2
        assert rows['BAM1022']['Fresno'] == 1
        assert rows['BAM1022']['total'] == 1
        assert rows['All types']['Fresno'] == 2
        assert rows['All types']['total'] == 3

    def test_single_channel_airgradient_counts_in_tiles(self):
        AirGradient.objects.create(name='AG single', device='O-1PS', sensor_id=1, position=Point(-119.75, 36.75), location='outside')
        response = self.client.get(reverse('reports:network-overview'))
        rows = {row['type']: row for row in response.context['rows']}
        assert rows['AirGradient']['total'] == 1
        assert response.context['tiles']['total'] == rows['All types']['total'] == 4

    def test_totals_row_is_in_the_table_footer(self):
        response = self.client.get(reverse('reports:network-overview'))
        content = response.content.decode()
        assert '<tfoot>' in content
        assert content.index('All types') > content.index('<tfoot>')

    def test_include_hidden(self):
        response = self.client.get(reverse('reports:network-overview'), {'include_hidden': '1'})
        rows = {row['type']: row for row in response.context['rows']}
        assert rows['PurpleAir']['total'] == 3
        assert response.context['tiles']['total'] == 4

    def test_outside_sjv_monitors_are_counted(self):
        PurpleAir.objects.create(name='SF PA', sensor_id=9, position=Point(-122.4, 37.8), location='outside')
        response = self.client.get(reverse('reports:network-overview'))
        rows = {row['type']: row for row in response.context['rows']}
        assert rows['PurpleAir']['Outside SJV'] == 1
        assert rows['PurpleAir']['total'] == 3
        assert rows['All types']['Outside SJV'] == 1
        assert rows['All types']['total'] == 4

    def test_disabled_monitor_types_are_excluded(self):
        CIMIS.objects.create(
            name='CIMIS Fresno',
            station_number='2',
            position=Point(-119.75, 36.75),
            location='outside',
        )
        response = self.client.get(reverse('reports:network-overview'))
        rows = {row['type']: row for row in response.context['rows']}
        assert 'CIMIS' not in rows
        assert rows['All types']['total'] == 3
        assert response.context['tiles']['total'] == 3



def give_health(monitor, score, flatline_a=None, flatline_b=None):
    check = HealthCheck.objects.create(
        monitor=monitor, hour=timezone.now().replace(minute=0, second=0, microsecond=0),
        score=score, sanity_flatline_a=flatline_a, sanity_flatline_b=flatline_b,
    )
    monitor.health = check
    monitor.save()
    return check


class FleetHealthTests(StaffClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        now = timezone.now()
        self.active = PurpleAir.objects.create(name='Active', sensor_id=1, position=Point(-119.75, 36.75), location='outside', is_sjvair=True)
        self.day = PurpleAir.objects.create(name='Day', sensor_id=2, position=Point(-119.75, 36.75), location='outside', is_sjvair=True)
        self.week = PurpleAir.objects.create(name='Week', sensor_id=3, position=Point(-119.0, 35.4), location='outside', is_sjvair=True)
        self.long = PurpleAir.objects.create(name='Long', sensor_id=4, position=Point(-119.0, 35.4), location='outside', is_sjvair=True)
        self.never = PurpleAir.objects.create(name='Never', sensor_id=5, position=Point(-119.0, 35.4), location='outside', is_sjvair=True)
        self.hidden = PurpleAir.objects.create(name='Hidden', sensor_id=6, position=Point(-119.0, 35.4), location='outside', is_hidden=True, is_sjvair=True)
        touch(self.active, now - timedelta(minutes=5))
        touch(self.day, now - timedelta(hours=6))
        touch(self.week, now - timedelta(days=3))
        touch(self.long, now - timedelta(days=30))
        touch(self.hidden, now - timedelta(minutes=5))
        give_health(self.active, 3)
        give_health(self.day, 1)

    def test_sjvair_only_by_default(self):
        partner = PurpleAir.objects.create(name='Partner', sensor_id=7, position=Point(-119.75, 36.75), location='outside')
        touch(partner, timezone.now() - timedelta(minutes=5))
        give_health(partner, 3)

        response = self.client.get(reverse('reports:fleet-health'))
        assert {r['type']: r for r in response.context['rows']}['PurpleAir']['total'] == 6
        assert {g['type']: g for g in response.context['grades']}['PurpleAir']['A'] == 1

        response = self.client.get(reverse('reports:fleet-health'), {'sjvair_only': '0'})
        assert {r['type']: r for r in response.context['rows']}['PurpleAir']['total'] == 7
        assert {g['type']: g for g in response.context['grades']}['PurpleAir']['A'] == 2

    def test_silence_buckets(self):
        response = self.client.get(reverse('reports:fleet-health'))
        assert response.status_code == 200
        row = {r['type']: r for r in response.context['rows']}['PurpleAir']
        assert row == {
            'type': 'PurpleAir', 'active': 1, 'silent_1d': 1, 'silent_7d': 1,
            'silent_long': 1, 'never': 1, 'hidden': 1, 'total': 6,
        }

    def test_county_filter(self):
        response = self.client.get(reverse('reports:fleet-health'), {'county': 'Fresno'})
        row = {r['type']: r for r in response.context['rows']}['PurpleAir']
        assert row['active'] == 1
        assert row['silent_1d'] == 1
        assert row['total'] == 2

    def test_grades_exclude_types_without_health_checks(self):
        # VOZbox lists two PM2.5 sensors but they are not a matched pair.
        VOZBox.objects.create(sensor_id='e00fce68f12da1a0c5de6248', name='VOZ', position=Point(-119.75, 36.75), location='outside', is_sjvair=True)
        response = self.client.get(reverse('reports:fleet-health'))
        assert 'VOZBox' not in {g['type'] for g in response.context['grades']}

    def test_grade_distribution(self):
        response = self.client.get(reverse('reports:fleet-health'))
        grades = {g['type']: g for g in response.context['grades']}
        assert grades['PurpleAir'] == {'type': 'PurpleAir', 'A': 1, 'B': 0, 'C': 1, 'F': 0, 'none': 4}
        assert 'BAM1022' not in grades


class DegradedMonitorsTests(StaffClientMixin, TestCase):
    fixtures = ['regions.yaml']
    def setUp(self):
        super().setUp()
        now = timezone.now()
        host = Host.objects.create(name='Library')
        self.fine = PurpleAir.objects.create(name='Fine', sensor_id=1, position=Point(-119.75, 36.75), location='outside', is_sjvair=True)
        self.grade_f = PurpleAir.objects.create(name='Grade F', sensor_id=2, position=Point(-119.75, 36.75), location='outside', host=host, is_sjvair=True)
        self.grade_c = PurpleAir.objects.create(name='Grade C', sensor_id=3, position=Point(-119.75, 36.75), location='outside', is_sjvair=True)
        self.flat = PurpleAir.objects.create(name='Flat', sensor_id=4, position=Point(-119.0, 35.4), location='outside', is_sjvair=True)
        self.silent = PurpleAir.objects.create(name='Silent', sensor_id=5, position=Point(-119.0, 35.4), location='outside', is_sjvair=True)
        self.never = BAM1022.objects.create(name='Never', position=Point(-119.0, 35.4), location='outside', is_sjvair=True)
        self.hidden = PurpleAir.objects.create(name='Hidden', sensor_id=6, position=Point(-119.0, 35.4), location='outside', is_hidden=True, is_sjvair=True)
        for monitor in (self.fine, self.grade_f, self.grade_c, self.flat):
            touch(monitor, now - timedelta(minutes=5))
        touch(self.silent, now - timedelta(days=3))
        give_health(self.fine, 3)
        give_health(self.grade_f, 0)
        give_health(self.grade_c, 1)
        give_health(self.flat, 3, flatline_b=False)

    def rows(self, **params):
        response = self.client.get(reverse('reports:degraded-monitors'), params)
        assert response.status_code == 200
        return response.context['rows']

    def test_lists_only_degraded_monitors_worst_first(self):
        rows = self.rows()
        assert [r['name'] for r in rows] == ['Never', 'Silent', 'Grade F', 'Grade C', 'Flat']

    def test_conditions_and_columns(self):
        rows = {r['name']: r for r in self.rows()}
        assert rows['Grade F']['condition'] == 'Grade F'
        assert rows['Grade F']['host'] == 'Library'
        assert rows['Grade F']['type'] == 'PurpleAir'
        assert rows['Grade F']['county'] == 'Fresno'
        assert rows['Flat']['condition'] == 'Flatline B'
        assert rows['Silent']['condition'] == 'Silent 3d'
        assert rows['Never']['condition'] == 'Never reported'
        assert rows['Never']['last_seen'] is None
        assert rows['Never']['type'] == 'BAM1022'
        assert rows['Never']['admin_url'] == reverse('admin:bam_bam1022_change', args=[self.never.pk])

    def test_map_marks_each_degraded_monitor(self):
        response = self.client.get(reverse('reports:degraded-monitors'))
        content = response.content.decode()
        assert 'class="admin-leaflet-map"' in content
        assert 'js/admin/leaflet-maps.js' in content
        assert content.count('"kind": "marker"') == 5
        assert content.count('"kind": "area"') == 8  # county outlines
        rows = {r['name']: r for r in response.context['rows']}
        assert rows['Grade F']['map_color'] == '#c0392b'
        assert rows['Silent']['map_color'] == '#7f8c8d'

    def test_map_draws_only_the_selected_county(self):
        response = self.client.get(reverse('reports:degraded-monitors'), {'county': 'Fresno'})
        content = response.content.decode()
        assert content.count('"kind": "area"') == 1
        assert content.count('"kind": "marker"') == 2

    def test_map_drops_markers_outside_the_drawn_counties(self):
        # Fits the map to the valley instead of stretching it to far-away monitors.
        PurpleAir.objects.create(name='Chico', sensor_id=8, position=Point(-121.84, 39.73), location='outside', is_sjvair=True)
        response = self.client.get(reverse('reports:degraded-monitors'))
        assert 'Chico' in {r['name'] for r in response.context['rows']}
        assert response.content.decode().count('"kind": "marker"') == 5

    def test_map_ignores_bogus_positions(self):
        # A device reporting a (0, 0) fix would otherwise fit the map to the whole planet.
        PurpleAir.objects.create(name='Null island', sensor_id=7, position=Point(0, 0), location='outside', is_sjvair=True)
        response = self.client.get(reverse('reports:degraded-monitors'))
        assert 'Null island' in {r['name'] for r in response.context['rows']}
        assert response.content.decode().count('"kind": "marker"') == 5

    def test_no_map_when_nothing_is_degraded(self):
        response = self.client.get(reverse('reports:degraded-monitors'), {'type': 'aqlite'})
        assert response.context['map'] is None
        assert 'class="admin-leaflet-map"' not in response.content.decode()

    def test_sjvair_only_by_default(self):
        partner = PurpleAir.objects.create(name='Partner', sensor_id=10, position=Point(-119.75, 36.75), location='outside')
        give_health(partner, 0)
        assert 'Partner' not in [r['name'] for r in self.rows()]
        assert 'Partner' in [r['name'] for r in self.rows(sjvair_only='0')]
        assert 'Partner' not in [r['name'] for r in self.rows(sjvair_only='1')]

    def test_filters(self):
        assert [r['name'] for r in self.rows(county='Fresno')] == ['Grade F', 'Grade C']
        assert [r['name'] for r in self.rows(type='bam1022')] == ['Never']
        assert 'Hidden' in [r['name'] for r in self.rows(include_hidden='1')]



class CoverageTests(StaffClientMixin, TestCase):
    fixtures = ['regions.yaml', 'calenviroscreen.yaml']

    def setUp(self):
        super().setUp()
        # Fixture tracts, both Fresno: 1.01 (DAC, pop 4650) spans lon -119.8..-119.7,
        # lat 36.7..36.8; 1.02 (not a DAC, pop 3350) spans lon -119.7..-119.6.
        # This monitor sits inside 1.02, ~890 m east of the DAC tract's edge
        # (at lat 36.75, 0.01 degrees of longitude is ~890 m).
        self.near_dac = PurpleAir.objects.create(name='Near DAC', sensor_id=1, position=Point(-119.69, 36.75), location='outside')
        # Kern, outside any fixture tract.
        self.kern = PurpleAir.objects.create(name='Kern', sensor_id=2, position=Point(-119.0, 35.4), location='outside')
        # Only monitors that reported recently count toward coverage.
        for monitor in (self.near_dac, self.kern):
            touch(monitor, timezone.now() - timedelta(minutes=5))

    def test_sjvair_only_toggle(self):
        self.near_dac.is_sjvair = True
        self.near_dac.save()
        response = self.client.get(reverse('reports:coverage'))
        assert {row['county']: row for row in response.context['rows']}['All counties']['monitors'] == 2

        response = self.client.get(reverse('reports:coverage'), {'sjvair_only': '1'})
        rows = {row['county']: row for row in response.context['rows']}
        assert rows['All counties']['monitors'] == 1
        assert rows['Kern']['monitors'] == 0
        assert response.content.decode().count('"kind": "marker"') == 1

    def test_inactive_monitors_do_not_count_by_default(self):
        PurpleAir.objects.create(name='Dead', sensor_id=3, position=Point(-119.72, 36.75), location='outside')
        stale = PurpleAir.objects.create(name='Stale', sensor_id=4, position=Point(-119.73, 36.75), location='outside')
        touch(stale, timezone.now() - timedelta(days=2))
        response = self.client.get(reverse('reports:coverage'))
        rows = {row['county']: row for row in response.context['rows']}
        assert rows['Fresno']['monitors'] == 1
        assert response.content.decode().count('"kind": "marker"') == 2

        response = self.client.get(reverse('reports:coverage'), {'include_inactive': '1'})
        rows = {row['county']: row for row in response.context['rows']}
        assert rows['Fresno']['monitors'] == 3
        assert response.content.decode().count('"kind": "marker"') == 4

    def test_uses_newest_ces_version(self):
        response = self.client.get(reverse('reports:coverage'))
        assert response.status_code == 200
        assert response.context['ces_version'] == 'CES5 (2020)'

    def test_county_rows(self):
        response = self.client.get(reverse('reports:coverage'))
        rows = {row['county']: row for row in response.context['rows']}
        fresno = rows['Fresno']
        assert fresno['monitors'] == 1
        assert fresno['population'] == 8000
        assert fresno['per_10k'] == 1.25
        assert fresno['dac_tracts'] == 1
        assert fresno['dac_monitors'] == 0
        assert fresno['dac_population'] == 4650
        assert fresno['dac_population_covered'] == 4650
        assert fresno['dac_covered_pct'] == 100.0
        kern = rows['Kern']
        assert kern['monitors'] == 1
        assert kern['population'] == 0
        assert kern['per_10k'] is None
        outside = rows['Outside SJV']
        assert outside['monitors'] == 0
        assert outside['dac_monitors'] == 0
        assert outside['population'] == 0
        assert outside['per_10k'] is None
        total = rows['All counties']
        assert total['monitors'] == 2
        assert total['population'] == 8000

    def test_monitor_inside_a_dac_tract_is_counted(self):
        touch(PurpleAir.objects.create(name='In DAC', sensor_id=3, position=Point(-119.75, 36.75), location='outside'), timezone.now())
        response = self.client.get(reverse('reports:coverage'))
        rows = {row['county']: row for row in response.context['rows']}
        assert rows['Fresno']['monitors'] == 2
        assert rows['Fresno']['dac_monitors'] == 1

    def test_map_shades_tracts_and_marks_monitors(self):
        response = self.client.get(reverse('reports:coverage'))
        content = response.content.decode()
        assert 'class="admin-leaflet-map"' in content
        assert content.count('"kind": "area"') == 2 + 8  # two fixture tracts plus county outlines
        assert content.count('"kind": "marker"') == 2
        assert '"fillColor": "#c0392b"' in content  # the DAC tract

    def test_county_without_region_row_has_no_population(self):
        Region.objects.counties().filter(name='Fresno County').delete()
        response = self.client.get(reverse('reports:coverage'))
        fresno = {row['county']: row for row in response.context['rows']}['Fresno']
        assert fresno['monitors'] == 1
        assert fresno['population'] == 0
        assert fresno['per_10k'] is None

    def test_map_ignores_bogus_positions(self):
        touch(PurpleAir.objects.create(name='Null island', sensor_id=9, position=Point(0, 0), location='outside'), timezone.now())
        response = self.client.get(reverse('reports:coverage'))
        assert response.content.decode().count('"kind": "marker"') == 2

    def test_totals_row_is_in_the_table_footer(self):
        response = self.client.get(reverse('reports:coverage'))
        content = response.content.decode()
        assert content.index('All counties') > content.index('<tfoot>')
        assert content.index('Outside SJV') < content.index('<tfoot>')

    def test_radius_param_changes_coverage(self):
        # The only monitor near the DAC tract is ~890 m outside it, so the DAC
        # population counts as covered at the default 1000 m but not at 500 m.
        # This is what pins the radius to meters rather than degrees.
        def covered(**params):
            response = self.client.get(reverse('reports:coverage'), params)
            assert response.context['radius'] == int(params.get('radius', 1000))
            rows = {row['county']: row for row in response.context['rows']}
            return rows['Fresno']['dac_population_covered']

        assert covered() == 4650
        assert covered(radius='500') == 0
        assert covered(radius='5000') == 4650

    def test_percentile_bands(self):
        response = self.client.get(reverse('reports:coverage'))
        bands = {b['band']: b for b in response.context['percentile_bands']}
        assert set(bands) == {'0–25', '25–50', '50–75', '75–100'}
        assert bands['75–100'] == {'band': '75–100', 'tracts': 1, 'population': 4650, 'monitors': 0, 'per_10k': 0.0}
        assert bands['50–75'] == {'band': '50–75', 'tracts': 1, 'population': 3350, 'monitors': 1, 'per_10k': 2.99}
        assert bands['0–25']['tracts'] == 0



class CoverageNoCESTests(StaffClientMixin, TestCase):
    fixtures = ['regions.yaml']
    """The report still renders when no CalEnviroScreen data has been imported."""

    def setUp(self):
        super().setUp()
        self.monitor = PurpleAir.objects.create(name='Fresno', sensor_id=1, position=Point(-119.75, 36.75), location='outside')
        touch(self.monitor, timezone.now() - timedelta(minutes=5))

    def test_map_shows_monitors_without_ces_data(self):
        response = self.client.get(reverse('reports:coverage'))
        content = response.content.decode()
        assert content.count('"kind": "area"') == 8  # county outlines only
        assert content.count('"kind": "marker"') == 1

    def test_renders_without_ces_data(self):
        response = self.client.get(reverse('reports:coverage'))
        assert response.status_code == 200
        assert response.context['ces_version'] is None
        assert response.context['percentile_bands'] == []
        fresno = {row['county']: row for row in response.context['rows']}['Fresno']
        assert fresno['monitors'] == 1
        assert fresno['population'] == 0
        assert fresno['per_10k'] is None


def make_place(name, region_type, bbox, external_id):
    """A city/CDP Region with a rectangular current boundary (lon/lat bbox)."""
    region = Region.objects.create(name=name, slug=name.lower(), type=region_type, external_id=external_id)
    boundary = Boundary.objects.create(region=region, version='latest', geometry=MultiPolygon(Polygon.from_bbox(bbox)))
    region.boundary = boundary
    region.save()
    return region


class CoverageCommunityTests(StaffClientMixin, TestCase):
    fixtures = ['regions.yaml', 'calenviroscreen.yaml']

    def setUp(self):
        super().setUp()
        # Testville covers fixture tract 1.01 (pop 4650); Emptyville covers tract 1.02 (pop 3350).
        self.testville = make_place('Testville', Region.Type.CDP, (-119.8, 36.7, -119.7, 36.8), '9001')
        self.emptyville = make_place('Emptyville', Region.Type.CITY, (-119.7, 36.7, -119.6, 36.8), '9002')
        self.monitor = PurpleAir.objects.create(name='In Testville', sensor_id=1, position=Point(-119.75, 36.75), location='outside')
        touch(self.monitor, timezone.now() - timedelta(minutes=5))

    def rows(self, **params):
        response = self.client.get(reverse('reports:coverage-community'), params)
        assert response.status_code == 200
        return response.context['rows'], response.context

    def test_rows_and_tiles(self):
        rows, context = self.rows()
        by_name = {row['name']: row for row in rows}
        assert by_name['Testville']['type'] == 'CDP'
        assert by_name['Testville']['county'] == 'Fresno'
        assert by_name['Testville']['population'] == 4650
        assert by_name['Testville']['monitors'] == 1
        assert by_name['Testville']['per_10k'] == 2.15
        assert by_name['Testville']['nearest_km'] is None
        assert by_name['Emptyville']['type'] == 'City'
        assert by_name['Emptyville']['population'] == 3350
        assert by_name['Emptyville']['monitors'] == 0
        assert by_name['Emptyville']['per_10k'] == 0.0
        assert 8.5 < by_name['Emptyville']['nearest_km'] < 9.5  # centroid (-119.65, 36.75) to the monitor
        # The regions fixture also ships a real Fresno city region, whose boundary
        # holds the monitor and tract 1.01's centroid, so it is a second covered row
        # with a population of its own. `covered` and the percentage are therefore
        # derived from the rows; the uncovered side is all Emptyville.
        total_population = sum(row['population'] for row in rows)
        assert context['tiles'] == {
            'covered': sum(1 for row in rows if row['monitors']),
            'uncovered': 1,
            'uncovered_population': 3350,
            'uncovered_pct': round(3350 / total_population * 100, 1),
        }
        assert context['tiles']['covered'] == 2  # Testville and the fixture's Fresno
        assert context['tiles']['uncovered_pct'] == 26.5
        # Fixture city regions (real Fresno etc.) are also listed; the two test places sort by population.
        assert rows[0]['population'] >= rows[1]['population']

    def test_rows_link_to_the_region_admin(self):
        rows, _ = self.rows()
        by_name = {row['name']: row for row in rows}
        assert by_name['Testville']['detail_url'] == reverse('admin:regions_region_change', args=[self.testville.pk])
        response = self.client.get(reverse('reports:coverage-community'))
        assert by_name['Testville']['detail_url'] in response.content.decode()

    def test_county_islands_count_as_part_of_the_city(self):
        # Holeyville is Testville's square with a hole punched in the middle;
        # the monitor sits in the hole. For coverage the hole is filled.
        outer = Polygon.from_bbox((-119.8, 36.7, -119.7, 36.8))
        hole = Polygon.from_bbox((-119.76, 36.74, -119.74, 36.76))
        holey = Region.objects.create(name='Holeyville', slug='holeyville', type=Region.Type.CITY, external_id='9004')
        boundary = Boundary.objects.create(region=holey, version='latest', geometry=MultiPolygon(Polygon(outer.exterior_ring, hole.exterior_ring)))
        holey.boundary = boundary
        holey.save()
        rows, _ = self.rows()
        row = {r['name']: r for r in rows}['Holeyville']
        assert row['monitors'] == 1
        assert row['population'] == 4650  # tract 1.01's centroid is in the hole too

    def test_county_type_and_population_filters(self):
        assert [r['name'] for r in self.rows(county='Kern')[0]] == []
        names = {r['name'] for r in self.rows(county='Fresno')[0]}
        assert {'Testville', 'Emptyville'} <= names
        assert {r['name'] for r in self.rows(place_type='cdp')[0]} == {'Testville'}
        assert 'Emptyville' in {r['name'] for r in self.rows(place_type='city')[0]}
        rows, context = self.rows(min_population='4000')
        assert 'Emptyville' not in {r['name'] for r in rows}
        assert 'Testville' in {r['name'] for r in rows}
        # Tiles follow the scoping filters (but not the uncovered toggle).
        assert context['tiles']['uncovered'] == 0
        assert self.rows(min_population='abc')[1]['min_population'] == 0

    def test_column_sorting(self):
        rows, context = self.rows(sort='monitors', dir='desc')
        assert rows[0]['name'] == 'Testville' or rows[0]['monitors'] >= rows[-1]['monitors']
        assert context['sort'] == 'monitors' and context['direction'] == 'desc'
        rows, _ = self.rows(sort='name', dir='asc')
        names = [r['name'] for r in rows]
        assert names == sorted(names)
        rows, _ = self.rows(sort='name', dir='desc')
        assert [r['name'] for r in rows] == sorted(names, reverse=True)
        # Unknown sort/dir fall back to population descending.
        rows, context = self.rows(sort='bogus', dir='sideways')
        assert context['sort'] == 'population' and context['direction'] == 'desc'
        assert rows[0]['population'] >= rows[-1]['population']
        # None values (covered places have no nearest distance) always sort last.
        rows, _ = self.rows(sort='nearest_km', dir='asc')
        assert rows[-1]['nearest_km'] is None
        rows, _ = self.rows(sort='nearest_km', dir='desc')
        assert rows[-1]['nearest_km'] is None

    def test_header_links_carry_filters_and_flip_direction(self):
        response = self.client.get(reverse('reports:coverage-community'), {'county': 'Fresno', 'sort': 'population', 'dir': 'desc'})
        columns = {c['key']: c for c in response.context['columns']}
        assert columns['population']['active'] is True
        assert 'county=Fresno' in columns['population']['url']
        assert 'dir=asc' in columns['population']['url']  # clicking the active column flips it
        assert 'dir=asc' in columns['name']['url']
        assert 'dir=desc' in columns['monitors']['url']  # numeric columns start descending

    def test_uncovered_filter_and_name_sort(self):
        rows, context = self.rows(uncovered='1')
        assert 'Testville' not in {row['name'] for row in rows}
        assert 'Emptyville' in {row['name'] for row in rows}
        # The tiles still describe every place, not just the filtered rows.
        assert context['tiles']['covered'] == 2
        assert context['tiles']['uncovered'] == 1
        rows, _ = self.rows(sort='name')
        names = [row['name'] for row in rows]
        assert names == sorted(names)

    def test_indoor_monitors_do_not_cover(self):
        PurpleAir.objects.create(name='Indoor', sensor_id=8, position=Point(-119.65, 36.75), location='inside')
        touch(PurpleAir.objects.get(name='Indoor'), timezone.now())
        rows, _ = self.rows(include_inactive='1', include_hidden='1')
        assert {row['name']: row for row in rows}['Emptyville']['monitors'] == 0

    def test_inactive_monitor_does_not_cover(self):
        LatestEntry.objects.filter(monitor=self.monitor).update(timestamp=timezone.now() - timedelta(days=2))
        rows, context = self.rows()
        assert {row['name']: row for row in rows}['Testville']['monitors'] == 0
        assert context['tiles']['covered'] == 0
        rows, _ = self.rows(include_inactive='1')
        assert {row['name']: row for row in rows}['Testville']['monitors'] == 1

    def test_place_with_no_tract_centroid_uses_containing_tract(self):
        # A tiny CDP inside tract 1.01 has no tract centroid of its own.
        make_place('Tinyville', Region.Type.CDP, (-119.76, 36.74, -119.74, 36.745), '9003')
        rows, _ = self.rows()
        assert {row['name']: row for row in rows}['Tinyville']['population'] == 4650

    def test_places_outside_the_valley_are_excluded(self):
        # A place whose centroid is in no SJV county Region is not a community we cover.
        make_place('Outerville', Region.Type.CITY, (-122.5, 37.7, -122.4, 37.8), '9004')
        rows, _ = self.rows()
        assert 'Outerville' not in {row['name'] for row in rows}

    def test_listed_on_index(self):
        response = self.client.get(reverse('reports:index'))
        assert reverse('reports:coverage-community') in response.content.decode()


class CommunityPanelTests(StaffClientMixin, TestCase):
    fixtures = ['regions.yaml', 'calenviroscreen.yaml']

    def setUp(self):
        super().setUp()
        self.testville = make_place('Testville', Region.Type.CDP, (-119.8, 36.7, -119.7, 36.8), '9001')
        self.emptyville = make_place('Emptyville', Region.Type.CITY, (-119.7, 36.7, -119.6, 36.8), '9002')
        host = Host.objects.create(name='Library')
        self.active = PurpleAir.objects.create(name='Active PA', sensor_id=1, position=Point(-119.75, 36.75), location='outside', is_sjvair=True, host=host)
        self.stale = PurpleAir.objects.create(name='Stale PA', sensor_id=2, position=Point(-119.76, 36.76), location='outside')
        self.hidden = BAM1022.objects.create(name='Hidden BAM', position=Point(-119.77, 36.77), location='outside', is_hidden=True)
        touch(self.active, timezone.now() - timedelta(minutes=5))
        touch(self.stale, timezone.now() - timedelta(days=3))
        touch(self.hidden, timezone.now() - timedelta(minutes=5))

    def panel(self, region, **params):
        request = RequestFactory().get('/', params)
        request.user = self.user
        panels = [p for p in panels_for(region, request) if isinstance(p, CommunityCoveragePanel)]
        assert len(panels) == 1
        return panels[0].get_context()

    def test_stats_for_a_covered_place(self):
        context = self.panel(self.testville)
        assert context['county'] == 'Fresno'
        assert context['type_label'] == 'CDP'
        assert context['tracts']['population'] == 4650
        assert context['tracts']['tracts'] == 1
        assert context['tracts']['dac_tracts'] == 1
        assert context['tracts']['dac_population'] == 4650
        assert context['tracts']['max_percentile'] == 89.2
        assert context['counts'] == {'total': 3, 'active': 1, 'inactive': 1, 'hidden': 1, 'sjvair': 1}
        assert context['monitors'] == 1  # default scope: active, not hidden
        assert context['per_10k'] == 2.15
        assert context['nearest'] is None
        assert context['has_holes'] is False

    def test_monitor_rows(self):
        indoor = PurpleAir.objects.create(name='Indoor PA', sensor_id=9, position=Point(-119.75, 36.75), location='inside')
        touch(indoor, timezone.now())
        rows = {row['name']: row for row in self.panel(self.testville)['rows']}
        assert set(rows) == {'Active PA', 'Stale PA', 'Hidden BAM'}  # the indoor monitor is not listed
        assert rows['Active PA']['status'] == 'Active'
        assert rows['Stale PA']['status'] == 'Inactive'
        assert rows['Hidden BAM']['status'] == 'Hidden'
        assert rows['Active PA']['host'] == 'Library'
        assert rows['Active PA']['type'] == 'PurpleAir'
        assert rows['Active PA']['admin_url'] == reverse('admin:purpleair_purpleair_change', args=[self.active.pk])

    def test_uncovered_place_reports_nearest_monitor(self):
        context = self.panel(self.emptyville)
        assert context['monitors'] == 0
        assert context['nearest']['name'] == 'Active PA'
        assert 8.0 < context['nearest']['km'] < 10.0
        assert context['per_10k'] == 0.0

    def test_scope_toggles_change_counted_monitors(self):
        assert self.panel(self.testville, include_inactive='1', include_hidden='1')['monitors'] == 3
        assert self.panel(self.testville, sjvair_only='1')['monitors'] == 1
        links = {label: (url, on) for label, url, on in self.panel(self.testville, sjvair_only='1')['scope_links']}
        assert links['SJVAir monitors only'][1] is True
        assert 'sjvair_only' not in links['SJVAir monitors only'][0]  # clicking it turns it off
        assert 'include_hidden=1' in links['Include hidden monitors'][0]
        assert 'sjvair_only=1' in links['Include hidden monitors'][0]  # keeps the other toggle

    def test_county_islands_are_inside(self):
        outer = Polygon.from_bbox((-119.8, 36.7, -119.7, 36.8))
        hole = Polygon.from_bbox((-119.76, 36.74, -119.74, 36.76))
        holey = Region.objects.create(name='Holeyville', slug='holeyville', type=Region.Type.CITY, external_id='9004')
        boundary = Boundary.objects.create(region=holey, version='latest', geometry=MultiPolygon(Polygon(outer.exterior_ring, hole.exterior_ring)))
        holey.boundary = boundary
        holey.save()
        context = self.panel(holey)
        assert context['has_holes'] is True
        assert context['monitors'] == 1  # Active PA sits in the hole
        assert context['tracts']['population'] == 4650

    def test_admin_change_page_renders_the_panel(self):
        response = self.client.get(reverse('admin:regions_region_change', args=[self.testville.pk]))
        assert response.status_code == 200
        content = response.content.decode()
        assert '<h2>Coverage</h2>' in content
        assert 'Active PA' in content
        assert 'Nearest counted monitor' not in content
        response = self.client.get(reverse('admin:regions_region_change', args=[self.emptyville.pk]))
        assert 'Nearest counted monitor' in response.content.decode()


class CountyPanelTests(StaffClientMixin, TestCase):
    fixtures = ['regions.yaml', 'calenviroscreen.yaml']

    def setUp(self):
        super().setUp()
        self.testville = make_place('Testville', Region.Type.CDP, (-119.8, 36.7, -119.7, 36.8), '9001')
        self.emptyville = make_place('Emptyville', Region.Type.CITY, (-119.7, 36.7, -119.6, 36.8), '9002')
        self.monitor = PurpleAir.objects.create(name='In Testville', sensor_id=1, position=Point(-119.75, 36.75), location='outside')
        touch(self.monitor, timezone.now() - timedelta(minutes=5))
        self.fresno = Region.objects.counties().get(name='Fresno County')
        self.kern = Region.objects.counties().get(name='Kern County')

    def panel(self, region, **params):
        request = RequestFactory().get('/', params)
        request.user = self.user
        panels = [p for p in panels_for(region, request) if isinstance(p, CountyCoveragePanel)]
        assert len(panels) == 1
        return panels[0].get_context()

    def test_lists_the_communities_in_the_county(self):
        context = self.panel(self.fresno)
        names = {row['name']: row for row in context['communities']}
        assert {'Testville', 'Emptyville'} <= set(names)
        assert names['Testville']['monitors'] == 1
        assert names['Emptyville']['monitors'] == 0
        assert names['Emptyville']['detail_url'] == reverse('admin:regions_region_change', args=[self.emptyville.pk])
        assert context['tiles']['uncovered'] >= 1
        assert context['counts']['active'] == 1
        types = {row['label']: row for row in context['type_rows']}
        assert types['PurpleAir']['total'] == 1
        assert types['PurpleAir']['changelist_url'] == reverse('admin:purpleair_purpleair_changelist') + '?county=Fresno'
        content = self.client.get(reverse('admin:regions_region_change', args=[self.fresno.pk])).content.decode()
        assert f'<a href="{types["PurpleAir"]["changelist_url"]}">PurpleAir</a>' in content
        assert 'Testville' not in {row['name'] for row in self.panel(self.kern)['communities']}

    def test_admin_change_page_renders_the_panel(self):
        response = self.client.get(reverse('admin:regions_region_change', args=[self.fresno.pk]))
        assert response.status_code == 200
        content = response.content.decode()
        assert '<h2>Communities and coverage</h2>' in content
        assert 'Browse in admin' not in content
        assert 'In Testville</a>' not in content  # counties link to the admin instead of listing monitors


class CoverageCommunityNoCESTests(StaffClientMixin, TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        super().setUp()
        make_place('Testville', Region.Type.CDP, (-119.8, 36.7, -119.7, 36.8), '9001')
        self.monitor = PurpleAir.objects.create(name='In Testville', sensor_id=1, position=Point(-119.75, 36.75), location='outside')
        touch(self.monitor, timezone.now() - timedelta(minutes=5))

    def test_renders_without_ces_data(self):
        response = self.client.get(reverse('reports:coverage-community'))
        assert response.status_code == 200
        row = {r['name']: r for r in response.context['rows']}['Testville']
        assert row['population'] == 0
        assert row['per_10k'] is None
        assert row['monitors'] == 1
        assert response.context['tiles']['uncovered_pct'] is None
