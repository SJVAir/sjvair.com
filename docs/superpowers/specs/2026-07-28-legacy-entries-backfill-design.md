# Legacy Entries Backfill Design

**Date:** 2026-07-28
**Status:** Draft for review

## Problem

The `entries` app superseded the old monolithic `Entry` model (`camp/apps/monitors/models.py`),
but the migration to it only ran forward from whenever each monitor type was cut over —
historical legacy data was never systematically copied into the new system. There's no
existing mechanism to audit which legacy rows are missing from `entries`, and the one
stub that gestures at this, `Monitor.get_entry_migration_status()`, only compares the
*earliest* legacy timestamp to the *earliest* new-entries timestamp, so it can't detect
gaps in the interior of a monitor's history (e.g. from a period where dual-writing broke
and was later fixed).

The goal is a backfill mechanism, following the same idiom as the summaries backfill
(`docs/superpowers/specs/2026-07-13-summary-backfill-design.md`) — a DB-tracked job
driven by Huey periodic tasks — that walks all legacy `Entry` history, finds rows with
no corresponding new RAW entry (anywhere in the range, not just at the edges), and
inserts them. Reprocessing those RAW entries through the correction/cleaning/calibration
pipeline is explicitly **out of scope** — this system only fills in RAW-stage entries;
advancing them through later stages is a separate, later effort.

## Scope: which monitor types and fields

Legacy `Entry` rows only exist for **PurpleAir, AirNow, AQview, and BAM**. AirGradient
never wrote legacy rows at all (`create_entry_legacy` is never called anywhere in its
ingest path), and there is no working "Methane"/vozbox monitor type (the directory is an
empty stub) — both are excluded from this design entirely, not merely skipped at runtime.

