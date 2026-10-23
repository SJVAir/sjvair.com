from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _

from .. import levels
from .base import BaseEntry


# Gases

class CO(BaseEntry):
    label = _('Carbon Monoxide')
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
    epa_aqs_code = 42102
    units = 'ppm'

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='Carbon dioxide (ppm)',
    )


class NO2(BaseEntry):
    label = _('Nitrogen Dioxide')
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
    epa_aqs_code = 42401
    units = 'ppb'
    summarize = True

    Levels = levels.SO2

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text=_('Sulfur dioxide (ppb)'),
    )
