'''
Mirror BAM 1022 entries from production into this deployment, for staging
and local development.

Only RAW entries are pulled from the production API. They are then run
through this monitor's normal processing pipeline (ENTRY_CONFIG processors),
so the CLEANED results match what production produced.

Disabled unless ``settings.BAM_MIRROR_ENABLED`` is true.
'''
from decimal import Decimal
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry

from camp.apps.entries import models as entry_models
from camp.apps.monitors.bam.models import BAM1022
from camp.utils.datetime import parse_datetime

from sjvair import SJVAirClient
from sjvair.client import DEFAULT_BASE_URL

# Maps each entry model to {model attribute: API field}, i.e. the inverse
# of the entry serializers used by the v2 API.
API_FIELD_MAP = {
    entry_models.Temperature: {'celsius': 'temperature_c'},
    entry_models.Humidity: {'value': 'value'},
    entry_models.Pressure: {'mmhg': 'pressure_mmhg'},
    entry_models.PM25: {'value': 'value'},
}


class MirrorDisabled(Exception):
    pass


def check_enabled():
    '''
    Raise MirrorDisabled if the mirror is switched off, or if this
    deployment *is* production (so we'd be mirroring from ourselves).
    '''
    if not settings.BAM_MIRROR_ENABLED:
        raise MirrorDisabled(
            'BAM mirroring is disabled in this environment. '
            'Set BAM_MIRROR_ENABLED=1 to enable it (staging / local dev only).'
        )

    own_host = urlparse(settings.DOMAIN or '').netloc
    if own_host and own_host == urlparse(DEFAULT_BASE_URL).netloc:
        raise MirrorDisabled(
            f'This deployment ({settings.DOMAIN}) is the mirror source. Refusing to mirror from itself.'
        )


def sync_monitor(data):
    '''
    Create or update the local BAM1022 record for a monitor payload from
    the production API. The production ID is preserved so entries line up
    across environments.
    '''
    fields = {
        'name': data['name'],
        'position': GEOSGeometry(str(data['position'])) if data.get('position') else None,
        'location': data.get('location') or BAM1022.LOCATION.outside,
        'is_sjvair': data.get('is_sjvair', True),
    }
    monitor, created = BAM1022.objects.update_or_create(id=data['id'], defaults=fields)
    return monitor, created


def mirror_entries(monitor, client, start, end):
    '''
    Pull RAW entries in [start, end) for every entry type the BAM supports,
    save them, and run them through the processing pipeline. Returns the
    number of raw entries created or updated.
    '''
    count = 0
    for EntryModel, field_map in API_FIELD_MAP.items():
        items = client.monitors.entries(
            monitor.pk, EntryModel.entry_type,
            stage='raw', timestamp__gte=start.isoformat(), timestamp__lt=end.isoformat(),
        )
        for item in items:
            # Coerce to Decimal so create_entry's change detection compares
            # like with like against the stored values on re-runs.
            data = {
                attr: Decimal(item[key])
                for attr, key in field_map.items()
                if item.get(key) is not None
            }
            if not data:
                continue

            entry = monitor.create_entry(
                EntryModel,
                timestamp=parse_datetime(item['timestamp']),
                sensor=item.get('sensor') or '',
                **data,
            )
            if entry is None:
                # Already present and unchanged.
                continue

            monitor.process_entry_pipeline(entry)
            count += 1
    return count


def mirror_bam_data(start, end, monitor_ids=None, log=None):
    '''
    Mirror BAM 1022 monitors and their RAW entries from production for the
    time range [start, end).

    Returns a list of (monitor, created, entry_count) tuples.
    '''
    log = log or (lambda msg: None)
    check_enabled()

    results = []
    with SJVAirClient(DEFAULT_BASE_URL) as client:
        log(f'Mirroring BAM 1022 data from {client.base_url} ({start:%Y-%m-%d %H:%M %Z} to {end:%Y-%m-%d %H:%M %Z})')

        for data in client.monitors.list(device='BAM1022'):
            if monitor_ids and data['id'] not in monitor_ids:
                continue
            monitor, created = sync_monitor(data)
            count = mirror_entries(monitor, client, start, end)
            results.append((monitor, created, count))
            log(f'  {monitor.name} ({monitor.pk}): {"created, " if created else ""}{count} raw entries')

    return results
