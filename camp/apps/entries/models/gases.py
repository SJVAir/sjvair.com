from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _

from .. import levels
from .base import BaseEntry


# Gases

class CO(BaseEntry):
    label = _('Carbon Monoxide')
    description = _('Colorless, odorless gas from vehicle exhaust and burning fuel.')
    epa_aqs_code = 42101
    units = 'ppm'
    summarize = True

    Levels = levels.CO

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='Carbon monoxide (ppm)',
    )


class CO2(BaseEntry):
    label = _('Carbon Dioxide')
    description = _('Gas from breathing and burning fuel; high levels indoors mean a room needs fresh air.')
    epa_aqs_code = 42102
    units = 'ppm'

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='Carbon dioxide (ppm)',
    )


class NO2(BaseEntry):
    label = _('Nitrogen Dioxide')
    description = _('Gas from vehicle and engine exhaust, highest near busy roads.')
    epa_aqs_code = 42602
    units = 'ppb'
    summarize = True

    Levels = levels.NO2

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='Nitrogen dioxide (ppb)',
    )


class O3(BaseEntry):
    label = _('Ozone')
    description = _('Ground-level gas that forms in sunlight on hot days.')
    epa_aqs_code = 44201
    units = 'ppb'
    summarize = True

    Levels = levels.O3

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='Ozone (ppb)'
    )


class SO2(BaseEntry):
    label = _('Sulfur Dioxide')
    description = _('Gas from burning fuels that contain sulfur, mostly from industry.')
    epa_aqs_code = 42401
    units = 'ppb'
    summarize = True

    Levels = levels.SO2

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text=_('Sulfur dioxide (ppb)'),
    )
