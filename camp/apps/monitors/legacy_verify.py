'''
Read-only verification of the legacy `Entry` -> `entries` RAW backfill.

The expected values here are written out independently of LEGACY_BACKFILL_MAP
on purpose: re-running the backfill's own mapping would only prove the code
agrees with itself. Each new RAW row is also classified as backfilled or
live-ingested (by `created - timestamp`), so a mismatch on a live row points at
the mapping itself rather than at the backfill writer -- during the period both
systems ingested in parallel, legacy and live rows are independent copies of
the same reading.
'''
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Exists, OuterRef

from camp.apps.entries import models as entry_models
from camp.apps.monitors.legacy_backfill import pipeline_entry_models, processable_stages

NEAR_MISS_WINDOW = timedelta(seconds=60)
BAM_SENTINEL = Decimal('99999')
HPA_PER_MMHG = Decimal('1.33322')

PARTICLE_FIELDS = (
    'particles_03um', 'particles_05um', 'particles_10um',
    'particles_25um', 'particles_50um', 'particles_100um',
)


def _quantize(value, places):
    return Decimal(value).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def _coalesce(*values):
    for value in values:
        if value is not None:
            return value
    return None


def _value(value):
    return None if value is None else {'value': value}


def _particulates(legacy):
    values = {name: getattr(legacy, name) for name in PARTICLE_FIELDS}
    if any(value is None for value in values.values()):
        return None
    return values


def _hpa_to_mmhg(legacy):
    if legacy.pressure is None:
        return None
    return {'value': _quantize(legacy.pressure / HPA_PER_MMHG, '0.01')}


def _celsius_to_fahrenheit(legacy):
    if legacy.celsius is None:
        return None
    return {'value': _quantize(legacy.celsius * Decimal(9) / Decimal(5) + 32, '0.1')}


def _bam_pm25(legacy):
    value = _coalesce(legacy.pm25_reported, legacy.pm25)
    if value is None or value == BAM_SENTINEL:
        return None
    return {'value': value}


def _bam_pm25_skipped(legacy):
    return _coalesce(legacy.pm25_reported, legacy.pm25) == BAM_SENTINEL


@dataclass
class Expectation:
    expected: callable  # legacy Entry -> {field: value} or None
    per_sensor: bool = False
    skipped: callable = None  # legacy Entry -> True when deliberately not copied
    sensors: tuple = None  # per-sensor types: legacy sensors that are copied


AB = ('a', 'b')


def _expectations():
    from camp.apps.monitors.purpleair.models import PurpleAir
    from camp.apps.monitors.airnow.models import AirNow
    from camp.apps.monitors.aqview.models import AQview
    from camp.apps.monitors.bam.models import BAM1022

    return {
        PurpleAir: {
            entry_models.PM25: Expectation(lambda e: _value(e.pm25_reported), per_sensor=True, sensors=AB),
            entry_models.PM10: Expectation(lambda e: _value(e.pm10), per_sensor=True, sensors=AB),
            entry_models.PM100: Expectation(lambda e: _value(e.pm100), per_sensor=True, sensors=AB),
            entry_models.Particulates: Expectation(_particulates, per_sensor=True, sensors=AB),
            entry_models.Temperature: Expectation(lambda e: _value(e.fahrenheit)),
            entry_models.Humidity: Expectation(lambda e: _value(e.humidity)),
            entry_models.Pressure: Expectation(_hpa_to_mmhg),
        },
        AirNow: {
            entry_models.PM25: Expectation(lambda e: _value(_coalesce(e.pm25_reported, e.pm25))),
            entry_models.PM100: Expectation(lambda e: _value(e.pm100)),
            entry_models.O3: Expectation(lambda e: _value(e.ozone)),
        },
        AQview: {
            entry_models.PM25: Expectation(lambda e: _value(_coalesce(e.pm25_reported, e.pm25))),
        },
        BAM1022: {
            entry_models.PM25: Expectation(_bam_pm25, skipped=_bam_pm25_skipped),
            entry_models.Temperature: Expectation(_celsius_to_fahrenheit),
            entry_models.Humidity: Expectation(lambda e: _value(e.humidity)),
            entry_models.Pressure: Expectation(lambda e: _value(
                None if e.pressure is None else _quantize(e.pressure, '0.01')
            )),
        },
    }


EXPECTATIONS = _expectations()

COUNTERS = (
    'legacy', 'matched', 'mismatch_backfilled', 'mismatch_live', 'meta_mismatch',
    'missing', 'near_miss', 'extra', 'skipped', 'legacy_ab_disagree', 'unprocessed',
)


@dataclass
class Mismatch:
    kind: str
    monitor_id: str
    entry_type: str
    timestamp: object
    sensor: str
    detail: str


@dataclass
class VerifyReport:
    counts: dict = field(default_factory=lambda: defaultdict(lambda: dict.fromkeys(COUNTERS, 0)))
    examples: list = field(default_factory=list)
    max_examples: int = 10

    def bump(self, key, counter, amount=1):
        self.counts[key][counter] += amount

    def example(self, mismatch):
        if len(self.examples) < self.max_examples:
            self.examples.append(mismatch)

    @property
    def failed(self):
        # near_miss is informational: the backfill deliberately doesn't copy a
        # legacy row that an existing RAW row within 60s already covers.
        failing = ('mismatch_backfilled', 'mismatch_live', 'meta_mismatch', 'missing')
        return any(row[name] for row in self.counts.values() for name in failing)


