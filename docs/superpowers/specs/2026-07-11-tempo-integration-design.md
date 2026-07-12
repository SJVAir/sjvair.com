# TEMPO Satellite Integration Design

**Date:** 2026-07-11
**Status:** Draft

## Overview

Integrate NASA's TEMPO (Tropospheric Emissions: Monitoring of Pollution) satellite data into SJVAir. TEMPO is a geostationary UV-visible spectrometer providing hourly, daytime-only measurements across North America of tropospheric NO2, formaldehyde (HCHO), total-column ozone (O3TOT), and a UV Aerosol Index — all as atmospheric column densities, not surface concentrations. Mission data record begins 2023-08-02.

TEMPO data is fundamentally different in shape from anything else this codebase ingests: it arrives as dense gridded raster files (Level 3, ~2x2km cells covering all of North America per hour), not point readings or discrete vector shapes. It also measures a different physical quantity (column density) than ground monitors (surface concentration), so it is **not** modeled as an `Entry`/`Monitor` — it's an independent raster data source that ground monitors and communities can be compared against.

## Use Cases

1. **Map overlay** — show TEMPO columns as a regional layer for context, alongside ground monitor data.
2. **Ground monitor comparison** — sample the TEMPO column value at a monitor's coordinates for a given hour, to compare against that monitor's own readings (AirNow, AQLite/PurpleAir, future OWWL).
3. **Community/region analysis** — zonal average of TEMPO columns over a community boundary, feeding into aggregate summary stats.

Map overlay is the immediate priority; the data model is built to serve all three from day one.

## Data Source

- **Products ingested:** NO2 (tropospheric/stratospheric/total column), O3TOT (total ozone column, bundles UV Aerosol Index), HCHO (formaldehyde column), CLDO4 (cloud fraction/pressure — QA-only, not user-facing; used to interpret retrieval quality on cloudy pixels).
- **Level:** L3 gridded (pre-regridded to a regular ~2x2km lat/lon grid, one file per hour per product covering all of North America). Chosen over L2 native swath because it requires no regridding on our end and matches how the data will be displayed.
- **Access:** NASA Earthdata / Harmony API, requires an Earthdata Login (`EARTHDATA_USERNAME`/`EARTHDATA_TOKEN` env vars). Harmony performs server-side spatial subsetting to our AOI (San Joaquin Valley region bbox, via `camp/utils/geodata.load_region_geometry()`) so we never download full-CONUS files.
- **Data tiers:**
  - **NRT** — available ~180 min after observation, used for live ingestion.
  - **Standard (science-quality)** — released with a delay, supersedes NRT for the same hour once available.
  - **Ongoing reprocessing** — NASA is reprocessing the full mission archive from V03 to V04 non-chronologically, on no fixed schedule. A given historical date's authoritative version can change months after it was first imported.
- **Versioning is per-collection, not per-file.** Confirmed via live CMR queries (2026-07-12): NASA mints a *separate CMR collection* (its own `concept_id`) for each algorithm version under the same short name — e.g. `TEMPO_NO2_L3` has one collection for V03 (`C2930763263-LARC_CLOUD`) and another for V04 (`C3685896708-LARC_CLOUD`). A granule search by short name alone, without pinning a collection, is ambiguous when both a date's V03 and V04 granules exist (identical `time_start`, CMR's tie-break is undocumented and was confirmed non-deterministic-in-practice by direct testing — it returned the *older* V03 granule under `sort_key=-start_date, page_size=1`). See "CMR Version Resolution" below.

## App Location

`camp/apps/tempo/`

## Models

### `Granule`

One row per `(product, timestamp)` — the clipped hourly grid for one product, at whatever is currently the best-available NASA version. Named after NASA's own term for one hourly, per-product L3 file.

```python
class Granule(models.Model):
    class Product(models.TextChoices):
        NO2 = 'no2', 'Nitrogen Dioxide'
        O3TOT = 'o3tot', 'Total Ozone'
        HCHO = 'hcho', 'Formaldehyde'
        CLDO4 = 'cldo4', 'Cloud Fraction'

    sqid = SqidsField(alphabet=shuffle_alphabet('tempo.Granule'))

    product = models.CharField(max_length=10, choices=Product.choices)
    timestamp = models.DateTimeField()          # start of the observation hour
    version = models.CharField(max_length=10)   # NASA algorithm version, e.g. 'V03', 'V04'
    is_final = models.BooleanField(default=False)  # NRT vs standard/science-quality

    raster = gis_models.RasterField(srid=4326)  # precise grid — source for ST_Value / ST_SummaryStats
    preview = models.ImageField(upload_to='tempo/previews/')  # colorized PNG, rendered at ingest, for map display
    bounds = gis_models.PolygonField(srid=4326)  # stored explicitly so listing doesn't touch the raster column

    class Meta:
        unique_together = ('product', 'timestamp')
        indexes = [models.Index(fields=['product', 'timestamp'])]
```

