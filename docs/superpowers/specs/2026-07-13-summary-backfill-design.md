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

A single DB-tracked job with one backward-walking cursor. Each chunk is processed
by fanning out one task per monitor (then, once those finish, one task per region)
so the work is actually distributed across the summaries queue's workers —  but
the periodic orchestrator that drives this **never blocks waiting on those
tasks**. It only ever checks a completion counter and returns immediately,
whether the batch is still in flight or ready to advance. This avoids the
deadlock risk of a task that occupies a worker slot while blocking on other
tasks that need worker slots to run.

```
SummaryBackfillJob                    backfill_summaries_tick (periodic, every 1 min)
┌───────────────────────┐             Claim the job (locked, skip if none/locked).
│ cursor                │             Branch on job.phase:
│ range_start/range_end │
│ state                 │             IDLE    → start next chunk: fan out one task
│ phase                 │◄──────────            per monitor, phase = MONITORS
│ pending_tasks         │             MONITORS → pending_tasks > 0? do nothing.
│ batch_id              │                        == 0? fan out one task per region,
│ phase_started_at      │                        phase = REGIONS
│ locked_at             │             REGIONS  → pending_tasks > 0? do nothing.
│ consecutive_failures  │                        == 0? run rollup cascade inline
│ last_error            │                        (fast, no fan-out needed), advance
└───────────────────────┘                        cursor, phase = IDLE
```

### Why fan out, but never wait inline

- **Distributed across workers**: a chunk's ~hundreds of monitors (or regions)
  are processed as independent tasks the whole worker pool can pick up in
  parallel, instead of one worker serially grinding through all of them.
- **No blocking task ever holds a worker slot hostage**: `backfill_summaries_tick`
  does a cheap DB check and returns — it is never "the task waiting for other
  tasks." If it *did* block, and the worker pool is small (2 by default on the
  `summaries` queue), you could end up with every worker stuck waiting on
  sub-tasks that have nowhere to run — a real deadlock. Because the orchestrator
  polls via a periodic tick instead, that scenario is structurally impossible.
- **"Is a batch already running?" is answered by `phase` + `pending_tasks`**,
  not by inspecting the queue. If `phase != IDLE` and `pending_tasks > 0`, the
  tick does nothing — it will not fan out a second batch on top of one still in
  flight, which is exactly the pile-up the phase field exists to prevent.
- **No Redis flooding**: a batch is bounded to roughly one task per monitor (or
  region) — hundreds, not hundreds of thousands — and the next batch isn't
  dispatched until the current one fully drains.
- **Monitor-before-region ordering is enforced by the phase gate**: the REGIONS
  batch is only dispatched after `pending_tasks` for the MONITORS batch reaches
  zero, guaranteeing every monitor summary for the chunk is committed before any
  region summary (which reads `MonitorSummary` rows) is computed.

## Chunking

Fixed 7-day steps, walking backward, day-aligned (`range_start`/`range_end` are
always midnight-aligned dates):

```
chunk_start = max(cursor - timedelta(days=7), range_start)
```

No clamping to month boundaries — chunks are always exactly 7 days (except the
final, possibly shorter, chunk against `range_start`).

## Rollup cascade (boundary-crossing detection)

This runs inline in the orchestrator, once `phase == REGIONS` and `pending_tasks`
reaches 0 — not fanned out. Rollup queries aggregate already-computed summary rows
(one query per window per level), which is cheap regardless of monitor/region
count, so there's no parallelism to gain by distributing it.

Within a chunk `[chunk_start, cursor)`, process in **two passes** over its (≤7)
days — this ordering is load-bearing, not stylistic (see the note below):

**Pass 1 — daily, every day in the chunk:** each day just became fully
covered → roll it up.

**Pass 2 — higher rollups, for each day `D`, after all of pass 1 has run:**

1. **Monthly**: if `D.day == 1`, the month `[D, D+1month)` just became fully
   covered. Because the walk is strictly backward with no gaps, every day in that
   month *after* D chronologically was already processed — either in an earlier
   (more-recent) tick, or, if it falls later in *this same* chunk, in pass 1
   above — so reaching D confirms the whole month is done. Roll it up.
2. **Quarterly**: if the month rolled up in step 1 has `D.month in (1, 4, 7, 10)`,
   the quarter `[D, D+3months)` is also now fully covered (its other two months,
   being chronologically later, were already completed in earlier ticks). Roll it up.
3. **Seasonal**: same check with `D.month in (12, 3, 6, 9)` (meteorological
   seasons — same convention as the existing `season_start_months` in
   `tasks.py`). Roll it up.
4. **Yearly**: if `D.month == 1`, the year is fully covered. Roll it up.

