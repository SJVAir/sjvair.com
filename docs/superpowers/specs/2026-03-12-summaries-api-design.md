# Summaries API Design

**Date:** 2026-03-12
**Branch:** feature/summaries
**Status:** Draft

## Overview

Two new API namespaces under `/api/2.0/`:

1. **Regions API** — list and detail endpoints for `Region` records
2. **Summary endpoints** — nested under both monitors and regions, returning paginated `MonitorSummary` and `RegionSummary` records

---

## Regions API

**Location:** `camp/api/v2/regions/`

### Endpoints

| Method | URL | Description |
|---|---|---|
| GET | `/api/2.0/regions/` | List all regions |
| GET | `/api/2.0/regions/{id}/` | Region detail with geometry |

### Filters

- `?type=county` — filter by `Region.type` (county, city, zip, air_basin, etc.)

### List response (no geometry)

```json
[
  {"id": "abc123", "name": "Fresno County", "type": "county"}
]
```

### Detail response (includes geometry)

```json
{
  "id": "abc123",
  "name": "Fresno County",
  "type": "county",
  "geometry": { ... }
}
```

Geometry comes from `region.boundary.geometry`. If `region.boundary` is null, geometry is `null`.

---

## Summary Endpoints

### URL Structure

Summary endpoints are nested under both monitors and regions. Resolution is a path segment. Date components are progressively optional — omitting narrows nothing, specifying narrows the result set. Pagination handles large results.

**Monitor summaries:**
```
/api/2.0/monitors/{id}/summaries/{entry_type}/hourly/{year}/
/api/2.0/monitors/{id}/summaries/{entry_type}/hourly/{year}/{month}/
/api/2.0/monitors/{id}/summaries/{entry_type}/hourly/{year}/{month}/{day}/

/api/2.0/monitors/{id}/summaries/{entry_type}/daily/{year}/
/api/2.0/monitors/{id}/summaries/{entry_type}/daily/{year}/{month}/

/api/2.0/monitors/{id}/summaries/{entry_type}/monthly/{year}/
/api/2.0/monitors/{id}/summaries/{entry_type}/quarterly/{year}/
/api/2.0/monitors/{id}/summaries/{entry_type}/seasonal/{year}/

/api/2.0/monitors/{id}/summaries/{entry_type}/yearly/
```

**Region summaries:** identical pattern with `/regions/{id}/` prefix.

### URL Parameters

| Segment | Values |
|---|---|
| `entry_type` | `pm25`, `o3`, `co`, `no2`, `so2` (any summarizable type) |
| `year` | 4-digit year |
| `month` | 1–12 |
| `day` | 1–31 |

Invalid entry types or resolutions → 404.

### Query Parameters

**Monitor summaries only:**
- `?processor=` — filter by processor string. Omitting returns `processor=''` (raw/uncalibrated) records. Pass a specific processor name (e.g. `PM25_EPA_Oct2021`) for calibrated data.

**Region summaries:** no processor param — always returns best-available calibration blend.

### Pagination

Standard resticus pagination. Default page size TBD (suggest 168 for hourly — one week).

### Response Fields

**Monitor summary record:**
```json
{
  "timestamp": "2026-03-15T09:00:00-07:00",
  "entry_type": "pm25",
  "processor": "",
  "count": 28,
  "expected_count": 30,
  "minimum": 4.2,
  "maximum": 18.7,
  "mean": 11.3,
  "stddev": 3.1,
  "p25": 8.9,
  "p75": 13.8,
  "is_complete": true
}
```

**Region summary record** (same but with `station_count`, no `processor`):
```json
{
  "timestamp": "2026-03-15T09:00:00-07:00",
  "entry_type": "pm25",
  "count": 340,
  "expected_count": 390,
  "minimum": 2.1,
  "maximum": 24.3,
  "mean": 11.8,
  "stddev": 4.2,
  "p25": 8.5,
  "p75": 14.9,
  "is_complete": true,
  "station_count": 13
}
```

Rollup machinery fields (`sum_value`, `sum_of_squares`, `tdigest`) are **not exposed**.

### Ordering

Results ordered by `timestamp` ascending. Clients page forward through time.

---

## File Structure

```
camp/api/v2/regions/
  __init__.py
  endpoints.py     # RegionList, RegionDetail
  serializers.py   # RegionSerializer (list), RegionDetailSerializer (with geometry)
  filters.py       # RegionFilter (type)
  urls.py

camp/api/v2/summaries/
  __init__.py
  endpoints.py     # MonitorSummaryList, RegionSummaryList (one view per resolution)
  serializers.py   # MonitorSummarySerializer, RegionSummarySerializer
  filters.py       # SummaryFilter (processor for monitor)
  urls.py          # Registered under both monitors/ and regions/
```

### Registration

In `camp/api/v2/urls.py`:
```python
path('regions/', include('camp.api.v2.regions.urls', namespace='regions')),
```

In `camp/api/v2/monitors/urls.py`:
```python
path('<monitor_id>/summaries/', include('camp.api.v2.summaries.monitor_urls')),
```

In `camp/api/v2/regions/urls.py`:
```python
path('<region_id>/summaries/', include('camp.api.v2.summaries.region_urls')),
```

---

## Out of Scope (v1)

- CSV export of summaries
- Summary gap detection
- Filtering by date range via query params (date is in the URL)
- `LatestSummary` model
