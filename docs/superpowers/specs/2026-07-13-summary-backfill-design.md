# Summary Backfill Design

**Date:** 2026-07-13
**Status:** Draft for review

## Problem

`rebuild_summaries` can compute summaries for a date range, but running it for the
full history (2020–2026, all monitors and regions) needs to happen without:

- requiring someone to babysit a long-lived terminal session, and
- enqueueing hundreds of thousands of individual Huey tasks at once (the existing
  `--async` mode of `rebuild_summaries` fans out one task per hour × monitor ×
  entry_type × processor combination).

The goal is a mechanism that walks backward from the start of the current month
to 2020-01-01, self-paces, survives worker restarts/deploys without manual
intervention, and produces hourly/daily/monthly/quarterly/seasonal/yearly summaries
for both monitors and regions along the way — using the same idiom this codebase
already relies on for all other recurring maintenance: Huey periodic tasks (there
is no external cron/scheduler dyno in this project; see `Procfile`).

## Architecture

A single DB-tracked job with one backward-walking cursor, advanced by a periodic
Huey task. No per-monitor or per-region progress tracking — the cursor is the only
state needed.

```
SummaryBackfillJob (model)          backfill_summaries_tick (periodic task, every 15 min)
┌─────────────────────────┐         1. Claim the active job (locked, skip if none/locked)
│ cursor                  │◄────────2. chunk_start = max(cursor - 7 days, range_start)
│ range_start, range_end  │         3. Compute hourly + daily monitor summaries for chunk
│ state                   │         4. Compute hourly + daily region summaries for chunk
│ locked_at               │         5. For each day boundary crossed, cascade rollups
│ consecutive_failures    │            (monthly → quarterly/seasonal/yearly as applicable)
│ last_error              │         6. cursor = chunk_start; save
└─────────────────────────┘         7. On failure: leave cursor unchanged, record error
```

### Why a single synchronous tick, not fanned-out sub-tasks

Each tick does the actual computation as direct, synchronous ORM writes — it does
**not** enqueue further Huey tasks. This is the key property the rest of the design
leans on:

- **No Redis flooding**: there is exactly one task in flight for the entire
  multi-year backfill at any moment (the next scheduled tick), regardless of how
  much range remains.
- **No duplicate-range risk**: the job's `cursor` is the single source of truth.
  There's no scenario of "tasks already queued for a range we're about to
  reprocess," because nothing is ever queued ahead of time — a chunk is either
  fully computed and committed within one tick, or nothing happened and the next
  tick retries the same chunk.
- **Monitor-before-region ordering falls out for free**: within one tick, monitor
  hourly/daily summaries are computed and committed *before* region summaries are
  computed for that same window (region summaries read from `MonitorSummary`
  rows). No cross-task timing or staggering is needed, because it's sequential
  Python in a single function call, not two independent queued tasks racing each
  other.

## Chunking

Fixed 7-day steps, walking backward, day-aligned (`range_start`/`range_end` are
always midnight-aligned dates):

```
chunk_start = max(cursor - timedelta(days=7), range_start)
```

No clamping to month boundaries — chunks are always exactly 7 days (except the
final, possibly shorter, chunk against `range_start`).

## Rollup cascade (boundary-crossing detection)

Within a chunk `[chunk_start, cursor)`, loop over each of its (≤7) days `D`:

1. **Daily**: every day in the chunk just became fully covered → roll it up.
2. **Monthly**: if `D.day == 1`, the month `[D, D+1month)` just became fully
   covered. Because the walk is strictly backward with no gaps, every day in that
   month *after* D chronologically was necessarily already processed in an earlier
   (more-recent) tick — so reaching D confirms the whole month is done. Roll it up.
3. **Quarterly**: if the month rolled up in step 2 has `D.month in (1, 4, 7, 10)`,
   the quarter `[D, D+3months)` is also now fully covered (its other two months,
   being chronologically later, were already completed in earlier ticks). Roll it up.
4. **Seasonal**: same check with `D.month in (12, 3, 6, 9)` (meteorological
   seasons — same convention as the existing `season_start_months` in
   `tasks.py`). Roll it up.
5. **Yearly**: if `D.month == 1`, the year is fully covered. Roll it up.

This reuses the existing `rollup_monitor_summaries` / `rollup_region_summaries`
functions in `camp/apps/summaries/tasks.py` unchanged — only the *triggering*
logic is new. A worked example (walking back through 2023) confirmed this fires
monthly, quarterly, seasonal, and yearly rollups automatically with no separate
phase or manual step.

