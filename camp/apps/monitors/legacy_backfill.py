'''
Field mapping and pure construction logic for backfilling legacy `Entry` rows
(camp/apps/monitors/models.py) into the new `entries` app, RAW stage only.
See docs/superpowers/specs/2026-07-28-legacy-entries-backfill-design.md.
'''
from datetime import timedelta

from django.db.models import Exists, OuterRef

from camp.apps.entries import models as entry_models


def _bam_pm25_sentinel(legacy_entry):
    return legacy_entry.pm25 == 99999


LEGACY_BACKFILL_MAP = {}


def _register(monitor_cls, mapping):
    LEGACY_BACKFILL_MAP[monitor_cls] = mapping


def _load_map():
    from camp.apps.monitors.purpleair.models import PurpleAir
    from camp.apps.monitors.airnow.models import AirNow
    from camp.apps.monitors.aqview.models import AQview
    from camp.apps.monitors.bam.models import BAM1022

    _register(PurpleAir, {
        entry_models.PM25: {'source': 'pm25_reported', 'target': 'value', 'per_sensor': True},
        entry_models.PM10: {'source': 'pm10', 'target': 'value', 'per_sensor': True},
        entry_models.PM100: {'source': 'pm100', 'target': 'value', 'per_sensor': True},
        entry_models.Particulates: {
            'source': [
                'particles_03um', 'particles_05um', 'particles_10um',
                'particles_25um', 'particles_50um', 'particles_100um',
            ],
            'per_sensor': True,
        },
        entry_models.Temperature: {'source': 'fahrenheit', 'target': 'fahrenheit', 'per_sensor': False},
        entry_models.Humidity: {'source': 'humidity', 'target': 'value', 'per_sensor': False},
        entry_models.Pressure: {'source': 'pressure', 'target': 'hpa', 'per_sensor': False},
    })

    _register(AirNow, {
        entry_models.PM25: {'source': ('pm25_reported', 'pm25'), 'target': 'value', 'per_sensor': False},
        entry_models.PM100: {'source': 'pm100', 'target': 'value', 'per_sensor': False},
        entry_models.O3: {'source': 'ozone', 'target': 'value', 'per_sensor': False},
    })

    _register(AQview, {
        entry_models.PM25: {'source': ('pm25_reported', 'pm25'), 'target': 'value', 'per_sensor': False},
    })

    _register(BAM1022, {
        entry_models.PM25: {
            'source': ('pm25_reported', 'pm25'), 'target': 'value', 'per_sensor': False,
            'skip_if': _bam_pm25_sentinel,
        },
        entry_models.Temperature: {'source': 'celsius', 'target': 'celsius', 'per_sensor': False},
        entry_models.Humidity: {'source': 'humidity', 'target': 'value', 'per_sensor': False},
        entry_models.Pressure: {'source': 'pressure', 'target': 'mmhg', 'per_sensor': False},
    })


_load_map()


def build_raw_entry(monitor, legacy_entry, entry_model, mapping):
    '''
    Given a legacy Entry row and its mapping (one value of a LEGACY_BACKFILL_MAP
    entry), return an unsaved `entry_model` RAW instance, or None if the source
    data is missing or explicitly skipped.
    '''
    skip_if = mapping.get('skip_if')
    if skip_if and skip_if(legacy_entry):
        return None

    source = mapping['source']
    target = mapping.get('target')

    if isinstance(source, list):
        values = {}
        for field_name in source:
            value = getattr(legacy_entry, field_name)
            if value is None:
                return None
            values[field_name] = value
    else:
        if isinstance(source, tuple):
            value = None
            for field_name in source:
                value = getattr(legacy_entry, field_name)
                if value is not None:
                    break
        else:
            value = getattr(legacy_entry, source)

        if value is None:
            return None

        values = {target: value}

    sensor = legacy_entry.sensor if mapping.get('per_sensor') else ''

    entry = entry_model(
        monitor=monitor,
        timestamp=legacy_entry.timestamp,
        sensor=sensor,
        position=legacy_entry.position,
        location=legacy_entry.location,
        stage=entry_model.Stage.RAW,
        processor='',
    )
    for field_name, value in values.items():
        setattr(entry, field_name, value)

    return entry


def eligible_monitor_classes():
    return list(LEGACY_BACKFILL_MAP.keys())


def chunk_start_for(cursor, range_start, chunk_days=7):
    return max(cursor - timedelta(days=chunk_days), range_start)


def _source_fields(mapping):
    source = mapping['source']
    if isinstance(source, list):
        return list(source)
    if isinstance(source, tuple):
        return list(source)
    return [source]


