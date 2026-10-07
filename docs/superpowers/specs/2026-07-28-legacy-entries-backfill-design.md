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
inserts them. A second phase then drives those RAW entries (and any other historical
RAW entries left incompletely processed by prior migration attempts) through the
existing correction/cleaning/calibration pipeline.

There is already a partial, previously-run migration mechanism —
`migrate_legacy_entry` / `copy_legacy_entries` / `copy_legacy_entries_range`
(`camp/apps/entries/tasks.py:17-117`) — which this design replaces. It has the same
"compare earliest timestamps" blind spot this design fixes (`copy_legacy_entries` only
migrates `[earliest_legacy_timestamp, earliest_pm25_entry_timestamp)`), and a known bug
in its `Pressure` mapping (see **Pressure correction**, below). It is not otherwise
touched by this design — no code from it is reused — but its past runs are the reason
some monitors already have partially-migrated and partially-piped entries, which is why
gap detection (RAW phase) and pipeline completion (pipeline phase) both need to handle
"partially done," not just "fully done" or "not started."

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

## Pipeline idempotency fix (prerequisite for the pipeline phase)

`BaseProcessor.run()` (`camp/apps/calibrations/core/processors/base.py:104-113`) already
guards against duplicate/erroring re-creation of an entry: `validation_check()`
(`entries/models.py:182-193`) checks whether a matching `(monitor, timestamp, sensor,
stage, processor)` row already exists, and if so, `run()` returns `None` instead of
saving a duplicate. That part is already safe to call repeatedly.

The bug is in what happens *next*: `process_entry_ng`/`process_entry_pipeline`
(`camp/apps/monitors/models.py:396-428`) only recurses into entries a call actually
**created** — when `run()` returns `None` because the entry already existed, the
recursion stops there, even if a *later* stage is still missing. Concretely: a RAW
entry whose CORRECTED entry already exists (e.g. left over from a previous partial
migration or a crashed task) but whose CLEANED/CALIBRATED entries don't will never get
those later stages filled in by calling `process_entry_pipeline` again — the call
silently stops at CORRECTED and reports nothing wrong.

Fix: change the "entry already exists" branch to return the **existing** entry instead
of `None`. `process_entry_ng`/`process_entry_pipeline`'s recursion then continues into
that existing entry regardless of whether this call created it or found it already
there, so a partially-processed chain always completes on re-run. This is a shared fix
in `BaseProcessor.run()`, not a backfill-only wrapper — it also makes real-time ingest
self-healing (e.g. after a task crashes mid-pipeline) instead of silently stuck, and
avoids a second, parallel "make it idempotent" implementation living only in the
backfill code.

Existing behavior is unchanged for the common case (nothing exists yet → create and
recurse as before) and for the fully-processed case (everything exists → each stage's
`run()` returns its existing entry, `process_entry_ng` finds no *stage* missing, so no
extra processor work happens — just cheap existence lookups). Needs a unit test
covering the specific "CORRECTED exists, CLEANED doesn't" case, since that's the case
that's silently broken today.

## Phase 2: pipeline reprocessing

Once RAW entries exist (whether from this backfill or left over from prior partial
migrations), a second, independently-runnable job drives them through
correction/cleaning/calibration. This is a separate job from the RAW backfill above —
it can run anytime, doesn't need to wait for the RAW job to reach `done`, and is safe to
re-run repeatedly (idempotent, per the fix above) — matching "re-run as-needed" as a
first-class requirement, not an afterthought.

