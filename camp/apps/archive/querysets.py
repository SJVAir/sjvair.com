import calendar

from datetime import date, timedelta

from django.db import models

from camp.apps.monitors.models import Monitor


class EntryArchiveQueryset(models.QuerySet):
    def generate(self, monitor, year, month):
        try:
            archive = self.get(monitor_id=monitor.pk, year=year, month=month)
        except self.model.DoesNotExist:
            archive = self.model(monitor=monitor, year=year, month=month)

        archive.generate()
        if archive.data:
            archive.save()
        return archive
