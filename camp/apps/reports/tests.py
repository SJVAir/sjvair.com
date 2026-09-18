from datetime import datetime, timedelta

from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from camp.apps.accounts.models import User
from camp.apps.alerts.models import Subscription
from camp.apps.calibrations.models import DefaultCalibration
from camp.apps.entries.models import PM25
from camp.apps.monitors.airgradient.models import AirGradient
from camp.apps.monitors.bam.models import BAM1022
from camp.apps.monitors.cimis.models import CIMIS
from camp.apps.monitors.models import Host, LatestEntry, Monitor
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.monitors.vozbox.models import VOZBox
from camp.apps.qaqc.models import HealthCheck
from camp.apps.regions.models import Boundary, Region
from camp.apps.reports.base import REPORTS
from camp.apps.summaries.models import MonitorSummary


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


def daily_summary(monitor, day, count, expected, entry_type='pm25'):
    """A RAW daily MonitorSummary for `day` (a date) with the given count/expected."""
    timestamp = timezone.make_aware(datetime.combine(day, datetime.min.time()))
    return MonitorSummary.objects.create(
        monitor=monitor, entry_type=entry_type, processor='',
        resolution=MonitorSummary.Resolution.DAILY, timestamp=timestamp,
        count=count, expected_count=expected, sum_value=float(count), sum_of_squares=float(count),
        tdigest={}, minimum=1.0, maximum=1.0, mean=1.0, stddev=0.0, p25=1.0, p75=1.0,
        is_complete=count >= expected,
    )


