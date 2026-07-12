from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _

from ..levels import LevelSet, AQLevel
from .base import BaseEntry


# Gases

class CO(BaseEntry):
    label = _('Carbon Monoxide')
    epa_aqs_code = 42101
    units = 'ppm'
    summarize = True

    Levels = LevelSet(
        AQLevel.GOOD(0.0),
        AQLevel.MODERATE(4.5),
        AQLevel.UNHEALTHY_SENSITIVE(9.5),
        AQLevel.UNHEALTHY(12.5),
        AQLevel.VERY_UNHEALTHY(15.5),
        AQLevel.HAZARDOUS(30.5),
        AQLevel.VERY_HAZARDOUS(50.4),
    )

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

    Levels = LevelSet(
        AQLevel.GOOD(0.0),
        AQLevel.MODERATE(54.0),
        AQLevel.UNHEALTHY_SENSITIVE(101.0),
        AQLevel.UNHEALTHY(361.0),
        AQLevel.VERY_UNHEALTHY(650.0),
        AQLevel.HAZARDOUS(1250.0),
        AQLevel.VERY_HAZARDOUS(2050.0),
    )

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='Nitrogen dioxide (ppb)',
    )


class O3(BaseEntry):
    label = _('Ozone')
    epa_aqs_code = 44201
    units = 'ppb'
    summarize = True

    Levels = LevelSet(
        AQLevel.GOOD(0.0),
        AQLevel.UNHEALTHY_SENSITIVE(125),
        AQLevel.UNHEALTHY(165),
        AQLevel.VERY_UNHEALTHY(205),
        AQLevel.HAZARDOUS(405),
        AQLevel.VERY_HAZARDOUS(605),
    )

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='Ozone (ppb)'
    )


class SO2(BaseEntry):
    label = _('Sulfur Dioxide')
    epa_aqs_code = 42401
    units = 'ppb'
    summarize = True

    Levels = LevelSet(
        AQLevel.GOOD(0),
        AQLevel.MODERATE(36),
        AQLevel.UNHEALTHY_SENSITIVE(76),
        AQLevel.UNHEALTHY(186),
        AQLevel.VERY_UNHEALTHY(305),
    )

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text=_('Sulfur dioxide (ppb)'),
    )
