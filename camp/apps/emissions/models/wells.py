from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _

from django_sqids import SqidsField, shuffle_alphabet


class Well(models.Model):
    """
    An oil or gas well in CalGEM's WellSTAR that is active, idle or newly
    permitted (plugged and cancelled wells aren't kept), where it is and who
    operates it. A regulatory record, not an emission: nothing here says what
    a well emits. `in_hpz` is CalGEM's own flag for SB 1137's 3,200-ft health
    protection zone around homes, schools and other sensitive receptors,
    still being revised. Refreshed weekly by import_wells.
    """

    class Status(models.TextChoices):
        ACTIVE = 'Active', _('Active')
        IDLE = 'Idle', _('Idle')
        NEW = 'New', _('New')

    class HPZ(models.TextChoices):
        VERIFIED = 'Verified HPZ', _('Verified health protection zone')
        UNCERTAIN = 'Uncertainty Area', _('Uncertainty area')
        NOT = 'Not Within HPZ', _('Not within a health protection zone')

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.Well'))
    api = models.CharField(_('API number'), max_length=14, unique=True)
    lease_name = models.CharField(_('Lease'), max_length=128, blank=True)
    well_number = models.CharField(_('Well number'), max_length=32, blank=True)
    designation = models.CharField(_('Designation'), max_length=64, blank=True)
    status = models.CharField(_('Status'), max_length=8, choices=Status.choices, db_index=True)
    well_type = models.CharField(_('Well type code'), max_length=8, blank=True)
    well_type_label = models.CharField(_('Well type'), max_length=64, blank=True)
    operator_code = models.CharField(_('Operator code'), max_length=16, blank=True)
    operator_name = models.CharField(_('Operator'), max_length=128, blank=True)
    field_name = models.CharField(_('Field'), max_length=128, blank=True)
    county = models.ForeignKey('regions.Region', verbose_name=_('County'), on_delete=models.PROTECT, related_name='wells')
    point = models.PointField(_('Point'))
    spud_date = models.DateField(_('Spud date'), null=True, blank=True)
    in_hpz = models.CharField(_('Health protection zone'), max_length=24, choices=HPZ.choices, blank=True)
    directional = models.BooleanField(_('Directionally drilled'), default=False)
    imported_at = models.DateTimeField(_('Imported at'), auto_now=True)

    class Meta:
        ordering = ['api']
        indexes = [models.Index(fields=['county', 'status'])]

    def __str__(self):
        return f'{self.label} ({self.api})'

    @property
    def label(self):
        return f'{self.lease_name} {self.well_number}'.strip() or self.api

    @property
    def calgem_url(self):
        return f'https://wellstar-public.conservation.ca.gov/WellSearch/Details?api={self.api}'