class DataCompletenessTests(StaffClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.good = PurpleAir.objects.create(name='Good', sensor_id=1, position=Point(-119.75, 36.75), location='outside', is_sjvair=True)
        self.bad = PurpleAir.objects.create(name='Bad', sensor_id=2, position=Point(-119.0, 35.4), location='outside', is_sjvair=True)
        self.partner = PurpleAir.objects.create(name='Partner', sensor_id=3, position=Point(-119.75, 36.75), location='outside')
        self.silent = PurpleAir.objects.create(name='Silent', sensor_id=4, position=Point(-119.75, 36.75), location='outside', is_sjvair=True)
        self.bam = BAM1022.objects.create(name='BAM', position=Point(-119.75, 36.75), location='outside', is_sjvair=True)
        yesterday = timezone.localdate() - timedelta(days=1)
        for offset in range(7):
            day = yesterday - timedelta(days=offset)
            daily_summary(self.good, day, 720, 720)
            daily_summary(self.bad, day, 360, 720)
            daily_summary(self.partner, day, 720, 720)
            daily_summary(self.bam, day, 24, 24)
        for offset in range(7, 30):
            daily_summary(self.good, yesterday - timedelta(days=offset), 720, 720)
        # Today's partial day must not count.
        daily_summary(self.good, timezone.localdate(), 10, 720)

    def rows(self, **params):
        response = self.client.get(reverse('reports:data-completeness'), params)
        assert response.status_code == 200
        return response.context

    def test_per_type_windows(self):
        context = self.rows()
        purpleair = {r['type']: r for r in context['rows']}['PurpleAir']
        # SJVAir only by default: Good, Bad, Silent (no rows) -> 7d: (720+360)*7 / 720*14 ... Silent has no expected rows.
        assert purpleair['monitors'] == 3
        assert purpleair['received_7'] == (720 + 360) * 7
        assert purpleair['expected_7'] == 720 * 14
        assert purpleair['pct_7'] == 75.0
        assert purpleair['received_30'] == 720 * 30 + 360 * 7
        assert purpleair['expected_30'] == 720 * 30 + 720 * 7
        bam = {r['type']: r for r in context['rows']}['BAM1022']
        assert bam['pct_7'] == 100.0
        assert context['entry_type'] == 'pm25'

    def test_low_table_worst_first_with_silent_monitors_on_top(self):
        context = self.rows()
        low = [(r['name'], r['pct_7']) for r in context['low']]
        assert low == [('Silent', 0.0), ('Bad', 50.0)]
        assert context['low'][1]['admin_url'] == reverse('admin:purpleair_purpleair_change', args=[self.bad.pk])

    def test_threshold_and_scope_filters(self):
        assert [r['name'] for r in self.rows(threshold='40')['low']] == ['Silent']
        assert 'Partner' not in [r['name'] for r in self.rows(sjvair_only='0')['low']]  # Partner is at 100%, never low
        purpleair = {r['type']: r for r in self.rows(sjvair_only='0')['rows']}['PurpleAir']
        assert purpleair['monitors'] == 4
        purpleair = {r['type']: r for r in self.rows(county='Kern')['rows']}['PurpleAir']
        assert purpleair['monitors'] == 1
        assert purpleair['pct_7'] == 50.0

    def test_entry_type_selector(self):
        daily_summary(self.good, timezone.localdate() - timedelta(days=1), 100, 200, entry_type='humidity')
        context = self.rows(entry_type='humidity')
        purpleair = {r['type']: r for r in context['rows']}['PurpleAir']
        assert purpleair['pct_7'] == 50.0
        assert ('humidity', 'Humidity') in context['entry_types']
        assert self.rows(entry_type='nope')['entry_type'] == 'pm25'


class DataQualityTests(StaffClientMixin, TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        super().setUp()
        host = Host.objects.create(name='Library')
        fresno = Point(-119.75, 36.75)
        self.fine = PurpleAir.objects.create(name='Fine', sensor_id=1, position=fresno, location='outside', is_sjvair=True, host=host)
        self.outsider = PurpleAir.objects.create(name='Paso Robles', sensor_id=2, position=Point(-120.69, 35.63), location='outside')
        self.no_position = PurpleAir.objects.create(name='No position', sensor_id=3, location='outside')
        self.bogus = PurpleAir.objects.create(name='Bogus', sensor_id=4, position=Point(0, 0), location='outside')
        self.no_name = PurpleAir.objects.create(name='', sensor_id=5, position=fresno, location='outside')
        self.no_county = PurpleAir.objects.create(name='No county', sensor_id=6, position=fresno, location='outside')
        Monitor.objects.filter(pk=self.no_county.pk).update(county='')
        self.wrong_county = PurpleAir.objects.create(name='Wrong county', sensor_id=7, position=fresno, location='outside')
        Monitor.objects.filter(pk=self.wrong_county.pk).update(county='Kern')
        self.hidden = PurpleAir.objects.create(name='Hidden reporting', sensor_id=8, position=fresno, location='outside', is_hidden=True)
        touch(self.hidden, timezone.now() - timedelta(minutes=5))
        self.no_host = BAM1022.objects.create(name='No host', position=fresno, location='outside', is_sjvair=True)

    def rows(self, **params):
        response = self.client.get(reverse('reports:data-quality'), params)
        assert response.status_code == 200
        return response.context

    def test_each_check_fires_once_and_clean_monitors_are_absent(self):
        context = self.rows()
        by_name = {row['name']: row['condition'] for row in context['rows']}
        assert by_name == {
            'No position': 'No position',
            'Bogus': 'Bogus position',
            self.no_name.pk: 'No name',
            'No county': 'No county',
            'Wrong county': 'Wrong county',
            'Hidden reporting': 'Hidden but reporting',
            'No host': 'No host',
        }
        assert context['tiles']['total'] == 7
        assert context['tiles']['No county'] == 1

    def test_sorted_by_check_order_then_name(self):
        names = [row['name'] for row in self.rows()['rows']]
        assert names == ['No position', 'Bogus', self.no_name.pk, 'No county', 'Wrong county', 'Hidden reporting', 'No host']

    def test_columns_and_filters(self):
        context = self.rows()
        row = {r['name']: r for r in context['rows']}['Wrong county']
        assert row['type'] == 'PurpleAir'
        assert row['county'] == 'Kern'
        assert row['position'] == '36.7500, -119.7500'
        assert row['admin_url'] == reverse('admin:purpleair_purpleair_change', args=[self.wrong_county.pk])
        assert [r['name'] for r in self.rows(type='bam1022')['rows']] == ['No host']
        assert [r['name'] for r in self.rows(county='Kern')['rows']] == ['Wrong county']


class DataQualityNoRegionsTests(StaffClientMixin, TestCase):
    """With no county Regions loaded, the county checks must not flag everything."""

    def test_county_checks_need_county_regions(self):
        monitor = PurpleAir.objects.create(name='Fine', sensor_id=1, position=Point(-119.75, 36.75), location='outside')
        assert monitor.county == 'Fresno'
        response = self.client.get(reverse('reports:data-quality'))
        assert response.status_code == 200
        assert response.context['rows'] == []
        assert response.context['tiles']['total'] == 0


class PipelineCoverageTests(StaffClientMixin, TestCase):
    fixtures = ['default-calibrations.yaml']

    def test_matrix_cells(self):
        response = self.client.get(reverse('reports:pipeline-coverage'))
        assert response.status_code == 200
        rows = {row['type']: row for row in response.context['rows']}
        pm25 = rows['PurpleAir']['pm25']
        assert pm25['published'] is True
        assert pm25['calibration'] == DefaultCalibration.objects.get(monitor_type='purpleair', entry_type='pm25').calibration
        assert 'Raw' in pm25['stages']
        assert rows['PurpleAir']['humidity']['published'] is False
        assert rows['VOZBox']['pm25']['published'] is False
        assert rows['BAM1022']['humidity'] is None or rows['BAM1022']['humidity']['published'] is False
        assert ('pm25', 'PM2.5') in response.context['entry_types']
        assert response.context['unpublished_count'] > 0

    def test_orphaned_publish_rows(self):
        DefaultCalibration.objects.create(monitor_type='purpleair', entry_type='co2', calibration='')
        response = self.client.get(reverse('reports:pipeline-coverage'))
        orphans = [(o['monitor_type'], o['entry_type']) for o in response.context['orphans']]
        assert ('purpleair', 'co2') in orphans
        assert ('purpleair', 'pm25') not in orphans
