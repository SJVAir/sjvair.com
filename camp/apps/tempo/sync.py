from datetime import datetime
from typing import Optional

from django.contrib.gis.geos import Polygon
from django.core.files.base import ContentFile

from camp.utils.geodata import load_region_geometry

from .client import TempoClient
from .models import Granule
from .parsing import parse_granule
from .raster import build_raster
from .rendering import render_preview


def _should_replace(existing: Optional[Granule], new_is_final: bool, new_version: str) -> bool:
    """
    Decides whether a freshly parsed granule should replace what's stored.
    NRT and standard (science-quality) products version independently --
    confirmed via a live CMR check that NASA's NRT track sits at V02 while
    standard is at V04 -- so version strings are only comparable within
    the same tier. Standard always supersedes NRT regardless of version
    numbers; NRT never replaces existing standard data. Within the same
    tier, a higher version string wins (single-digit versions only, the
    only kind TEMPO has shipped so far; revisit if NASA reaches 'V100').
    """
    if existing is None:
        return True
    if new_is_final and not existing.is_final:
        return True
    if not new_is_final and existing.is_final:
        return False
    return new_version > existing.version


def sync_granule(product: str, timestamp: datetime, client: Optional[TempoClient] = None) -> Optional[Granule]:
    """
    Finds the best-available NASA granule for (product, timestamp) and
    compares its version against what's stored -- without downloading
    anything yet, since find_granule()'s CMR-based version resolution
    (see client.py) makes this comparison possible before any Harmony
    fetch. Only downloads and replaces the Granule row if NASA's version
    is actually newer than what we have. Returns the Granule if it was
    created/updated, or None if NASA has no granule for that hour, or if
    what's stored is already up to date.
    """
    client = client or TempoClient()
    bbox = load_region_geometry().bounds  # (lon_min, lat_min, lon_max, lat_max)

    granule_meta = client.find_granule(product, timestamp, bbox)
    if granule_meta is None:
        return None

    existing = Granule.objects.filter(product=product, timestamp=timestamp).first()
    if not _should_replace(existing, granule_meta['is_final'], granule_meta['version']):
        return None

    raw_bytes = client.fetch_granule_bytes(granule_meta, bbox)
    parsed = parse_granule(raw_bytes, product)

    raster = build_raster(parsed.array, parsed.lon_min, parsed.lat_min, parsed.lon_max, parsed.lat_max)
    bounds = Polygon.from_bbox((parsed.lon_min, parsed.lat_min, parsed.lon_max, parsed.lat_max))
    preview_bytes = render_preview(parsed.array, product)

    granule, _created = Granule.objects.update_or_create(
        product=product,
        timestamp=timestamp,
        defaults={
            'version': granule_meta['version'],
            'is_final': granule_meta['is_final'],
            'raster': raster,
            'bounds': bounds,
        },
    )
    granule.preview.save(
        # No minutes/seconds -- ingestion always writes top-of-hour
        # timestamps, so they'd always read ":00" and add nothing.
        f'{product}_{timestamp:%Y-%m-%d-%H}.png',
        ContentFile(preview_bytes),
        save=True,
    )
    return granule