**Why two passes, not one combined loop per day:** chunks are fixed 7-day
windows, deliberately *not* aligned to month boundaries, so a month's 1st
very often falls in the *middle* of a chunk rather than at its edge. A
single ascending loop that rolled up a day and then immediately cascaded its
higher rollups would fire a month's MONTHLY rollup before later days *in the
same chunk* — still to come in that same loop — had been written, permanently
undercounting the month (and everything cascaded from it), since `D.day == 1`
only fires once and is never revisited. Doing all of pass 1 before any of
pass 2 restores the invariant that every day contributing to a higher rollup
window has already been written, regardless of whether it was processed in
an earlier chunk or earlier in this same one.

This reuses the existing `rollup_monitor_summaries` / `rollup_region_summaries`
functions in `camp/apps/summaries/tasks.py` unchanged — only the *triggering*
logic is new. A worked example (walking back through 2023) confirmed this fires
monthly, quarterly, seasonal, and yearly rollups automatically with no separate
phase or manual step.

## Concurrency & failure handling

`SummaryBackfillJob` fields:

| Field                 | Purpose                                                                 |
|------------------------|--------------------------------------------------------------------------|
| `sqid`                 | External identifier (project convention)                                |
| `state`                | `running` / `paused` / `done` / `failed`                                |
| `phase`                | `idle` / `monitors` / `regions` — which batch (if any) is in flight     |
| `cursor`               | **Confirmed** boundary of already-processed range — only moves when a chunk fully completes |
| `chunk_start`          | **Target** lower bound of the chunk currently in flight (set once, when leaving `idle`; unchanged until the chunk completes) |
| `range_start`          | Target earliest bound (e.g. 2020-01-01)                                 |
| `range_end`            | Fixed starting point (e.g. start of current month)                      |
| `pending_tasks`        | Count of outstanding sub-tasks for the current phase's batch             |
| `batch_id`             | Fencing token, incremented every time a batch is (re)dispatched          |
| `phase_started_at`     | When the current phase's batch was dispatched (staleness detection)      |
| `locked_at`            | Heartbeat held only for the brief claim/dispatch transaction             |
| `consecutive_failures` | Reset to 0 on success; increments on exception or forced batch restart   |
| `last_error`           | Most recent exception message, for visibility without log-diving        |
| `created`, `updated`   | Standard timestamps                                                      |

### Tracking position in the timeline

`cursor` and `chunk_start` are both persisted DB fields, not in-memory state, and
they answer different questions:

- `cursor` — "how far back is fully done?" Only ever updated in one place: the
  `regions` → `idle` transition, after rollups for the chunk have run.
- `chunk_start` — "where is the batch currently in flight heading?" Set once
  when a chunk starts (`idle` → `monitors`) and left untouched for the rest of
  that chunk's lifetime, including across the `monitors` → `regions` handoff.

Because both live on the row, a tick never needs to reconstruct "where was I" —
it just reads `phase`, `cursor`, and `chunk_start` off the job. This is also what
makes the staleness-restart path (below) correct: it re-dispatches using the
*same* `[chunk_start, cursor)` window already recorded, not a freshly recomputed
one, so a restart can never accidentally drift the range being processed.

### Claiming the job

Each tick claims the job under `select_for_update(skip_locked=True)`, filtered
to `state='running'`, with `locked_at` null or older than a small threshold
(e.g. 30 seconds — comfortably longer than a tick's own dispatch-or-check
duration, comfortably shorter than the 1-minute tick interval). The lock is
released as soon as the tick's own DB work commits.

### Dispatching a batch safely

Enqueueing ~hundreds of Huey tasks must not race with the DB transaction that
records the batch. The claim-and-transition step commits first; the actual
`.delay()` calls happen via `transaction.on_commit()`, so a task is never
enqueued referencing a `batch_id`/`phase` that didn't actually commit:

```
with transaction.atomic():
    job = (SummaryBackfillJob.objects
        .select_for_update(skip_locked=True)
        .filter(state='running', ...))
        .first()
    if job is None:
        return
    if job.phase == 'idle':
        combos = <monitor ids with data in [chunk_start, job.cursor)>
        job.chunk_start = chunk_start
        job.batch_id += 1
        job.pending_tasks = len(combos)
        job.phase = 'monitors'
        job.phase_started_at = timezone.now()
        job.save()
        for monitor_id in combos:
            transaction.on_commit(
                lambda m=monitor_id, b=job.batch_id: backfill_monitor_chunk(
                    job.id, m, job.chunk_start, job.cursor, b))
    elif job.phase == 'monitors' and job.pending_tasks == 0:
        # mirror image: dispatch one backfill_region_chunk per region,
        # phase = 'regions', same on_commit pattern
        ...
    elif job.phase == 'regions' and job.pending_tasks == 0:
        # run the rollup cascade inline, then:
        job.cursor = job.chunk_start
        job.phase = 'idle'
        job.consecutive_failures = 0
        job.last_error = ''
        if job.cursor <= job.range_start:
            job.state = 'done'
        job.save()
```

