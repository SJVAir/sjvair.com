from datetime import timedelta

from django.contrib.gis.geos import Point
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from camp.apps.accounts.models import User
from camp.apps.alerts.models import Subscription
from camp.apps.entries.models import PM25
from camp.apps.monitors.bam.models import BAM1022
from camp.apps.monitors.models import LatestEntry, Monitor
from camp.apps.monitors.purpleair.models import PurpleAir


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
        # created is auto_now_add; push one monitor back a year for the deployments table.
        # Updated via the base Monitor queryset (not PurpleAir) to avoid a Django ORM quirk
        # where a multi-table-inheritance UPDATE joining back to the parent table for a
        # SmallUUIDField pk re-runs the pk through a bare psycopg2 uuid.UUID.
        Monitor.objects.filter(pk=self.pa_kern.pk).update(created=now - timedelta(days=365))

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

    def test_deployments_are_contiguous_and_cumulative(self):
        response = self.client.get(reverse('reports:network-overview'))
        deployments = response.context['deployments']
        assert deployments[0]['new'] == 1
        assert deployments[0]['cumulative'] == 1
        assert deployments[-1]['cumulative'] == 3
        assert len(deployments) == 5  # a year ago through now spans 5 quarter buckets
        assert sum(d['new'] for d in deployments) == 3

    def test_csv_columns(self):
        response = self.client.get(reverse('reports:network-overview'), {'format': 'csv'})
        header = response.content.decode().splitlines()[0]
        assert header == 'type,Fresno,Kern,Kings,Madera,Merced,San Joaquin,Stanislaus,Tulare,total'
