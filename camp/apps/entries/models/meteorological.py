from decimal import Decimal, ROUND_HALF_UP

from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _

from .base import BaseEntry


# Meteorological

class Temperature(BaseEntry):
    label = _('Temperature')
    epa_aqs_code = 62101
    units = '°F'

    value = models.DecimalField(
        max_digits=4, decimal_places=1,
        help_text=_('Temperature (°F)')
    )

    @property
    def fahrenheit(self):
        return self.value

    @fahrenheit.setter
    def fahrenheit(self, value):
        self.value = value

    @property
    def celsius(self):
        value = (Decimal(self.fahrenheit) - 32) * (Decimal(5) / Decimal(9))
        return value.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)

    @celsius.setter
    def celsius(self, value):
        value = (Decimal(value) * (Decimal(9) / Decimal(5))) + 32
        self.fahrenheit = value.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)


    def serialized_data(self):
        return {
            'temperature_f': self.fahrenheit,
            'temperature_c': self.celsius,
        }


class Humidity(BaseEntry):
    label = _('Humidity')
    epa_aqs_code = 62201
    units = '%'

    value = models.DecimalField(
        max_digits=4, decimal_places=1,
        help_text=_('Relative humidity (%)')
    )


class Pressure(BaseEntry):
    label = _('Atmospheric Pressure')
    units = 'mmHg'

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text=_('Atmospheric pressure (mmHg)'),
    )

    @property
    def mmhg(self):
        return self.value

    @mmhg.setter
    def mmhg(self, value):
        self.value = Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @property
    def hpa(self):
        return (self.mmhg * Decimal('1.33322')).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)

    @hpa.setter
    def hpa(self, value):
        self.mmhg = Decimal(value) / Decimal('1.33322')

    def serialized_data(self):
        return {
            'pressure_mmhg': self.mmhg,
            'pressure_hpa': self.hpa,
        }
