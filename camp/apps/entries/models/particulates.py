from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _

from .. import levels
from .base import BaseEntry


# Particulate Matter

class PM25(BaseEntry):
    label = _('PM2.5')
    epa_aqs_code = 88101
    units = 'µg/m³'
    summarize = True

    Levels = levels.PM25

    value = models.DecimalField(
        max_digits=7, decimal_places=2,
        help_text=_('PM2.5 (µg/m³)'),
    )



class Particulates(BaseEntry):
    label = _('Particulates')
    particles_03um = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    particles_05um = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    particles_10um = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    particles_25um = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    particles_50um = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    particles_100um = models.DecimalField(max_digits=8, decimal_places=2, null=True)


class PM10(BaseEntry):
    label = _('PM1.0')
    units = 'µg/m³'

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='PM1.0 (µg/m³)'
    )


class PM100(BaseEntry):
    label = _('PM10.0')
    epa_aqs_code = 81102
    units = 'µg/m³'

    Levels = levels.PM100

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='PM10.0 (µg/m³)'
    )
