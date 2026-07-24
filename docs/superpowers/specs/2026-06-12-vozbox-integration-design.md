# VOZbox Integration Design

**Date:** 2026-06-12
**Branch:** feature/vozbox

## Overview

Integrate VOZbox air quality monitors deployed by CCEJN (Central California Environmental Justice Network) into SJVAir. VOZbox devices upload data as CSV files to a public GitHub repository (`QuinnResearch/carbVoz_data`). This integration ingests that data on a 10-minute polling cadence, running the full LCS calibration pipeline for PM2.5, and includes a backfill command for the separately-published calibrated O3 dataset.

## Data Sources

**GitHub repo:** `QuinnResearch/carbVoz_data`

Two relevant folders:

| Folder | Filename pattern | Cadence | Contents |
|---|---|---|---|
| `moospmV3_daily/` | `moospmV3_YYYY-MM-DD.csv` | One file per day, rows appended every ~10 min | Raw sensor data, all devices |
| `moospmV3_cal/` | `moospmV3_cal_YYYY-MM-DDThh.csv` | One file per UTC hour | Calibrated O3 output, all devices, months behind realtime |

Each file contains all active devices. Devices are identified by the `coreid` column (Particle hardware IDs, e.g. `e00fce68f12da1a0c5de6248`).

**Daily CSV key columns:**
- `unixtime` — Unix timestamp (seconds)
- `m_PM25_ATM`, `m_PM25_b` — PM2.5 a-channel and b-channel
- `m_PM10_ATM`, `m_PM10_b` — PM10 a-channel and b-channel
- `temp_C`, `rh` — temperature (°C) and relative humidity
- `o3` — raw O3 reading
- `lat`, `lon` — GPS coordinates (per-reading, consistent per device)
- `coreid` — device identifier

**Calibrated CSV key columns:**
- `unixtime`, `coreid`, `lat`, `lon`
- `m_PM25_CF1`, `m_PM25_ATM`, `m_PM25_b`, `m_PM10_CF1`, `m_PM10_ATM`, `m_PM10_b`
- `temp_C`, `rh`, `o3`
- `C1_T`, `C2_rh`, `C3_o3`, `b` — per-row regression coefficients (exact formula TBD — confirm with Quinn Research)
- `o3_cal` — calibrated O3 value

## Module Structure

```
camp/apps/monitors/vozbox/
├── __init__.py
├── admin.py
├── api.py                          # VozBoxClient
├── apps.py
├── management/
│   └── commands/
│       └── import_vozbox_cal.py   # calibrated O3 backfill
├── migrations/
├── models.py                       # VOZBox monitor subclass
└── tasks.py                        # periodic import + per-device processing
```

No new entry model is needed — `O3` already exists in `camp/apps/entries/`.

A new O3 calibration processor (`O3_VOZBox`) will be added to `camp/apps/calibrations/processors.py` following the existing convention (all processors live there, even device-specific ones like `AirGradientTemperature`).

## Client Library (`api.py`)

`VozBoxClient` is a stateless class used as a context manager. It owns all network I/O and CSV parsing. Nothing else in the module touches GitHub URLs or CSV column names.

```python
with VozBoxClient() as client:
    data = client.get_daily_data(date)  # dict[coreid, list[row_dict]]
```

**URL strategy:**
- Realtime downloads use `raw.githubusercontent.com` URLs constructed directly from date/hour — no GitHub API call needed, no rate limit consumed.
- Directory listing (`list_daily_files()`, `list_cal_files()`) uses the GitHub Contents API for the backfill command.

**Authentication:** Optional `GITHUB_API_TOKEN` setting (shared with any other GitHub API integrations). If present, added as `Authorization: Bearer <token>` to GitHub API requests, raising the rate limit from 60 to 5000 req/hr. Raw downloads are unaffected (no rate limit on `raw.githubusercontent.com`).

**Temp dir:** Created on `__enter__`, deleted on `__exit__`. `download_csv(url)` writes the file there and returns the path.

**Return format:** `parse_csv(filepath)` returns `dict[coreid, list[dict]]`. Each row dict uses normalized keys:

| Key | Source column |
|---|---|
| `timestamp` | `unixtime` → aware `datetime` (UTC) |
| `pm1_a` | `m_PM1_ATM` |
| `pm1_b` | `m_PM1_b` |
| `pm25_a` | `m_PM25_ATM` |
| `pm25_b` | `m_PM25_b` |
| `pm10_a` | `m_PM10_ATM` |
| `pm10_b` | `m_PM10_b` |
| `temperature` | `temp_C` |
| `humidity` | `rh` |
| `o3` | `o3` |
| `o3_cal` | `o3_cal` (calibrated CSV only) |
| `latitude` | `lat` |
| `longitude` | `lon` |

`get_daily_data(date)` returns `None` (not an exception) on 404 — the file may not exist yet for today. Same for `get_cal_data(date, hour_utc)`.

## Monitor Model (`models.py`)

```python
class VOZBox(LCSMixin, Monitor):
    DATA_PROVIDERS = [{'name': 'CCEJN', 'url': 'https://ccejn.org/'}]
    DATA_SOURCE = {'name': 'VOZbox', 'url': 'https://ccejn.org/'}
    EXPECTED_INTERVAL = '10 min'
```