Legacy `Entry` also predates `pm25_reported` (added ~2023): before that, only the
calibrated `pm25` value was stored, with no original reading preserved. For **PurpleAir**,
`pm25` and `pm25_reported` are genuinely different values (`pm25` is calibrated,
`pm25_reported` is the raw sensor reading) — this backfill uses `pm25_reported` only and
deliberately excludes `pm25`, so PurpleAir rows recorded before `pm25_reported` existed
are simply not backfillable for PM2.5 (they'll surface as permanent gaps, which is
correct — there's no uncalibrated value to recover). For **AirNow, AQview, and BAM**,
there was never any calibration applied — `pm25` and `pm25_reported` are the same value
whenever both are present, so those three use `COALESCE(pm25_reported, pm25)` and can be
backfilled across their full history.

Gas pollutants (CO, NO2, SO2) have no legacy counterpart at all — the old `Entry` model
never had columns for them (only AirNow's new-entries path produces them) — so they are
not part of this backfill; there is nothing to migrate.

### Field mapping table

| Monitor | EntryModel | Legacy source | Target field | Sensor | Notes |
|---|---|---|---|---|---|
| PurpleAir | PM25 | `pm25_reported` | `value` | copied from legacy row (`a`/`b`) | excludes `pm25` |
| PurpleAir | PM10 | `pm10` | `value` | copied from legacy row | legacy `pm10` is PM1.0, matches `entries.PM10` |
| PurpleAir | PM100 | `pm100` | `value` | copied from legacy row | legacy `pm100` is PM10.0, matches `entries.PM100` |
| PurpleAir | Particulates | `particles_03um`..`particles_100um` | same field names | copied from legacy row | direct copy, all 6 fields |
| PurpleAir | Temperature | `fahrenheit` | `fahrenheit` | collapsed to `''` | dedup: legacy stores same value on both `a`/`b` rows |
| PurpleAir | Humidity | `humidity` | `value` | collapsed to `''` | same dedup |
| PurpleAir | Pressure | `pressure` (hPa) | `hpa` | collapsed to `''` | **hPa**, converted via `hpa` setter |
| AirNow | PM25 | `COALESCE(pm25_reported, pm25)` | `value` | `''` | |
| AirNow | PM100 | `pm100` | `value` | `''` | |
| AirNow | O3 | `ozone` | `value` | `''` | |
| AQview | PM25 | `COALESCE(pm25_reported, pm25)` | `value` | `''` | only field AQview ever captured |
| BAM | PM25 | `COALESCE(pm25_reported, pm25)` | `value` | `''` | skip when legacy `pm25 == 99999` (bad-data sentinel) |
| BAM | Temperature | `celsius` | `celsius` | `''` | converted to fahrenheit via `celsius` setter |
| BAM | Humidity | `humidity` | `value` | `''` | |
| BAM | Pressure | `pressure` (mmHg) | `mmhg` | `''` | **mmHg already** — do not run through `hpa` setter; legacy `Entry.pressure` units differ by monitor type (PurpleAir stores hPa, BAM stores mmHg) |

This table is expressed as data, not a new class hierarchy — a plain dict keyed by
monitor model class, living in a new `camp/apps/monitors/legacy_backfill.py`, parallel
in spirit to `ENTRY_CONFIG` but pointing at legacy `Entry` attribute names instead of raw
payload keys:

```python
LEGACY_BACKFILL_MAP = {
    PurpleAir: {
        entry_models.PM25: {'source': 'pm25_reported', 'target': 'value', 'per_sensor': True},
        entry_models.PM10: {'source': 'pm10', 'target': 'value', 'per_sensor': True},
        entry_models.PM100: {'source': 'pm100', 'target': 'value', 'per_sensor': True},
        entry_models.Particulates: {
            'source': ['particles_03um', 'particles_05um', 'particles_10um',
                       'particles_25um', 'particles_50um', 'particles_100um'],
            'target': None,  # direct field-name copy
            'per_sensor': True,
        },
        entry_models.Temperature: {'source': 'fahrenheit', 'target': 'fahrenheit', 'per_sensor': False},
        entry_models.Humidity: {'source': 'humidity', 'target': 'value', 'per_sensor': False},
        entry_models.Pressure: {'source': 'pressure', 'target': 'hpa', 'per_sensor': False},
    },
    AirNow: {
        entry_models.PM25: {'source': ('pm25_reported', 'pm25'), 'target': 'value', 'per_sensor': False},
        entry_models.PM100: {'source': 'pm100', 'target': 'value', 'per_sensor': False},
        entry_models.O3: {'source': 'ozone', 'target': 'value', 'per_sensor': False},
    },
    AQview: {
        entry_models.PM25: {'source': ('pm25_reported', 'pm25'), 'target': 'value', 'per_sensor': False},
    },
    BAM: {
        entry_models.PM25: {
            'source': ('pm25_reported', 'pm25'), 'target': 'value', 'per_sensor': False,
            'skip_if': lambda legacy: legacy.pm25 == 99999,
        },
        entry_models.Temperature: {'source': 'celsius', 'target': 'celsius', 'per_sensor': False},
        entry_models.Humidity: {'source': 'humidity', 'target': 'value', 'per_sensor': False},
        entry_models.Pressure: {'source': 'pressure', 'target': 'mmhg', 'per_sensor': False},
    },
}
```

`source` as a tuple means "coalesce, first non-null wins." `per_sensor=True` means the
new entry's `sensor` is copied straight from the legacy row (PM10/PM25/PM100/Particulates,
which are genuinely per-channel); `per_sensor=False` means the new entry always uses
`sensor=''` regardless of which legacy sensor row supplied the value (Temperature/
Humidity/Pressure, which aren't channel-specific in the new schema even though legacy
duplicated them across both `a`/`b` rows).

## Gap detection

For each `(monitor, EntryModel)` pair present in `LEGACY_BACKFILL_MAP`, walk the
monitor's legacy timestamp range in fixed 7-day chunks, day-aligned, walking backward
(same chunking convention as the summaries backfill). Per chunk:

1. Query legacy `Entry` rows in `[chunk_start, chunk_end)` for that monitor, with the
   mapped source field(s) non-null (applying `skip_if` where present).
2. Query existing new-entries keys — `(timestamp, sensor)` at `stage=RAW,
   processor=''` — for that `EntryModel`/monitor/window.
3. Anti-join in Python over the chunk-sized sets (not a full-table comparison) to find
   legacy rows with no RAW counterpart. For `per_sensor=False` mappings, multiple legacy
   sensor rows can map to the same target key (`sensor=''`) — dedup before diffing so a
   monitor with both `a` and `b` rows for the same timestamp doesn't get counted or
   inserted twice.
4. Bulk-create the missing RAW entries via
   `bulk_create(..., update_conflicts=True, unique_fields=['monitor', 'timestamp', 'sensor', 'stage', 'processor'])`
   — idempotent, safe to rerun any chunk (belt-and-suspenders on top of the anti-join,
   consistent with how `summaries/backfill.py` already upserts).

This catches gaps anywhere in a monitor's history, not just at the very start or end —
the naive "compare earliest timestamps" approach (`get_entry_migration_status`, which
this design retires) misses exactly this case: a monitor whose dual-write broke for a
stretch in the middle and was later fixed.

## Job architecture

Directly mirrors `SummaryBackfillJob` (see the summaries backfill design for the full
rationale — non-blocking periodic orchestrator, fenced batch completion, staleness
recovery, cancellation semantics). The same shape, applied to this problem:

```
EntryBackfillJob                         backfill_legacy_entries_tick (periodic, every 1 min)
┌───────────────────────┐                Claim the job (locked, skip if none/locked).
│ cursor                │                phase == 'idle' and pending_tasks == 0:
│ chunk_start           │◄───────────      compute next chunk, find monitors (of the
│ range_start/range_end │                  four eligible types) with legacy Entry rows
│ state                 │                  in [chunk_start, cursor), fan out one task
│ pending_tasks         │                  per monitor, phase = 'monitors'
│ batch_id              │                phase == 'monitors' and pending_tasks == 0:
│ phase_started_at      │                  advance cursor = chunk_start, phase = 'idle'
│ locked_at             │                  if cursor <= range_start: state = 'done'
│ consecutive_failures  │                phase == 'monitors' and pending_tasks > 0
│ last_error            │                  and phase_started_at stale (>30min):
│ raw_entries_created   │                  restart batch (bump batch_id, re-dispatch)
└───────────────────────┘
```

There's only one phase here (`monitors`) — unlike the summaries job's `monitors` →
`regions` two-phase handoff, entries backfill has no second, dependent aggregation
level, so a chunk is just "dispatch one task per monitor, wait for them all to report
back, advance the cursor."

`range_start` defaults to the earliest legacy `Entry.timestamp` across all four eligible
monitor types; `range_end` defaults to now. The cursor walks backward from `range_end`,
same as summaries, so the most recent (most likely operationally relevant) gaps get
filled first.

Each `backfill_monitor_chunk(job_id, monitor_id, chunk_start, chunk_end, batch_id)` task:
iterates every `EntryModel` in that monitor's `LEGACY_BACKFILL_MAP` entry, runs the
gap-detection + bulk-create steps above for `[chunk_start, chunk_end)`, then does the
fenced update:

```python
EntryBackfillJob.objects.filter(pk=job_id, batch_id=batch_id, phase='monitors').update(
    pending_tasks=F('pending_tasks') - 1,
    raw_entries_created=F('raw_entries_created') + created_count,
)
```

Only monitors with at least one legacy `Entry` row actually falling in the chunk window
are dispatched (an `EXISTS` subquery, not the full monitor table), and only monitors of
the four eligible types — AirGradient and any other type absent from
`LEGACY_BACKFILL_MAP` never get a task at all.

## Management command

`camp/apps/monitors/management/commands/backfill_legacy_entries.py`, same shape as
`backfill_summaries`:

- `manage.py backfill_legacy_entries start [--from YYYY-MM-DD] [--to YYYY-MM-DD]` —
  creates the job. Refuses a second job while one is `running`/`paused` unless
  `--force` is passed (replaces the row, does not merge progress).
- `manage.py backfill_legacy_entries status` — prints state, cursor, % of range
  complete, `raw_entries_created`, `last_error` if any.
- `manage.py backfill_legacy_entries cancel` — sets `state` to `done`.

## Admin

Register `EntryBackfillJob` in `camp/apps/monitors/admin.py`: list view showing state,
cursor, range bounds, `raw_entries_created`, `updated`, `consecutive_failures`.
Pause/resume via the `state` field in the admin form, same as `SummaryBackfillJob`.

## Task registration

`camp/apps/monitors/tasks.py`, lowest priority on whichever queue handles monitor
maintenance work (matching the summaries backfill's convention of running behind live
traffic):

- `backfill_legacy_entries_tick` — `db_periodic_task(crontab(minute='*'), priority=1)`
- `backfill_monitor_chunk(job_id, monitor_id, chunk_start, chunk_end, batch_id)` —
  `db_task(priority=1)`

## Code layout & testing

- `camp/apps/monitors/legacy_backfill.py` — `LEGACY_BACKFILL_MAP`, plus pure,
  unit-testable helpers: chunk-range math (reused pattern from
  `camp/apps/summaries/backfill.py`), the per-`EntryModel` anti-join/gap-detection
  function, and the RAW-entry construction function (applying `source`/`target`/
  `per_sensor`/`skip_if`). These take plain querysets/values in and return plain data
  out — no Huey or job-model coupling — so they're testable without touching the task
  queue.
- `camp/apps/monitors/models.py` — add `EntryBackfillJob`; remove
  `get_entry_migration_status()` (superseded, and already unused elsewhere in the
  codebase).
- `camp/apps/monitors/tasks.py` — the tick + per-monitor-chunk tasks.
- `camp/apps/monitors/management/commands/backfill_legacy_entries.py` — start/status/cancel.
- `camp/apps/monitors/test_legacy_backfill.py` — unit tests per monitor type covering:
  the PurpleAir `pm25` exclusion, the AirNow/AQview/BAM coalesce fallback, the BAM
  99999 sentinel skip, the hPa-vs-mmHg pressure handling, the `per_sensor=False` dedup
  across `a`/`b` rows, interior-gap detection (not just head/tail), and idempotent
  re-running of an already-processed chunk. A handful of task-level tests using Huey
  immediate mode (`MemoryHuey`) confirm the fan-out/fenced-decrement/cursor-advance
  wiring end to end.

## Out of scope

- Reprocessing backfilled RAW entries through CORRECTED/CLEANED/CALIBRATED stages —
  a separate, later effort, run and scoped independently once RAW backfill is
  complete or substantially caught up.
- AirGradient and any monitor type absent from `LEGACY_BACKFILL_MAP` (no legacy data
  exists to migrate).
- CO/NO2/SO2 or any pollutant with no legacy-era counterpart.
- Per-monitor targeted backfill CLI flags, multiple concurrent jobs, or configurable
  chunk size/tick interval — same reasoning as the summaries backfill: revisit only if
  the fixed defaults prove wrong in practice.
- A replacement UI/report for per-monitor migration status beyond `status`/admin —
  job-level progress only, no new per-monitor dashboard.