`raster` and `preview` are two representations produced from the same ingest: the raw grid (for accurate point/zonal queries) and a colorized PNG (for map display), rendered once from the same in-memory array — no separate rendering pipeline or PostGIS-side `ST_AsPNG` call.

## Ingestion

### CMR Version Resolution

`TempoClient.find_granule` resolves a specific collection *before* searching for a granule, rather than searching an unversioned short name:

1. `_resolve_collections(short_name)` — a CMR *collection* search (no temporal/bbox filter — this is metadata, not a granule lookup) returning every collection matching that short name, each with its own `concept_id` and `version_id` string (e.g. `'V04'`, `'V03'`). Sorted newest-first by `version_id`. Cached in-process with a short TTL (collections change on the order of months, not worth a fresh lookup on every call, but long-running Huey workers shouldn't pin a stale list forever).
2. Try the newest collection's `concept_id` first: search granules scoped to that specific collection (not the short name) for `(timestamp, bbox)`. If found, that's the result — tagged with that collection's `version_id`.
3. If not found, try the next-newest collection, and so on. This naturally falls back to V03 for historical dates NASA hasn't reprocessed to V04 yet, while always preferring V04 once it's available for that date — deterministically, not via CMR's undocumented tie-break.
4. `find_granule`'s return dict includes `version` (the collection's `version_id` string) alongside the existing `concept_id`/`granule_id`/`collection_concept_id`/`is_final` fields — this is what makes the version comparison in `sync_granule` below cheap.

### Sync function

Core logic lives in one function, called from every ingestion path:

```python
def sync_granule(product: str, timestamp: datetime) -> Granule | None:
    """
    Finds the best-available NASA granule for (product, timestamp) and
    compares its version against what's stored -- without downloading
    anything yet. Only fetches and replaces the Granule row if NASA's
    version is actually newer than what we have. No-op if already up to
    date, which is the common case for both routine sync and re-checking
    history for reprocessing upgrades.
    """
```

Flow:
1. Call `TempoClient.find_granule(product, timestamp, bbox)` — resolves the best-available collection/granule per "CMR Version Resolution" above. This alone tells us the granule's version; no download yet.
2. Compare that version (and `is_final` tier) against the existing `Granule` row, if any, via `_should_replace` (tier-first: standard always supersedes NRT regardless of version number, NRT never replaces existing standard data; same-tier falls back to version-string comparison).
3. If no replacement is needed: return `None`. **No Harmony fetch happens in this case** — this is what makes re-checking history for reprocessing upgrades (see `sync_tempo_reprocessing` below) cheap instead of an unconditional download every time.
4. If replacement is needed: fetch the subsetted netCDF via Harmony, load into a numpy array + geotransform, build a `GDALRaster` directly from the array (no intermediate file), render the colorized PNG from the same array, and `update_or_create` the `Granule` row. The file's own `processing_version` attribute is still parsed and stored as `Granule.version` (ground truth for what was actually ingested) — CMR's collection-level version from step 1 is only used for the pre-download decision, not written to the database directly.

### Callers

| Caller | Cadence | Purpose |
|---|---|---|
| `fetch_tempo` (Huey periodic task) | Hourly, daylight hours only | Live NRT ingestion for the current hour |
| `fetch_tempo_final` (Huey periodic task) | Daily, delayed | Re-check yesterday once NASA's standard product typically lands |
| `sync_tempo_reprocessing` (Huey periodic task) | Weekly | Re-syncs a rolling window of history (e.g. the last 90 days, extendable to full mission history now that the cost concern is resolved) to catch NASA's non-chronological V03→V04 reprocessing. Cheap in the common case: `sync_granule`'s version check (CMR Version Resolution) short-circuits before any download for every hour that hasn't actually changed. |
| `import_tempo` (management command) | Manual | `manage.py import_tempo --start 2023-08-02 --end ... --product no2`. Initial full-history backfill and any ad-hoc range re-sync. Resumable — safe to interrupt and rerun since `sync_granule` skips anything already up to date. |

All four are thin wrappers around `sync_granule` — the historical backfill and everyday NRT ingestion are the same code path, just driven by a date range instead of the clock.

### Error handling / QA