`sensor_id` (from base `Monitor`) stores the `coreid`.

**`ENTRY_CONFIG`:**

| Entry type | Sensors | Fields | Stages |
|---|---|---|---|
| `PM10` | `['a', 'b']` | `value` ← `pm1_a` / `pm1_b` | RAW only |
| `PM25` | `['a', 'b']` | `value` ← `pm25_a` / `pm25_b` | RAW → CORRECTED → CLEANED → CALIBRATED (same processors as PurpleAir/AirGradient) |
| `PM100` | `['a', 'b']` | `value` ← `pm10_a` / `pm10_b` | RAW only |
| `Temperature` | `['1']` | `celsius` ← `temperature` | RAW only |
| `Humidity` | `['1']` | `value` ← `humidity` | RAW only |
| `O3` | `['1']` | `value` ← `o3` | RAW → CALIBRATED (`O3_VOZBox` processor) |

**`update_data(row)`:** Sets `position` from `latitude`/`longitude`. If `name` is empty (newly auto-created monitor), sets `name = coreid`. Sets `location = outside` (all VOZboxes are outdoor).

**`create_entries(row)`:** Maps the normalized row dict to `create_entry()` calls. Produces one entry per (entry type, sensor) pair where the value is not `None`. Same pattern as AirGradient.

**Health checks:** All VOZboxes are dual-channel — `supports_health_checks()` returns `True` unconditionally. No per-device variant needed.

## O3 Calibration

There are two distinct O3 calibration paths, and they coexist without conflict:

**External calibration (Quinn Research, via `import_vozbox_cal`):**
Calibrated O3 values from the `moospmV3_cal` CSVs are stored as O3 CALIBRATED entries with `processor=''`. No processor class is needed. `get_default_calibration` returns `''` when no `DefaultCalibration` record exists for `(VOZBox, O3)`, so these entries correctly update `LatestEntry` and appear in the API until our own calibration is operational. The unique constraint `(monitor, timestamp, sensor, stage, processor)` keeps them distinct from pipeline-produced entries.

**Internal calibration (future, `VOZBox_O3_xyz` in `camp/apps/calibrations/processors.py`):**
A future processor trained against a reference FEM O3 instrument, with temperature and humidity as covariates (matching the Quinn Research formula structure). Wired into `ENTRY_CONFIG` as a RAW → CALIBRATED processor. Inactive until a `DefaultCalibration` record for `(VOZBox, O3)` is registered. Once active, its CALIBRATED entries take over `LatestEntry`; the external entries remain in the DB but no longer update the "latest" pointer.

The calibrated CSV columns (`C1_T`, `C2_rh`, `C3_o3`, `b`) suggest a multivariate linear form using temperature, humidity, and raw O3 as inputs — confirming with Quinn Research on the exact formula would be a prerequisite to building the internal calibration.

## Tasks (`tasks.py`)

**`import_realtime`** — `@db_periodic_task(crontab(minute='*/10'), priority=50)`

Downloads today's and yesterday's daily CSVs (yesterday handles rows that landed just after midnight). For each `coreid` in the combined results, schedules `process_device`.

**`process_device(coreid, rows)`** — `@db_task()`

1. Gets or creates the `VOZBox` monitor: tries `VOZBox.objects.get(sensor_id=coreid)`; on `DoesNotExist`, instantiates `VOZBox(sensor_id=coreid)`, calls `update_data()` with the latest row to populate name/position/location, then `save()`.
2. For existing monitors, calls `update_data()` with the most recent row (keeps position current).
3. Determines the dedup cutoff from `LatestEntry` for PM2.5 RAW, sensor `a`.
4. Iterates rows in ascending timestamp order, skipping rows at or before the cutoff. `validation_check()` provides the hard dedup guarantee.
5. Calls `create_entries()` + `process_entry_pipeline()` for each new row.
6. Calls `monitor.save()`.

## Management Command (`import_vozbox_cal`)

```
python manage.py import_vozbox_cal [--start YYYY-MM-DD] [--end YYYY-MM-DD]
```

Uses `client.list_cal_files()` to enumerate available calibrated CSVs, optionally filtered to a date range. For each file:

- Downloads and parses the calibrated CSV.
- For each row, looks up the `VOZBox` monitor by `coreid` — skips unknown coreids (the realtime task creates monitors; this command does not).
- Creates an O3 entry at `Stage.CALIBRATED` using `o3_cal` directly (calibration already applied by Quinn Research — no processor run).
- Creates PM2.5/PM10/temp/humidity entries from the calibrated CSV columns where available (some rows have `NaN` coefficients, indicating no valid calibration for that reading — skip those for O3).

## Admin (`admin.py`)

Registers `VOZBox` with `ModelAdmin`. No custom actions. Standard admin interface for name and visibility management.

## Testing

- Unit tests for `VozBoxClient`: mock HTTP responses, verify CSV parsing, verify 404 → `None` behavior.
- Integration test for `process_device`: uses a fixture CSV with known rows, asserts correct entries and pipeline output.
- Management command test: fixture of calibrated CSV rows, asserts O3 CALIBRATED entries created, unknown coreids skipped.
- All tests follow project conventions: `django.test.TestCase`, plain `assert` statements, fixtures in `/fixtures/*.yaml`.
