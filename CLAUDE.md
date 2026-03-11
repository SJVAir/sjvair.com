# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All development runs inside Docker.

```bash
# Start the full dev environment (web, DB, Redis, Memcached, Huey workers)
docker compose --profile web up

# Run the full test suite
docker compose run --rm test pytest

# Run a specific test file or test
docker compose run --rm test pytest camp/apps/monitors/tests.py -v
docker compose run --rm test pytest camp/apps/qaqc/tests.py::HealthCheckTests::test_grade_a_when_both_sensors_agree -v

# Run migrations / management commands
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py createsuperuser
```

Tests use `camp.settings.test` which runs Huey in immediate/synchronous mode and swaps in a local memory cache. Fixtures live in `/fixtures/*.yaml`.

## Architecture Overview

SJVAir is a Django/PostGIS air quality monitoring platform for the San Joaquin Valley. It ingests data from multiple sensor networks, processes it through a calibration pipeline, and exposes it via a versioned REST API.

### Core Data Model

**Monitors** (`camp/apps/monitors/`) are air quality devices. The base `Monitor` model has polymorphic subclasses via Django multi-table inheritance:
- `PurpleAir`, `AirGradient`, `AirNow`, `AQView`, `BAM`, `Methane`

Each monitor subclass defines an `ENTRY_CONFIG` dict that maps entry models to configuration (sensors, allowed stages, calibration processors). This config drives the entire data pipeline.

**Entries** (`camp/apps/entries/`) are time-series measurements. `BaseEntry` has subclasses per pollutant: `PM25`, `PM10`, `PM100`, `Particulates`, `Temperature`, `Humidity`, `Pressure`, `CO`, `CO2`, `NO2`, `O3`, `SO2`.

Entries move through stages: `RAW → CORRECTED → CLEANED → CALIBRATED`. Each stage is produced by a processor defined in `ENTRY_CONFIG`. `LatestEntry` tracks the most recent entry per monitor/type/processor combination.

**Health Checks** (`camp/apps/qaqc/`) run hourly per dual-channel monitor. `HealthCheckEvaluator` computes statistics (RPD, correlation, flatline ratio) for the two PM2.5 channels and assigns a score (0–3 / F–A). Results are stored in `HealthCheck` and linked back to the monitor via `monitor.health`.

**Calibrations** (`camp/apps/calibrations/`) hold trained regression models and processors. Processors are registered classes that transform one entry stage into the next. `DefaultCalibration` maps monitor type + entry type → which processor to use.

### API

Two versioned REST APIs at `/api/1.0/` and `/api/2.0/`, built on `django-resticus`. Key v2 endpoints:

- `GET /api/2.0/monitors/` — all monitors
- `GET /api/2.0/monitors/{type}/closest/` — nearest monitors by lat/lon
- `GET /api/2.0/monitors/{type}/current/` — monitors with recent healthy data
- `GET /api/2.0/monitors/{id}/entries/{type}/` — paginated entry list
- `GET /api/2.0/monitors/{id}/entries/{type}.csv` — CSV export

Serializers live next to their endpoints. Filters use `resticus.filters.FilterSet`. The `MonitorSerializer.fixup` pattern is used to add dynamic extra fields (health data, type-specific fields).

### Task Queue

Two Huey queues backed by Redis:
- **primary** — periodic tasks (cron) + sync work
- **secondary** — async one-off tasks

Task files: `camp/apps/*/tasks.py`. In tests, `MemoryHuey(immediate=True)` runs tasks inline.

### Settings

- `camp/settings/base.py` — main config
- `camp/settings/test.py` — overrides for tests (sync Huey, file email, local cache)
- `camp/settings/heroku.py` — production (S3, Memcached, SSL)

Key env vars: `DATABASE_URL`, `REDIS_URL`, `PURPLEAIR_READ_KEY`, `AIRNOW_API_KEY`, `TWILIO_*`, `AWS_*`.

### Data Science Utilities

`camp/datasci/` contains stats functions (`stats.py`), series comparison (`series.py`), and linear regression (`linear.py`). All stat functions return `Optional[float]` — they return `None` instead of `NaN` for edge cases (empty series, division by zero).

### Key Conventions

- All primary keys are `SmallUUIDField` (URL-safe UUIDs via `django-smalluuid`)
- Timezone is always `America/Los_Angeles`; `camp/utils/datetime.py` has helpers
- `Monitor.ENTRY_CONFIG` is the source of truth for what data a monitor produces and how it's processed
- `Monitor.supports_health_checks()` is an **instance method** — returns `True` only if this specific monitor instance supports dual-channel health checks (e.g., AirGradient requires `device == 'O-1PP'`)
- `Monitor.health_check_queryset_filter()` is a **classmethod** — returns a dict of queryset kwargs for filtering health-check-eligible monitors of that type in bulk