def find_missing_raw_entries(monitor, entry_model, mapping, chunk_start, chunk_end):
    '''
    Returns unsaved entry_model instances for legacy Entry rows in the window
    that have no corresponding RAW entry yet. Safe to call repeatedly.
    '''
    from django.db.models import Q
    from camp.apps.monitors.models import Entry

    field_filter = Q()
    for field_name in _source_fields(mapping):
        field_filter |= Q(**{f'{field_name}__isnull': False})

    legacy_qs = Entry.objects.filter(
        field_filter,
        monitor=monitor,
        timestamp__gte=chunk_start,
        timestamp__lt=chunk_end,
    )

    existing_keys = set(
        entry_model.objects.filter(
            monitor=monitor,
            stage=entry_model.Stage.RAW,
            timestamp__gte=chunk_start,
            timestamp__lt=chunk_end,
        ).values_list('timestamp', 'sensor')
    )

    seen = set()
    missing = []
    for legacy_entry in legacy_qs:
        entry = build_raw_entry(monitor, legacy_entry, entry_model, mapping)
        if entry is None:
            continue
        key = (entry.timestamp, entry.sensor)
        if key in existing_keys or key in seen:
            continue
        seen.add(key)
        missing.append(entry)

    return missing


def monitors_with_legacy_data_in(chunk_start, chunk_end):
    '''
    Returns pks of monitors (of the eligible types) with at least one legacy
    Entry row in [chunk_start, chunk_end).
    '''
    from camp.apps.monitors.models import Entry

    entries_in_range = Entry.objects.filter(
        monitor=OuterRef('pk'),
        timestamp__gte=chunk_start,
        timestamp__lt=chunk_end,
    )

    monitor_ids = set()
    for monitor_cls in eligible_monitor_classes():
        ids = (monitor_cls.objects
            .annotate(has_legacy=Exists(entries_in_range))
            .filter(has_legacy=True)
            .values_list('pk', flat=True))
        monitor_ids.update(ids)
    return list(monitor_ids)


def pipeline_entry_models(monitor_class):
    '''
    EntryModels this monitor type both backfills from legacy data and runs
    through a processing pipeline (declares 'processors' in ENTRY_CONFIG),
    mapped to their terminal (final configured) stage.
    '''
    result = {}
    mapping = LEGACY_BACKFILL_MAP.get(monitor_class, {})
    for entry_model in mapping:
        config = monitor_class.ENTRY_CONFIG.get(entry_model, {})
        if 'processors' in config:
            result[entry_model] = config['allowed_stages'][-1]
    return result


def find_incomplete_pipelines(monitor, entry_model, terminal_stage, chunk_start, chunk_end):
    '''
    Returns RAW-stage entry_model instances in the window that have no
    corresponding terminal-stage entry yet (any processor). Safe to call
    repeatedly.
    '''
    raw_qs = entry_model.objects.filter(
        monitor=monitor,
        stage=entry_model.Stage.RAW,
        timestamp__gte=chunk_start,
        timestamp__lt=chunk_end,
    )

    complete_keys = set(
        entry_model.objects.filter(
            monitor=monitor,
            stage=terminal_stage,
            timestamp__gte=chunk_start,
            timestamp__lt=chunk_end,
        ).values_list('timestamp', 'sensor')
    )

    return [
        entry for entry in raw_qs
        if (entry.timestamp, entry.sensor) not in complete_keys
    ]


def monitors_with_incomplete_pipelines_in(chunk_start, chunk_end):
    '''
    Returns pks of monitors (of the eligible types) with at least one RAW
    entry in [chunk_start, chunk_end) missing its terminal-stage counterpart,
    across any of that monitor type's pipeline-eligible entry models.
    '''
    monitor_ids = set()
    for monitor_cls in eligible_monitor_classes():
        models_map = pipeline_entry_models(monitor_cls)
        if not models_map:
            continue

        for entry_model, terminal_stage in models_map.items():
            # Cheap pre-filter: get monitors with any RAW at all in window
            raw_in_range = entry_model.objects.filter(
                monitor=OuterRef('pk'),
                stage=entry_model.Stage.RAW,
                timestamp__gte=chunk_start,
                timestamp__lt=chunk_end,
            )
            candidate_monitors = (monitor_cls.objects
                .annotate(has_raw=Exists(raw_in_range))
                .filter(has_raw=True)
                .values_list('pk', flat=True))

            # Precise check: for each candidate monitor, check if any RAW entry
            # is missing its terminal-stage counterpart, since comparing per-entry
            # keys isn't expressible as a single annotation without risking false
            # negatives on the sensor-collapse cases.
            for monitor_id in candidate_monitors:
                monitor = monitor_cls.objects.get(pk=monitor_id)
                incomplete = find_incomplete_pipelines(
                    monitor, entry_model, terminal_stage, chunk_start, chunk_end,
                )
                if incomplete:
                    monitor_ids.add(monitor_id)

    return list(monitor_ids)
