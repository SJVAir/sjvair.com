# Summaries Design

**Date:** 2026-03-11
**Branch:** feature/summaries
**Status:** Draft

## Overview

A system for summarizing monitor and region air quality data across multiple time resolutions. Summaries serve as a first-class data product for user-facing content, a data analysis toolbox, and community data exports (eliminating the need to send raw 2-minute readings).

---

## Data Model

### `BaseSummary` (abstract)

Shared fields for both monitor and region summaries.

**Identity fields:**

| Field | Type | Notes |
|---|---|---|
| `id` | `SmallUUIDField` | Primary key |
| `resolution` | `CharField` | Choices: `hour`, `day`, `month`, `quarter`, `season`, `year` |
| `timestamp` | `DateTimeField` | Start of the aggregation window |
| `entry_type` | `EntryTypeField` | Pollutant or metric (e.g. PM2.5, Ozone) |
| `stage` | `CharField` | Pipeline stage (RAW, CORRECTED, CLEANED, CALIBRATED) |
| `processor` | `CharField` | Specific processor class; blank = uncalibrated cleaned data |

**Rollup machinery** — required for correct aggregation across time periods:

| Field | Type | Notes |
|---|---|---|
| `count` | `PositiveIntegerField` | Valid entries in the window |
| `expected_count` | `PositiveIntegerField` | Expected entries in the window |
| `sum_value` | `FloatField` | Sum of values; enables count-weighted mean rollup |
| `sum_of_squares` | `FloatField` | Enables exact stddev aggregation |
| `tdigest` | `JSONField` | Serialized T-digest; mergeable for accurate percentile rollup |

**Readable stats:**

| Field | Type |
|---|---|
| `minimum` | `FloatField` |
| `maximum` | `FloatField` |
| `mean` | `FloatField` |
| `stddev` | `FloatField` |
| `p25` | `FloatField` |
| `p75` | `FloatField` |

**Quality:**

| Field | Type | Notes |
|---|---|---|
| `is_complete` | `BooleanField` | True if `count >= 80%` of `expected_count` |

**Index:** `(timestamp, resolution, entry_type)`

---

### `MonitorSummary(BaseSummary)`

| Field | Type |
|---|---|
| `monitor` | `ForeignKey(Monitor)` |

**Unique constraint:** `(monitor, entry_type, stage, processor, resolution, timestamp)`

---

### `RegionSummary(BaseSummary)`

| Field | Type | Notes |
|---|---|---|
| `region` | `ForeignKey(Region)` | |
| `station_count` | `PositiveIntegerField` | Number of monitors that contributed |

**Unique constraint:** `(region, entry_type, stage, processor, resolution, timestamp)`

---

## Rollup Chain

Summaries are computed in a strict hierarchy. Each level aggregates from the level below:

```
entries (raw 2-min readings)
  → hourly MonitorSummary     ← only level that reads from entries table
      → daily MonitorSummary
          → monthly MonitorSummary
              → quarterly MonitorSummary
                  → seasonal MonitorSummary
                      → yearly MonitorSummary

hourly MonitorSummary (all monitors in region)
  → hourly RegionSummary
      → daily RegionSummary
          → ... (same chain as above)
```

**Aggregation rules when rolling up:**

- `count` — sum of child counts
- `expected_count` — sum of child expected counts
- `sum_value` / `sum_of_squares` — sum of child values
- `mean` — count-weighted mean: `sum_value / count`
- `stddev` — derived from `sum_of_squares`, `sum_value`, `count`
- `minimum` / `maximum` — min of mins / max of maxes
- `tdigest` — merged from child T-digests (approximation error < 1%)
- `is_complete` — True if rolled-up `count >= 80%` of `expected_count`

---

## Weighting (RegionSummary)

Weighting is applied only when computing **hourly RegionSummary** from individual monitor hourly summaries. All higher resolutions inherit weights implicitly through the rollup chain.

```
weight = type_weight × health_factor
```

| Monitor type | `type_weight` |
|---|---|
| FEM (BAM, AirNow) | High (e.g. 3) |
| LCS (PurpleAir, AirGradient) | Low (e.g. 1) |

`health_factor`:
- For monitors with a health score: `health_score / max_score` (0.0–1.0)
- For monitors without health checks (FEM, single-channel): `1.0`

Both a weighted `mean` and the raw `count`/`sum_value` fields are stored, so consumers can verify or recompute if needed.

---

## Task Pipeline

Each resolution has its own independent periodic task. Tasks are independently retriable and testable.

### Monitor Summaries

| Task | Schedule | Source |
|---|---|---|
| `hourly_monitor_summaries` | `:05` each hour | Entries table |
| `daily_monitor_summaries` | `00:15` each day | Hourly MonitorSummary |
| `monthly_monitor_summaries` | `00:30` on 1st of month | Daily MonitorSummary |
| `quarterly_monitor_summaries` | `00:45` on 1st of quarter | Monthly MonitorSummary |
| `seasonal_monitor_summaries` | `01:00` on season change | Monthly MonitorSummary |
| `yearly_monitor_summaries` | `01:15` on Jan 1 | Monthly MonitorSummary |

### Region Summaries

Region tasks run after their corresponding monitor tasks, querying completed `MonitorSummary` records.

| Task | Schedule |
|---|---|
| `hourly_region_summaries` | `:15` each hour |
| `daily_region_summaries` | `00:25` each day |
| `monthly_region_summaries` | `00:40` on 1st of month |
| (and so on for quarterly, seasonal, yearly) | |

### Monitor Selection (hourly task)

The hourly monitor task does not filter by monitor active status. It queries the entries table for distinct `monitor_id`s with entries in the target window. This captures:
- Active monitors (by definition have data)
- Recently-inactive monitors that reported during the first part of the window

### Concurrency

No task-level concurrency limiting for v1. Each monitor summary query is lightweight (~30 rows, well-indexed). If DB load becomes an issue, the lever is worker count at the Huey queue level.

---

## What's Explicitly Out of Scope (v1)

- `QCFlag` — requires detection logic that doesn't exist; `is_complete` covers the core trustworthiness signal
- `exceedance_count` / `exceedance_fraction` — requires baking in threshold definitions; consumers can compute
- `mean_of_means`, `max_of_means` — computable from MonitorSummary records
- `downtime_minutes` — `count` / `expected_count` already tells the story
- Concurrency limiting on summary tasks
- API endpoints (follow-on work)
- Admin UI beyond a stub (follow-on work)
