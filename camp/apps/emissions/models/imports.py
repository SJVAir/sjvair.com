from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _

from django_sqids import SqidsField, shuffle_alphabet


class SourceImport(models.Model):
    """
    One finished run of an external-source import (the Consolidated Table,
    the CEIDARS toxics crawl, later ICIS-Air and the rest): when it ran, what
    it covered. Templates read the newest row per source for their "as of"
    stamps; nothing else depends on it.
    """

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.SourceImport'))
    source = models.CharField(_('Source'), max_length=32, db_index=True)
    imported_at = models.DateTimeField(_('Imported at'), auto_now_add=True)
    data_through = models.DateField(_('Data through'), null=True, blank=True)
    version = models.CharField(_('Version'), max_length=64, blank=True)
    notes = models.JSONField(_('Notes'), default=dict, blank=True)

    class Meta:
        ordering = ['-imported_at', '-pk']

    def __str__(self):
        return f'{self.source} ({self.imported_at:%Y-%m-%d})'

    @classmethod
    def latest(cls, source):
        return cls.objects.filter(source=source).order_by('-imported_at', '-pk').first()