def monitors_with_legacy_data(monitor_cls, range_start, range_end):
    from camp.apps.monitors.models import Entry

    entries_in_range = Entry.objects.filter(
        monitor=OuterRef('pk'),
        timestamp__gte=range_start,
        timestamp__lt=range_end,
    )
    return list(monitor_cls.objects
        .annotate(has_legacy=Exists(entries_in_range))
        .filter(has_legacy=True)
        .values_list('pk', flat=True))


def _expected_rows(legacy_rows, expectation, report, key):
    '''
    Collapses legacy rows to {(timestamp, sensor): expected_fields}. For entry
    types that aren't per-sensor, PurpleAir's a/b rows collapse onto sensor ''
    and the lowest sensor name wins; rows where a and b disagree are counted.
    '''
    expected = {}
    sources = {}
    for legacy in sorted(legacy_rows, key=lambda row: row.sensor):
        if expectation.skipped and expectation.skipped(legacy):
            report.bump(key, 'skipped')
            continue
        if expectation.sensors is not None and legacy.sensor not in expectation.sensors:
            report.bump(key, 'skipped')
            continue
        values = expectation.expected(legacy)
        if values is None:
            continue
        sensor = legacy.sensor if expectation.per_sensor else ''
        row_key = (legacy.timestamp, sensor)
        if row_key in expected:
            if expected[row_key] != values:
                report.bump(key, 'legacy_ab_disagree')
            continue
        expected[row_key] = values
        sources[row_key] = legacy
    return expected, sources


def _near(timestamp, sensor, timestamps_by_sensor):
    return any(
        abs(other - timestamp) <= NEAR_MISS_WINDOW and other != timestamp
        for other in timestamps_by_sensor.get(sensor, ())
    )


def verify_monitor_window(monitor, window_start, window_end, report, live_lag):
    from camp.apps.monitors.models import Entry

    legacy_rows = list(Entry.objects.filter(
        monitor=monitor,
        timestamp__gte=window_start,
        timestamp__lt=window_end,
    ))
    if not legacy_rows:
        return

    pipelines = pipeline_entry_models(type(monitor))

    for entry_model, expectation in EXPECTATIONS[type(monitor)].items():
        key = (type(monitor).__name__, entry_model.__name__)
        expected, sources = _expected_rows(legacy_rows, expectation, report, key)
        report.bump(key, 'legacy', len(expected))

        actual = {
            (row.timestamp, row.sensor): row
            for row in entry_model.objects.filter(
                monitor=monitor,
                stage=entry_model.Stage.RAW,
                timestamp__gte=window_start,
                timestamp__lt=window_end,
            )
        }

        actual_by_sensor = defaultdict(list)
        for timestamp, sensor in actual:
            actual_by_sensor[sensor].append(timestamp)
        expected_by_sensor = defaultdict(list)
        for timestamp, sensor in expected:
            expected_by_sensor[sensor].append(timestamp)

        for row_key, values in expected.items():
            timestamp, sensor = row_key
            row = actual.get(row_key)
            if row is None:
                if _near(timestamp, sensor, actual_by_sensor):
                    report.bump(key, 'near_miss')
                    report.example(Mismatch('near_miss', monitor.pk, entry_model.__name__, timestamp, sensor,
                        'covered by a RAW row within 60s, not copied'))
                else:
                    report.bump(key, 'missing')
                    report.example(Mismatch('missing', monitor.pk, entry_model.__name__, timestamp, sensor,
                        f'expected {values}'))
                continue

            diffs = {
                name: (value, getattr(row, name))
                for name, value in values.items()
                if getattr(row, name) != value
            }
            if diffs:
                origin = 'live' if row.created - row.timestamp <= live_lag else 'backfilled'
                report.bump(key, f'mismatch_{origin}')
                detail = ', '.join(f'{name}: expected {exp} got {got}' for name, (exp, got) in diffs.items())
                report.example(Mismatch(f'mismatch_{origin}', monitor.pk, entry_model.__name__,
                    timestamp, sensor, detail))
                continue

            legacy = sources[row_key]
            if row.location != legacy.location or row.position != legacy.position:
                report.bump(key, 'meta_mismatch')
                report.example(Mismatch('meta_mismatch', monitor.pk, entry_model.__name__, timestamp, sensor,
                    f'location {legacy.location!r} -> {row.location!r}, '
                    f'position {legacy.position} -> {row.position}'))
                continue

            report.bump(key, 'matched')

        for timestamp, sensor in actual:
            if (timestamp, sensor) not in expected and not _near(timestamp, sensor, expected_by_sensor):
                report.bump(key, 'extra')

        if entry_model in pipelines:
            report.bump(key, 'unprocessed', entry_model.objects.filter(
                monitor=monitor,
                stage__in=processable_stages(type(monitor), entry_model),
                timestamp__gte=window_start,
                timestamp__lt=window_end,
                derived_entries__isnull=True,
            ).count())


def verify(monitors, range_start, range_end, live_lag=timedelta(hours=24), max_examples=10):
    report = VerifyReport(max_examples=max_examples)
    for monitor in monitors:
        window_start = range_start
        while window_start < range_end:
            window_end = min(window_start + timedelta(days=1), range_end)
            verify_monitor_window(monitor, window_start, window_end, report, live_lag)
            window_start = window_end
    return report