**Which `EntryModel`s are in scope:** driven directly from `ENTRY_CONFIG`, not a
hardcoded per-monitor-type list — any `EntryModel` whose `ENTRY_CONFIG` entry declares a
`processors` key has a pipeline to run; its terminal stage is
`config['allowed_stages'][-1]` (e.g. `CALIBRATED` for PurpleAir's `PM25`/`Temperature`/
`Humidity`, `CLEANED` for AirNow/AQview's `PM25`). Entry models with no `processors` key
(PurpleAir's `PM10`, `PM100`, `Particulates`) have nothing to reprocess and are skipped.

**Selection, per chunk per monitor per eligible `EntryModel`:** revised from the
terminal-stage anti-join originally sketched here. Instead, mirroring the existing
`derived_entries__isnull=True` idiom already used by `process_monitor_history`
(`camp/apps/monitors/purpleair/tasks.py`), it selects `stage=RAW` entries in the chunk
window that have *no derived entries of any kind* — i.e. the pipeline was never even
attempted. For each match, call `monitor.process_entry_pipeline(raw_entry)` (no
`cutoff_stage`, so the pipeline runs all the way to its terminal stage).

This is a deliberate, signed-off tradeoff, not an oversight: a terminal-stage anti-join
cannot correctly handle PurpleAir's dual-sensor PM25 merge-and-defer semantics, where
`PM25_LCS_Correction` merges both sensor channels into a single `sensor=''` CORRECTED
entry and only the alphabetically-first sensor's RAW row ever produces a derived entry
at all — the other sensor's RAW row is expected to stay childless forever. A
terminal-stage check keyed on `(monitor, timestamp, sensor)` would misidentify that
RAW row as perpetually incomplete. The accepted limitation is the flip side: a RAW
entry stuck partway through the pipeline (e.g. `CORRECTED` exists but
`CLEANED`/`CALIBRATED` doesn't, from an earlier crashed/partial run) is *not* detected,
since it already has at least one derived entry. Completing such partially-stuck chains
is out of scope for this feature.

**Job/task shape:** identical pattern to the RAW backfill job — a new
`PipelineBackfillJob` (same fields: `state`, `cursor`, `chunk_start`, `range_start`/
`range_end`, `pending_tasks`, `batch_id`, `phase_started_at`, `locked_at`,
`consecutive_failures`, `last_error`, plus `entries_processed`), a periodic
`reprocess_legacy_pipeline_tick` task, and a per-monitor `reprocess_monitor_chunk(job_id,
monitor_id, chunk_start, chunk_end, batch_id)` task doing the fenced `pending_tasks`
decrement. Kept as a separate job model (not a second phase bolted onto
`EntryBackfillJob`) since it has its own independent lifecycle — it isn't gated on the
RAW job's cursor, and re-running it later (e.g. after a calibration change) shouldn't
require re-running RAW backfill too.

`range_start`/`range_end` default the same way — earliest RAW entry timestamp across the
four eligible monitor types → now — and the cursor walks backward, same rationale as
the RAW job (recent data most likely to matter operationally).

Management command `camp/apps/monitors/management/commands/reprocess_legacy_pipeline.py`,
same `start`/`status`/`cancel` shape as `backfill_legacy_entries`.

## Pressure correction (one-time data repair)

The old `migrate_legacy_entry` (`camp/apps/entries/tasks.py:17-117`) mapped legacy
`pressure` directly to the new `Pressure` entry's `value` field
(`{'pressure': 'value'}`, line 34) with no unit conversion, for every monitor type
generically. Per the field mapping table above, legacy `pressure` is stored in hPa for
PurpleAir but mmHg for BAM — a direct copy is only correct for BAM. Any PurpleAir
`Pressure` RAW entries created by that old code path are storing raw hPa values
mislabeled as the mmHg-denominated `value` field (hPa ≈ 950–1050 typically; correctly
converted mmHg values would be ≈ 712–787 — the two ranges don't overlap, so this is
detectable without needing to know which code path created a given row).

One-time repair, run before or independently of the two jobs above (it's bounded to
however many PurpleAir `Pressure` RAW rows currently exist — not an open-ended
chunked backfill, so no job-tracking machinery needed):

1. For every PurpleAir `Pressure` RAW entry, look up the corresponding legacy `Entry`
   row(s) for `(monitor, timestamp)` (either sensor — pressure isn't per-channel) and
   compute the correct value via the `hpa` setter.
2. If the entry's current `value` differs from the correctly-converted value beyond a
   small tolerance (rounding), update it in place (`save(update_fields=['value'])`).
   This recompute-and-compare approach sidesteps needing to identify *which* rows the
   old buggy code touched — it's self-correcting for any PurpleAir `Pressure` entry,
   regardless of provenance.
3. Log a count of corrected rows for visibility (not a full job/report system — a
   one-time repair, not a recurring capability).

A management command, `camp/apps/monitors/management/commands/fix_purpleair_pressure.py`,
wraps this — synchronous, since the affected row count is bounded and small relative to
the full historical backfill volume.

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
- `reprocess_legacy_pipeline_tick` — `db_periodic_task(crontab(minute='*'), priority=1)`
- `reprocess_monitor_chunk(job_id, monitor_id, chunk_start, chunk_end, batch_id)` —
  `db_task(priority=1)`

## Code layout & testing

- `camp/apps/monitors/legacy_backfill.py` — `LEGACY_BACKFILL_MAP`, plus pure,
  unit-testable helpers: chunk-range math (reused pattern from
  `camp/apps/summaries/backfill.py`), the per-`EntryModel` anti-join/gap-detection
  function (reused for both the RAW-missing check and the terminal-stage-missing
  check), and the RAW-entry construction function (applying `source`/`target`/
  `per_sensor`/`skip_if`). These take plain querysets/values in and return plain data
  out — no Huey or job-model coupling — so they're testable without touching the task
  queue.
- `camp/apps/calibrations/core/processors/base.py` — the `BaseProcessor.run()`
  idempotency fix (return the existing entry instead of `None` when one already
  matches).
- `camp/apps/monitors/models.py` — add `EntryBackfillJob` and `PipelineBackfillJob`;
  remove `get_entry_migration_status()` (superseded, and already unused elsewhere in
  the codebase).
- `camp/apps/monitors/tasks.py` — both jobs' tick + per-monitor-chunk tasks.
- `camp/apps/monitors/management/commands/backfill_legacy_entries.py` — start/status/cancel.
- `camp/apps/monitors/management/commands/reprocess_legacy_pipeline.py` — start/status/cancel.
- `camp/apps/monitors/management/commands/fix_purpleair_pressure.py` — the one-time
  Pressure repair.
- `camp/apps/monitors/test_legacy_backfill.py` — unit tests per monitor type covering:
  the PurpleAir `pm25` exclusion, the AirNow/AQview/BAM coalesce fallback, the BAM
  99999 sentinel skip, the hPa-vs-mmHg pressure handling, the `per_sensor=False` dedup
  across `a`/`b` rows, interior-gap detection (not just head/tail), and idempotent
  re-running of an already-processed chunk. A handful of task-level tests using Huey
  immediate mode (`MemoryHuey`) confirm the fan-out/fenced-decrement/cursor-advance
  wiring end to end, for both jobs.
- `camp/apps/calibrations/test_processors.py` (or wherever processor tests currently
  live) — a test for the specific "CORRECTED exists, CLEANED doesn't" case the
  idempotency fix addresses, plus confirming the fully-processed and
  nothing-processed-yet cases are unchanged.
- A test for `fix_purpleair_pressure`, confirming it corrects a synthetically
  mislabeled hPa value and leaves an already-correct mmHg value untouched.

## Out of scope

- AirGradient and any monitor type absent from `LEGACY_BACKFILL_MAP` (no legacy data
  exists to migrate).
- CO/NO2/SO2 or any pollutant with no legacy-era counterpart.
- Per-monitor targeted backfill CLI flags, multiple concurrent jobs, or configurable
  chunk size/tick interval — same reasoning as the summaries backfill: revisit only if
  the fixed defaults prove wrong in practice.
- A replacement UI/report for per-monitor migration status beyond `status`/admin —
  job-level progress only, no new per-monitor dashboard.
- Auditing/correcting other already-migrated fields for provenance-independent
  correctness the way the Pressure repair does — Pressure is the one known case with a
  cross-monitor-type unit mismatch; no other field mapping has this property.
