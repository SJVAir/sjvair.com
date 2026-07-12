# CIMIS Weather Integration — Design

## Summary

Add a new `CIMIS` monitor type that pulls hourly weather station data from
California's CIMIS (California Irrigation Management Information System) API,
storing it as new generic meteorological entry types alongside the existing
air-quality entries. As part of this work, split `camp/apps/entries/models.py`
into a package, since this change roughly doubles the size of its
Meteorological section.

## Background / library investigation

We considered depending on the `python-CIMIS` PyPI package
(https://pypi.org/project/python-CIMIS/). Investigation found:

- The GitHub repo (Precision-Irrigation-Management-lab/Python-CIMIS) has no
  commits, tags, or releases after 2025-07-20.
- PyPI has a `1.3.7` release published 2026-07-08 with no corresponding
  commit, tag, or release on GitHub. `setup.py` in that release even
  disagrees with `pyproject.toml` about the version number (`1.3.6` vs
  `1.3.7`).
- Diffing the `1.3.5` (last GitHub-verified) and `1.3.7` sdists found no
  malicious code (no `eval`/`exec`/`subprocess`/`os.system`/`base64`/network
  exfiltration patterns) — both versions only talk to the official
  `et.water.ca.gov` CIMIS endpoint. The release appears to be legitimate but
  sloppily maintained, not compromised.

**Decision: do not depend on `python-CIMIS`.** The CIMIS API itself is a
single authenticated GET endpoint returning JSON. We'll hand-roll a small
client, consistent with this codebase's existing per-provider API client
pattern (see `airgradient/api.py`, `purpleair/api.py`), rather than trust
an unverifiable third-party dependency for something this small.

## Entry types (`camp/apps/entries/models/meteorological.py`)

Add 10 new `BaseEntry` subclasses. These are generic meteorological types,
not CIMIS-specific — a future weather provider (NOAA, OpenWeather, etc.)
reuses them rather than getting its own duplicate set.

| Entry type | CIMIS field | Units | Conversion pattern |
|---|---|---|---|
| `DewPoint` | `hly-dew-pnt` | °F | mirrors `Temperature` (fahrenheit/celsius properties) |
| `WindSpeed` | `hly-wind-spd` | mph | plain value |
| `WindDirection` | `hly-wind-dir` | degrees | plain value |
| `Precipitation` | `hly-precip` | in | plain value |
| `SolarRadiation` | `hly-sol-rad` | W/m² | plain value |
| `NetRadiation` | `hly-net-rad` | W/m² | plain value |
| `VaporPressure` | `hly-vap-pres` | kPa | plain value |
| `SoilTemperature` | `hly-soil-tmp` | °F | mirrors `Temperature`; distinct from `Temperature` (different sensor/meaning) |
| `ETo` | `hly-asce-eto` | in | plain value; reference evapotranspiration |
| `ETr` | `hly-asce-etr` | in | plain value; alfalfa-reference evapotranspiration |

Existing `Temperature` and `Humidity` entry types are reused for CIMIS's
`hly-air-tmp` and `hly-rel-hum` fields. CIMIS's `hly-res-wind` (a combined
speed+direction vector average) is not modeled separately since
`WindSpeed`/`WindDirection` cover the same information.

Where a field has a natural alternate unit (temperature-like values), follow
the existing `Temperature`/`Pressure` convention: canonical `value` field +
property accessors for the converted unit + a `serialized_data()` override.
Fields with no natural conversion (wind direction, radiation, ETo/ETr,
precipitation, vapor pressure) get a plain `value` field, like `PM25`/`CO`.

## `entries/models.py` → `entries/models/` package

Triggered by this task nearly tripling the Meteorological section (3 → 13
classes), pushing the file from 545 lines to roughly 700-800.

```
camp/apps/entries/models/
    __init__.py        # re-exports everything, e.g. `from .base import BaseEntry`,
                        # `from .particulates import PM25, Particulates, PM10, PM100`, etc.
    base.py             # BaseEntry
    particulates.py      # PM25, Particulates, PM10, PM100
    meteorological.py    # Temperature, Humidity, Pressure + 10 new CIMIS-driven types
    gases.py               # CO, CO2, NO2, O3, SO2
```

Verified safe:
- Django keys models by `app_label.ModelName`, not file path — no migration
  impact from moving class definitions between files.