- Masked or QA-flagged pixels (per `CLDO4` cloud flags and each product's own quality field) are stored as null in the raster band. `ST_Value`/`ST_SummaryStats` on a null pixel return `None`, consistent with `camp/datasci`'s "`None` not `NaN`" convention — callers must handle this explicitly.
- Harmony fetch failures use standard Huey retry/backoff.
- Retention is indefinite — the clipped grid is small (~150x50 px), so multi-year history is not a meaningful storage concern.

## Query Utilities

`camp/apps/tempo/queries.py` — small `Func` subclasses wrapping the PostGIS raster functions Django doesn't provide ORM support for, used on demand (no precomputed per-monitor/per-region tables):

```python
class STValue(Func):
    function = 'ST_Value'
    output_field = FloatField()

class STSummaryStats(Func):
    function = 'ST_SummaryStats'
    # composite return (count, sum, mean, stddev, min, max) — unpacked per-field
```

```python
def value_at_point(product: str, timestamp: datetime, point: Point) -> float | None: ...
def zonal_stats(product: str, timestamp: datetime, polygon: Polygon) -> dict | None: ...
```

These are called directly by whatever needs a comparison — internal data-tooling scripts, notebooks, or future endpoints — not precomputed at ingest. Deliberately decoupled from `Monitor`/`Region`: adding a new monitor (e.g. OWWL) or redrawing a community boundary works retroactively against existing history with no backfill step, since these functions always query the archived grid directly.

## Comparison Methodology

TEMPO measures atmospheric column density (molecules/cm², integrated through the troposphere); every ground network we compare against (AirNow, AQLite/PurpleAir, future OWWL) measures surface concentration (ppb). **There is no fixed conversion between them** — the relationship depends on boundary-layer height and vertical mixing, which shift by hour and season. NASA's own TEMPO validation uses Pandora spectrometers precisely because Pandora measures the same column quantity TEMPO does; against surface in-situ monitors, even NASA validates by correlation, not unit conversion.

So "compare TEMPO to a ground monitor" means **checking whether the two series move together over time, not whether their values agree**. `value_at_point` returns the raw column number; any comparison logic sits one layer up, in analysis code, as one of:

- **Dual-axis time series** — TEMPO's column value and the ground monitor's ppb reading plotted against the same time axis on separate y-axes, so a viewer can see whether the two lines rise and fall together without needing shared units.
- **Correlation, not conversion** — Pearson r (or a simple regression) between the paired series at a monitor's location over a rolling window, as a QA/exploration signal (e.g. correlation breaking down may indicate a plume aloft that isn't reaching the surface, rather than a data quality problem).

Neither approach requires new ingestion or storage infrastructure — both are built from `value_at_point` output paired with the monitor's own `Entry` data, entirely in analysis/presentation code.

## API

**Files:** `camp/api/v2/tempo/` (`endpoints.py`, `serializers.py`, `urls.py`), wired into `camp/api/v2/urls.py`.

| Endpoint | Description |
|---|---|
| `GET /api/2.0/tempo/` | User-facing products with label, units, and legend stops (color breaks using SJVAir's existing site palette, scaled to each product's molec/cm² range — a *secondary* legend, distinct from the ppb-based AQI legend used for ground monitors, since the two are different quantities). Excludes `CLDO4` — it's QA-only and never exposed as a toggleable layer, though it's still ingested and stored as a `Granule` row like the other products. |
| `GET /api/2.0/tempo/{product}/grids/` | Available hourly timestamps for a product — `timestamp`, `is_final`, `bounds`, `preview_url`. Defaults to today, falling back to yesterday if today's data isn't available yet. |
| `GET /api/2.0/tempo/{product}/value/?lat=&lon=&timestamp=` | Point value via `value_at_point` |
| `GET /api/2.0/tempo/{product}/zonal/?region_id=&timestamp=` | Zonal aggregate over a community boundary via `zonal_stats` |

`preview_url` is the `ImageField`'s storage URL (S3) — no dedicated image-serving view is needed.

### Frontend map flow

1. Fetch `/tempo/` once for the layer switcher and legend.
2. On enabling a layer, fetch `/tempo/{product}/grids/` for available timestamps (or default to latest).
3. Add `L.imageOverlay(grid.preview_url, grid.bounds)` to the map for the selected timestamp.
4. A time control steps through the day's hours by re-fetching step 2/3 — small JSON payloads, no re-rendering on the client.

## Deferred

- `GET /api/2.0/monitors/{id}/tempo/{product}/` (time-series of point values at a monitor's location, for comparison charts) — `value_at_point` covers this need internally for now via direct data-tooling use; add a dedicated endpoint if/when a UI needs it.
- NASA GIBS WMTS as an alternative overlay source — considered and dropped. GIBS does support subdaily TEMPO time steps matching its actual scan cadence (not day-only, as an earlier pass at this doc assumed), but it renders with NASA's own fixed scientific colormap, not ours. Self-rendering the `preview` PNG lets us use SJVAir's existing color palette for consistency with the rest of the site.
- Feeding TEMPO values into the existing `summaries` app (`MonitorSummary`/`RegionSummary`) — those are built around `Entry`'s stage/calibration pipeline, which TEMPO's column data doesn't fit. Community aggregate stats are served via `zonal_stats` directly; formal integration into the summaries rollup system is a separate future decision.
- PostGIS raster tile pyramid / XYZ tiling — the clipped AOI is small and fixed-extent, so a single `ImageOverlay` per hour is sufficient; no need for zoom-level tile generation.
