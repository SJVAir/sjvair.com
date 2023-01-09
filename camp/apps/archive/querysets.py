import calendar

from datetime import date, timedelta

from django.db import models

from camp.apps.monitors.models import Monitor


class EntryArchiveQueryset(models.QuerySet):
    pass

    # def generate(self, monitor, year, month):
    #     start_date = self.get_start_date(year, month)
    #     end_date = self.get_end_date(year, month)

    #     print(' - ', monitor, start_date, end_date)

    #     archive =
