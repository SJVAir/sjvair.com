from django.test import TestCase, RequestFactory
from django.urls import reverse

from camp.apps.monitors.purpleair.models import PurpleAir
from camp.utils.test import debug, get_response_data

from . import endpoints

archive_list = endpoints.ArchiveList.as_view()
archive_csv = endpoints.ArchiveCSV.as_view()


class EndpointTests(TestCase):
    fixtures = ['purple-air.yaml', 'archive.yaml']

    def setUp(self):
        self.factory = RequestFactory()
        self.monitor = PurpleAir.objects.get(purple_id=8892)

    def test_get_archive_list(self):
        url = reverse('api:v1:monitors:archive:archive-list', kwargs={
            'monitor_id': self.monitor.pk
        })
        request = self.factory.get(url)
        request.monitor = self.monitor

        response = archive_list(request, monitor_id=self.monitor.pk)
        content = get_response_data(response)
        assert response.status_code == 200

    def test_get_archive_csv(self):
        archive = self.monitor.archives.first()
        url = reverse('api:v1:monitors:archive:archive-csv', kwargs={
            'monitor_id': self.monitor.pk,
            'year': f'{archive.year:04d}',
            'month': f'{archive.month:02d}',
        })
        request = self.factory.get(url)
        request.monitor = self.monitor

        response = archive_csv(request,
            monitor_id=self.monitor.pk,
            year=archive.year,
            month=archive.month,
        )
        assert response.status_code == 302
        assert response.url == archive.data.url
