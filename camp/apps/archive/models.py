import calendar

from datetime import date, timedelta

from django.core.files.base import ContentFile
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone
from django.utils.dates import MONTHS

from django_smalluuid.models import SmallUUIDField, uuid_default

from camp.apps.archive.querysets import EntryArchiveQueryset
from camp.apps.monitors.models import Monitor
from camp.utils.test import get_response_data


def archive_data_path(instance, filename):
    path = '/'.join([
        'archive',
        f'{instance.year}',
        f'{instance.month:02d}',
        filename,
    ])
    return path


def year_validator(value):
    return MaxValueValidator(timezone.now().year)(value)


class EntryArchive(models.Model):
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    monitor = models.ForeignKey('monitors.Monitor',
        related_name='archives',
        on_delete=models.CASCADE
    )

    year = models.IntegerField(validators=[year_validator])
    month = models.IntegerField(choices=MONTHS.items())
    data = models.FileField(upload_to=archive_data_path)

    objects = EntryArchiveQueryset.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['monitor', 'year', 'month'], name='unique_archive')
        ]
        indexes = [
            models.Index(fields=['monitor', 'year', 'month']),
        ]
        ordering = ['year', 'month']

    def get_start_date(self):
        return date(self.year, self.month, 1)

    def get_end_date(self):
        last_day = calendar.monthrange(self.year, self.month)[1]
        return date(self.year, self.month, last_day) + timedelta(days=1)

    def get_filename(self):
        filename = '_'.join([
            self.monitor.__class__.__name__,
            self.monitor.slug,
            f'{self.monitor.pk}',
            f'{self.year}-{self.month}'
        ])
        return f'{filename}.csv'

    def generate(self):
        ''' Generate the actual archive file and save it to the .data field. This
            works by using Django's RequestFactory to manually call the CSV export
            endpoint for the monitor, filtered to the specified month.
            CONSIDER: This is kinda hacky, but, y'know, it works. Should look
            into refactoring the CSV generation later, e.g., using pandas.
        '''
        from camp.api.v1.monitors.endpoints import EntryCSV

        params = {
            'timestamp__gte': self.get_start_date(),
            'timestamp__lt': self.get_end_date(),
        }

        if not self.monitor.entries.filter(**params).exists():
            return

        entry_csv = EntryCSV.as_view()
        factory = RequestFactory()
        url = reverse('api:v1:monitors:entry-csv', kwargs={'monitor_id': self.monitor.pk})

        request = factory.get(url, params)
        request.monitor = self.monitor
        response = entry_csv(request)

        assert response.status_code == 200
        assert 'Content-Disposition' in response.headers
        assert response.headers['Content-Disposition'].startswith('attachment')

        content = get_response_data(response)
        content = ContentFile(content)

        self.data.save(
            name=self.get_filename(),
            content=content,
            save=False,
        )