`combos` is filtered to monitors (or, in the regions branch, regions) with at
least one entry actually falling in `[chunk_start, job.cursor)` — an `EXISTS`
subquery, not the full unfiltered monitor/region table — so retired or
data-sparse monitors don't spawn pointless no-op tasks every chunk.

Each sub-task (`backfill_monitor_chunk` / `backfill_region_chunk`) computes its
summaries and, in the same atomic block, does a **fenced** decrement:

```
SummaryBackfillJob.objects.filter(
    pk=job_id, batch_id=batch_id, phase='monitors',
).update(pending_tasks=F('pending_tasks') - 1)
```

The `batch_id` match is what makes this safe against a batch being restarted
(below) while a straggler from the old batch is still running: a late/duplicate
completion from a stale batch simply matches no rows and is a no-op, instead of
corrupting the new batch's counter.

### Recovering from a stalled or partially-dispatched batch

If a tick finds `phase != 'idle'` and `pending_tasks > 0`, but `phase_started_at`
is older than a stale threshold (30 minutes — generous relative to the
few-minutes-per-chunk runtime expected even serially, let alone parallelized
across workers), it treats the batch as stalled — whether from crashed workers,
a task never actually getting enqueued (e.g. a process died between the commit
above and finishing its `on_commit` callbacks), or anything else — and restarts
it: bump `batch_id` again, recompute the combo list, reset `pending_tasks`, and
re-dispatch. This is safe because summary writes are idempotent upserts
(`update_conflicts=True`, already used throughout `tasks.py`); any combos that
did complete under the old `batch_id` just get recomputed to the same values.
Each restart increments `consecutive_failures`; after 5, `state` flips to
`failed` so a genuinely poisoned chunk (e.g. one monitor's task always crashing)
doesn't loop forever silently — it becomes visible in admin instead.

### Cancellation mid-batch

`backfill_summaries cancel` (or pausing via admin) sets `state`. Because
sub-tasks' fenced updates only ever touch `pending_tasks` — never `state` — a
cancel takes effect immediately: the orchestrator simply stops claiming the job
on its next tick (the `state='running'` filter excludes it), regardless of
whether a batch is still draining in the background. Any in-flight sub-tasks
finish harmlessly; their decrements just update a job nobody is watching anymore.

## Code reuse

The current private `_backfill_monitor_summaries` / `_backfill_region_summaries`
methods in `rebuild_summaries.py` compute a whole monitor/region set at once; the
backfill job needs the same aggregation logic scoped to a *single* monitor or
region (since that's now the unit of fan-out). Extract the per-item computation
into shared functions in a new `camp/apps/summaries/backfill.py` —
`backfill_monitor_hours(monitor, hours, entry_models)` and
`backfill_region_hours(region, hours, monitor_grades)` — and have both
`rebuild_summaries.py`'s existing loop and the new `backfill_monitor_chunk` /
`backfill_region_chunk` tasks call them per-item, instead of duplicating the
aggregation logic in three places.

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

All on the `summaries` queue, at the lowest priority in the existing scheme
(100 → 5) so backfill work never preempts live real-time summaries:

- `backfill_summaries_tick` — `db_periodic_task(crontab(minute='*'), priority=1,
  queue='summaries')`. The non-blocking orchestrator described above.
- `backfill_monitor_chunk(job_id, monitor_id, chunk_start, chunk_end, batch_id)` —
  `db_task(priority=1, queue='summaries')`. Computes hourly + daily
  `MonitorSummary` rows for one monitor over the chunk, then does the fenced
  `pending_tasks` decrement.
- `backfill_region_chunk(job_id, region_id, chunk_start, chunk_end, batch_id)` —
  `db_task(priority=1, queue='summaries')`. Same, for one region's
  `RegionSummary` rows.

Note for deployment: since these run at the same priority as each other but
still share the `summaries` queue's worker pool with the live real-time tasks
(which run at priority 5–100), a large `pending_tasks` batch will queue behind
any live work already scheduled, but Huey's `PriorityRedisHuey` ensures live
tasks always jump ahead of backfill tasks when both are pending — backfill
throughput is whatever's left over. Bumping `HUEY_SUMMARIES_WORKERS` during the
backfill window is an operational lever if it's running too slowly, not a code
change.

## Out of scope

- Per-monitor / per-region progress tracking or partial-scope backfill jobs
  (the existing synchronous `rebuild_summaries --monitor`/`--region` flags
  already cover targeted recalculation; this system is for the full-history case).
- Multiple concurrent backfill jobs.
- Configurable chunk size/tick interval via settings — hardcoded to 7 days /
  1-minute orchestrator ticks / 30-minute stall threshold; can be revisited if
  those estimates prove wrong in practice.
- Per-sub-task retry/backoff policy beyond Huey's defaults — a failed monitor or
  region task just leaves `pending_tasks` non-zero until the batch-level
  staleness recovery (above) restarts the whole batch.
