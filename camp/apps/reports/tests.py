from datetime import timedelta

from django.contrib.gis.geos import Point
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from camp.apps.accounts.models import User
from camp.apps.alerts.models import Subscription
from camp.apps.entries.models import PM25
from camp.apps.monitors.bam.models import BAM1022
from camp.apps.monitors.cimis.models import CIMIS
from camp.apps.monitors.models import Host, LatestEntry
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.monitors.vozbox.models import VOZBox
from camp.apps.qaqc.models import HealthCheck


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

    def test_csv_export(self):
        response = self.client.get(reverse('reports:subscription-county-stats'), {'format': 'csv'})
        assert response.status_code == 200
        assert response['Content-Type'] == 'text/csv'
        assert 'subscription-county-stats-' in response['Content-Disposition']
        lines = response.content.decode().splitlines()
        assert lines[0] == 'county,total_monitors,subscription_monitors,total_subscriptions'
        assert 'Fresno,1,1,1' in lines

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

    def test_tiles(self):
        response = self.client.get(reverse('reports:network-overview'))
        assert response.status_code == 200
        assert response.context['tiles'] == {'total': 3, 'active': 1, 'sjvair': 2, 'partner': 1}

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

    def test_csv_columns(self):
        response = self.client.get(reverse('reports:network-overview'), {'format': 'csv'})
        header = response.content.decode().splitlines()[0]
        assert header == 'type,Fresno,Kern,Kings,Madera,Merced,San Joaquin,Stanislaus,Tulare,Outside SJV,total'


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
        self.active = PurpleAir.objects.create(name='Active', sensor_id=1, position=Point(-119.75, 36.75), location='outside')
        self.day = PurpleAir.objects.create(name='Day', sensor_id=2, position=Point(-119.75, 36.75), location='outside')
        self.week = PurpleAir.objects.create(name='Week', sensor_id=3, position=Point(-119.0, 35.4), location='outside')
        self.long = PurpleAir.objects.create(name='Long', sensor_id=4, position=Point(-119.0, 35.4), location='outside')
        self.never = PurpleAir.objects.create(name='Never', sensor_id=5, position=Point(-119.0, 35.4), location='outside')
        self.hidden = PurpleAir.objects.create(name='Hidden', sensor_id=6, position=Point(-119.0, 35.4), location='outside', is_hidden=True)
        touch(self.active, now - timedelta(minutes=5))
        touch(self.day, now - timedelta(hours=6))
        touch(self.week, now - timedelta(days=3))
        touch(self.long, now - timedelta(days=30))
        touch(self.hidden, now - timedelta(minutes=5))
        give_health(self.active, 3)
        give_health(self.day, 1)

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
        VOZBox.objects.create(sensor_id='e00fce68f12da1a0c5de6248', name='VOZ', position=Point(-119.75, 36.75), location='outside')
        response = self.client.get(reverse('reports:fleet-health'))
        assert 'VOZBox' not in {g['type'] for g in response.context['grades']}

    def test_grade_distribution(self):
        response = self.client.get(reverse('reports:fleet-health'))
        grades = {g['type']: g for g in response.context['grades']}
        assert grades['PurpleAir'] == {'type': 'PurpleAir', 'A': 1, 'B': 0, 'C': 1, 'F': 0, 'none': 4}
        assert 'BAM1022' not in grades


class DegradedMonitorsTests(StaffClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        now = timezone.now()
        host = Host.objects.create(name='Library')
        self.fine = PurpleAir.objects.create(name='Fine', sensor_id=1, position=Point(-119.75, 36.75), location='outside')
        self.grade_f = PurpleAir.objects.create(name='Grade F', sensor_id=2, position=Point(-119.75, 36.75), location='outside', host=host)
        self.grade_c = PurpleAir.objects.create(name='Grade C', sensor_id=3, position=Point(-119.75, 36.75), location='outside')
        self.flat = PurpleAir.objects.create(name='Flat', sensor_id=4, position=Point(-119.0, 35.4), location='outside')
        self.silent = PurpleAir.objects.create(name='Silent', sensor_id=5, position=Point(-119.0, 35.4), location='outside')
        self.never = BAM1022.objects.create(name='Never', position=Point(-119.0, 35.4), location='outside')
        self.hidden = PurpleAir.objects.create(name='Hidden', sensor_id=6, position=Point(-119.0, 35.4), location='outside', is_hidden=True)
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

    def test_filters(self):
        assert [r['name'] for r in self.rows(county='Fresno')] == ['Grade F', 'Grade C']
        assert [r['name'] for r in self.rows(type='bam1022')] == ['Never']
        assert 'Hidden' in [r['name'] for r in self.rows(include_hidden='1')]

    def test_csv_columns(self):
        response = self.client.get(reverse('reports:degraded-monitors'), {'format': 'csv'})
        header = response.content.decode().splitlines()[0]
        assert header == 'name,type,county,host,grade,last_seen,condition'


class CoverageTests(StaffClientMixin, TestCase):
    fixtures = ['calenviroscreen.yaml']

    def setUp(self):
        super().setUp()
        # Fixture tracts, both Fresno: 1.01 (DAC, pop 4650) spans lon -119.8..-119.7,
        # lat 36.7..36.8; 1.02 (not a DAC, pop 3350) spans lon -119.7..-119.6.
        # This monitor sits inside 1.02, ~890 m east of the DAC tract's edge
        # (at lat 36.75, 0.01 degrees of longitude is ~890 m).
        self.near_dac = PurpleAir.objects.create(name='Near DAC', sensor_id=1, position=Point(-119.69, 36.75), location='outside')
        # Kern, outside any fixture tract.
        self.kern = PurpleAir.objects.create(name='Kern', sensor_id=2, position=Point(-119.0, 35.4), location='outside')

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
        PurpleAir.objects.create(name='In DAC', sensor_id=3, position=Point(-119.75, 36.75), location='outside')
        response = self.client.get(reverse('reports:coverage'))
        rows = {row['county']: row for row in response.context['rows']}
        assert rows['Fresno']['monitors'] == 2
        assert rows['Fresno']['dac_monitors'] == 1

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

    def test_csv_columns(self):
        response = self.client.get(reverse('reports:coverage'), {'format': 'csv'})
        header = response.content.decode().splitlines()[0]
        assert header == 'county,monitors,population,per_10k,dac_tracts,dac_monitors,dac_population,dac_population_covered,dac_covered_pct'


class CoverageNoCESTests(StaffClientMixin, TestCase):
    """The report still renders when no CalEnviroScreen data has been imported."""

    def setUp(self):
        super().setUp()
        self.monitor = PurpleAir.objects.create(name='Fresno', sensor_id=1, position=Point(-119.75, 36.75), location='outside')

    def test_renders_without_ces_data(self):
        response = self.client.get(reverse('reports:coverage'))
        assert response.status_code == 200
        assert response.context['ces_version'] is None
        assert response.context['percentile_bands'] == []
        fresno = {row['county']: row for row in response.context['rows']}['Fresno']
        assert fresno['monitors'] == 1
        assert fresno['population'] == 0
        assert fresno['per_10k'] is None

    def test_csv_export_without_ces_data(self):
        response = self.client.get(reverse('reports:coverage'), {'format': 'csv'})
        assert response.status_code == 200
        header = response.content.decode().splitlines()[0]
        assert header == 'county,monitors,population,per_10k,dac_tracts,dac_monitors,dac_population,dac_population_covered,dac_covered_pct'