## Concurrency & failure handling

`SummaryBackfillJob` fields:

| Field                 | Purpose                                                        |
|------------------------|------------------------------------------------------------------|
| `sqid`                 | External identifier (project convention)                        |
| `state`                | `running` / `paused` / `done` / `failed`                        |
| `cursor`               | Next unprocessed boundary (walks backward)                      |
| `range_start`          | Target earliest bound (e.g. 2020-01-01)                         |
| `range_end`            | Fixed starting point (e.g. start of current month)               |
| `locked_at`            | Heartbeat set while a tick is actively processing this job       |
| `consecutive_failures` | Reset to 0 on success; increments on exception                   |
| `last_error`           | Most recent exception message, for visibility without log-diving |
| `created`, `updated`   | Standard timestamps                                              |

Each tick claims the job under `select_for_update(skip_locked=True)`, filtered to
`state='running'` and (`locked_at` is null or older than a staleness threshold —
30 minutes, comfortably longer than the expected few-minutes-per-chunk runtime and
the 15-minute tick interval, so it only kicks in for a genuinely stalled/crashed
tick). The lock is set in a short transaction, then released before the actual
computation runs — a multi-minute-long chunk never holds a Postgres row lock open
for its full duration.

Because all summary writes are idempotent upserts (`update_conflicts=True`,
already used throughout `tasks.py`), a chunk retried after a crash — or, in the
rare case a stale lock is reclaimed while the original tick is still finishing —
just recomputes the same numbers. Wasted duplicate work, not a correctness issue.

On exception: `consecutive_failures` increments, `last_error` is recorded, cursor
is **not** advanced (so the same chunk retries next tick). After 5 consecutive
failures, `state` flips to `failed` so it stops retrying silently forever and
becomes visible in admin instead of spinning indefinitely.

The final write-back (advancing `cursor`, clearing the lock, and setting `state`
on completion) uses a conditional update — `SummaryBackfillJob.objects.filter(pk=job.pk,
state='running').update(...)` — rather than an unconditional `job.save()`. This
matters because a chunk can take a few minutes to compute; if an operator runs
`backfill_summaries cancel` (or pauses the job in admin) while a tick is mid-chunk,
the tick must not clobber that state change back to `running` when it finishes.
The conditional update means the write silently no-ops if the job was
cancelled/paused out from under it.

## Code reuse

Extract the current private `_backfill_monitor_summaries` / `_backfill_region_summaries`
methods out of `rebuild_summaries.py` into shared functions in a new
`camp/apps/summaries/backfill.py`, so both the management command's synchronous
mode and the new periodic task call the same logic instead of duplicating it.
`rebuild_summaries.py` is updated to delegate to these functions.

## Management command

`camp/apps/summaries/management/commands/backfill_summaries.py`:

- `manage.py backfill_summaries start --from 2020-01-01 [--to YYYY-MM-DD]`
  Creates the job (`range_start`, `range_end` defaulting to start of current
  month, `cursor = range_end`). Refuses to create a second job while one is
  already `running`/`paused` unless `--force` is passed, in which case the
  existing job row is deleted and replaced with a fresh one at the new
  `--from`/`--to` bounds (this does **not** attempt to merge or preserve
  progress from the old job).
- `manage.py backfill_summaries status`
  Prints state, cursor, % of range complete, `last_error` if any.
- `manage.py backfill_summaries cancel`
  Sets the active job's `state` to `done` so `backfill_summaries_tick` stops
  picking it up.

## Admin

Register `SummaryBackfillJob` in `camp/apps/summaries/admin.py` with a list
view showing state, cursor, range bounds, `updated`, and `consecutive_failures`.
Pausing/resuming is just switching `state` in the admin form — no custom actions
needed.

## Task registration

`backfill_summaries_tick` — `db_periodic_task(crontab(minute='*/15'), priority=1,
queue='summaries')`. Lowest priority in the existing summaries-queue priority
scheme (100 → 5) so it never preempts live real-time summary work.

## Out of scope

- Per-monitor / per-region progress tracking or partial-scope backfill jobs
  (the existing synchronous `rebuild_summaries --monitor`/`--region` flags
  already cover targeted recalculation; this system is for the full-history case).
- Multiple concurrent backfill jobs.
- Configurable chunk size/tick interval via settings — hardcoded to 7 days / 15
  minutes based on production's measured "a few minutes per week" runtime; can
  be revisited if that estimate proves wrong in practice.
