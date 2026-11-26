from datetime import timedelta
from decimal import Decimal as D

from django.core.cache import cache
from django.db.models import Aggregate, FloatField
from django.utils.text import slugify

from camp.apps.entries.models import Humidity, PM25
from camp.apps.monitors.models import Monitor

from camp.apps.calibrations import processors
from ..base import BaseProcessor

__all__ = ['PM25_EPA_Oct2021']

# EPA's suggested stand-in when no valid RH is available (Barkjohn et al.
# 2021, AMT 14, 4617, Discussion): "substituting a value of 50 % may limit
# this error". The RH term is -0.0862 * RH, so it is off by at most
# 4.3 ug/m3 at any concentration.
DEFAULT_HUMIDITY = D('50')

COUNTY_HUMIDITY_CACHE_TIMEOUT = 60 * 60 * 3


class Median(Aggregate):
    function = 'percentile_cont'
    template = '%(function)s(0.5) WITHIN GROUP (ORDER BY %(expressions)s)'
    output_field = FloatField()


def is_valid_humidity(value):
    '''
    0 <= RH < 100. A PurpleAir's RH sensor sits in a warm case and reads
    below ambient, so an exact 100 is a failing sensor (a BME280 sticks at
    100 when moisture gets in), not fog.
    '''
    return value is not None and 0 <= value < 100


def county_humidity(county, timestamp):
    '''
    Median RAW humidity from the county's outdoor PurpleAirs over the clock
    hour before `timestamp`, as a Decimal, or None without any. PurpleAir
    RH because that's what the EPA correction was fit on; it reads lower
    than weather-station RH. Cached per (county, hour): only monitors with
    a failed RH sensor ask, and they ask every reading.

    Back-tested on outdoor PurpleAirs, 2026-10-11 to 11-10 (30,822 monitor
    hours): 7.7 %RH mean absolute error (95th percentile 24.1), against
    14.8 (35.3) for a flat 50 %. At 0.0862 ug/m3 per %RH that's 0.7 ug/m3
    on average.
    '''
    if not county:
        return None

    end = timestamp.replace(minute=0, second=0, microsecond=0)
    # slugify: memcached rejects keys with spaces ('San Joaquin').
    key = f'epa-county-humidity:{slugify(county)}:{end.isoformat()}'
    cached = cache.get(key)
    if cached is not None:
        return None if cached == '' else cached  # '' caches "no neighbors"

    median = (Humidity.objects
        .filter(
            monitor__county=county,
            monitor__purpleair__isnull=False,
            monitor__location=Monitor.LOCATION.outside,
            stage=Humidity.Stage.RAW,
            timestamp__gte=end - timedelta(hours=1),
            timestamp__lt=end,
            value__gte=0,
            value__lt=100,
        )
        .aggregate(median=Median('value'))['median']
    )
    value = D(str(round(median, 1))) if median is not None else None
    cache.set(key, value if value is not None else '', COUNTY_HUMIDITY_CACHE_TIMEOUT)
    return value


@processors.register()
class PM25_EPA_Oct2021(BaseProcessor):
    '''
    EPA's October 2021 PurpleAir correction algorithm,
    as described in the Fire and Smoke Map documentation.

    https://document.airnow.gov/airnow-fire-and-smoke-map-questions-and-answers.pdf

    RH is the monitor's own reading at the same timestamp. When that is
    missing or invalid (a failed RH sensor), it falls back to the county's
    median PurpleAir RH for the hour before, then to EPA's 50 %. An entry
    used a stand-in exactly when the monitor has no valid RAW humidity at
    its timestamp.
    '''
    label = "EPA correction (Oct 2021)"
    description = (
        "Adjusts low-cost sensor PM2.5 using humidity, following the EPA's October 2021 PurpleAir correction for the Fire and Smoke Map."
    )
    required_context = ['pm25']
    entry_model = PM25
    required_stage = PM25.Stage.CLEANED
    next_stage = PM25.Stage.CALIBRATED

    def process(self):
        value = self.get_correction(pm25=self.context['pm25'], rh=self.get_humidity())
        if value is not None:
            return self.build_entry(value=value)

    def get_humidity(self):
        humidity = self.context.get('humidity')
        if is_valid_humidity(humidity):
            return humidity
        humidity = county_humidity(self.entry.monitor.county, self.entry.timestamp)
        return DEFAULT_HUMIDITY if humidity is None else humidity

    def get_correction(self, pm25, rh):
        '''
        This function applies different formulas based on the raw PM2.5 reading (pm25).
        'rh' is the relative humidity in percent (0–100).

        Equations (pseudo-code from EPA PDF):
        1) if pm25 < 30:
            corrected = 0.524*pm25 - 0.0862*rh + 5.75

        2) if 30 ≤ pm25 < 50:
            fraction = (pm25/20) - 1.5
            corrected = [0.786*fraction + 0.524*(1 - fraction)] * pm25
                        - (0.0862*rh)
                        + 5.75

        3) if 50 ≤ pm25 < 210:
            corrected = 0.786*pm25 - 0.0862*rh + 5.75

        4) if 210 ≤ pm25 < 260:
            fraction = (pm25/50) - 4.2
            corrected = [0.69*fraction + 0.786*(1 - fraction)] * pm25
                        - [0.0862*rh * (1 - fraction)]
                        + [2.966*fraction]
                        + [5.75*(1 - fraction)]
                        + [8.84e-4 * (pm25^2) * fraction]

        5) if pm25 ≥ 260:
            corrected = 2.966 + 0.69*pm25 + 8.84e-4*(pm25^2)

        Returns the corrected PM2.5 value, clamped to a minimum of 0.0.
        '''

        if pm25 < 30:
            corrected = (D('0.524') * pm25) - (D('0.0862') * rh) + D('5.75')

        elif pm25 < 50:
            fraction = (pm25 / D('20')) - D('1.5')
            corrected = (
                (D('0.786') * fraction + D('0.524') * (D('1') - fraction)) * pm25
                - (D('0.0862') * rh)
                + D('5.75')
            )

        elif pm25 < 210:
            corrected = (D('0.786') * pm25) - (D('0.0862') * rh) + D('5.75')

        elif pm25 < 260:
            fraction = pm25 / D('50') - D('4.2')
            corrected = (
                (D('0.69') * fraction + D('0.786') * (D('1') - fraction)) * pm25
                - (D('0.0862') * rh * (D('1') - fraction))
                + (D('2.966') * fraction)
                + (D('5.75') * (D('1') - fraction))
                + (D('0.000884') * (pm25**2) * fraction)
            )

        else:
            corrected = (
                D('2.966')
                + (D('0.69') * pm25)
                + (D('0.000884') * (pm25**2))
            )

        return max(corrected, D('0.0'))