- No circular-import risk: `camp/apps/monitors/models.py` imports
  `camp.apps.entries.stages` and `camp.apps.entries.fields.EntryTypeField`,
  never `camp.apps.entries.models` — so `base.py`'s
  `from camp.apps.monitors.models import Monitor` is safe.
- All 45 existing call sites (`from camp.apps.entries.models import PM25`,
  `entries.models.PM25`, etc., across API serializers, calibration
  processors, tests, etc.) keep working unchanged via the package
  `__init__.py` re-exports.
- `BaseEntry.get_subclasses()` (built on `__subclasses__()`) is unaffected by
  which file defines a subclass, as long as every submodule is imported —
  guaranteed by `__init__.py` importing all of them at package load time.

## `CIMIS` monitor (`camp/apps/monitors/cimis/`)

Mirrors the existing `aqview`/`airnow` module layout: `models.py`,
`tasks.py`, `admin.py`, `apps.py`, plus its own API client file.

- `CIMIS(Monitor)`:
  - `LOCATION = Monitor.LOCATION.outside` always (fixed weather stations).
  - `GRADE = None` — CIMIS isn't an air-quality regulatory grade (FEM/FRM/LCS
    don't apply); `is_regulatory` and health-check machinery are AQ-specific
    and not relevant to a weather-only monitor.
  - `DATA_SOURCE`/`DATA_PROVIDERS` point at CDWR/CIMIS.
  - `station_number = models.CharField(unique=True)` — the stable external
    key for get-or-create lookups, following the `PurpleAir.sensor_id`
    precedent (not name-based lookup like `AQview`, which is more fragile
    against station renames).
  - `ENTRY_CONFIG` maps all 12 fields (10 new + reused `Temperature`/
    `Humidity`) to `RAW`-stage entries only — no calibration/processor
    pipeline, since CIMIS data is already QC'd by the state before
    publication.
- `CIMISAPI` in `camp/apps/monitors/cimis/api.py`: one `requests` session, GET
  `https://et.water.ca.gov/StationWeb/GetDataByStationNumber` with the
  `Ocp-Apim-Subscription-Key` header.

  **Naming cleanup**: the three existing providers are split between
  `api.py`/`*API` (`airgradient/api.py` → `AirGradientAPI`,
  `purpleair/api.py` → `PurpleAirAPI`) and the outlier
  `airnow/client.py` → `AirNowClient`. Standardize on `api.py`/`*API` as
  part of this task: rename `airnow/client.py` → `airnow/api.py` and
  `AirNowClient` → `AirNowAPI`, updating the import in `airnow/tasks.py`
  and the class references and `@patch` targets throughout
  `airnow/tests.py`. Use `cimis/api.py` / `CIMISAPI` for the new provider.
- New setting `CIMIS_APP_KEY` (mirrors `AIRNOW_API_KEY`) — requires
  requesting a free CIMIS app key from CDWR, documented in `CLAUDE.md`'s env
  var list.

## Station discovery + data ingestion (`tasks.py`)

Two periodic Huey tasks, following the AQview split of discovery vs. data
pull:

- `discover_cimis_stations` (infrequent, e.g. daily) — calls CIMIS's
  `GetAllStations` endpoint, filters to San Joaquin Valley counties via
  `camp.utils.counties.County` (same filter AQview uses), `get_or_create`s a
  `CIMIS` monitor per `station_number`.
- `import_cimis_data` (hourly-ish; CIMIS data typically has QC lag) — pulls
  latest hourly data for known stations via `GetDataByStationNumber`, and for
  each of the 12 mapped fields calls `handle_payload()` to create an entry.

Left open for the implementation plan (not architecture-level): which CIMIS
QC flags on individual data items are acceptable to ingest vs. skip as
missing/unreliable.

## No new abstraction for future weather providers

The codebase doesn't have a shared abstract base for same-domain monitors
today (no `PollutionMonitor` base shared by `AirNow`/`AQview`) — each
provider is its own direct `Monitor` subclass with its own `ENTRY_CONFIG`.
A second weather provider added later follows the same pattern: its own
`Monitor` subclass, reusing the meteorological entry types defined here.
Adding a `WeatherMonitor` abstract layer now would be speculative for a
single provider (YAGNI).
