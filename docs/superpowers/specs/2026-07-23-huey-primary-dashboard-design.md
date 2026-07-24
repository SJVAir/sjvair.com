# Huey primary-queue admin dashboard — design

**Date:** 2026-07-23
**Status:** Approved, ready for implementation planning

## Goal

Add a single Django-admin page that shows live task statistics for the
**primary** `django_huey` queue — live queue depths (pending/scheduled/results),
running tasks, a throughput chart, per-task timing/error rates, a recent-event
log, and flush/revoke controls — using huey's built-in
`huey.contrib.djhuey.stats` app, without disturbing the existing multi-queue
`DJANGO_HUEY` configuration or the `djangohuey` consumer model.

Only the **primary** queue is in scope. The secondary queue is low-traffic and
the summaries queue is monitored by other means; both are explicitly out of
scope here.

## Background / constraints

- The project runs multiple queues via **`django-huey`** (`DJANGO_HUEY` setting +
  `manage.py djangohuey --queue <name>`), which builds three independent Huey
  instances: `primary`, `secondary`, `summaries`. `settings.HUEY` is **not** set.
- huey's built-in dashboard (`huey.contrib.djhuey.stats`, added in huey **3.2.1**)
  is wired to the single-instance `huey.contrib.djhuey` integration. Its admin
  resolves the queue through a module-level function
  `huey.contrib.djhuey.stats.admin.get_huey()`, which returns
  `huey.contrib.djhuey.HUEY` (the `settings.HUEY` instance). It is used in
  exactly two methods: `HueyDashboardAdmin._context()` and `.action_view()`.
- The underlying engine (`huey.contrib.stats`) is per-instance and queue-tagged:
  `enable_stats(huey, db)` attaches a recorder to one Huey instance (idempotent
  per instance, stashes the recorder on `huey._stats`), and events are written to
  peewee tables `huey_event` / `huey_inflight` with an indexed `queue` column.
  `live_counts(huey)` and `dashboard_context(huey, stats, ...)` both take the
  instance as an argument — nothing is a hard singleton at the data layer.
- The currently installed huey is **3.0.1**, which predates the dashboard.

### Why not simply set `settings.HUEY` to mirror primary

Recording happens on the instance whose consumer executes the task — i.e.
`django_huey`'s primary instance (run by `djangohuey --queue primary`). If
`settings.HUEY` were a separate instance mirroring primary's storage, the
dashboard's `_stats` lookup and the recorder would sit on **different objects**:
live counts would work (same Redis) but the throughput/per-task panels would be
empty because no recorder receives the consumer's signals. The recorder and the
dashboard must therefore point at the **same object** the consumer uses:
`get_queue('primary')`.

## Decisions

- **Upgrade huey `3.0.1 → 3.3.0`** (current latest; the dashboard requires ≥ 3.2.1).
- **Point the dashboard at primary by monkeypatching** `get_huey` rather than
  subclassing/re-registering the admin. Both admin methods reference the
  module-level `get_huey`, so reassigning that one attribute covers the whole
  dashboard, and we avoid copying ~40 lines of huey-internal method bodies that
  would need to be kept in sync across upgrades.

## Changes

### 1. Dependency

Bump `huey` from `3.0.1` to `3.3.0` in the requirements file.

### 2. `INSTALLED_APPS` (base.py)

Add `huey.contrib.djhuey.stats` (alongside the existing
`huey.contrib.djhuey`). This provides:

- the admin registrations (`HueyEventAdmin`, `HueyDashboardAdmin`),
- the `managed=False` Django models mapping to the `huey_event` /
  `huey_inflight` tables (so the **Events** changelist reads them through the
  ORM), and
- the dashboard templates.

The app's own `ready()` calls `enable_stats(djhuey.HUEY, db)` on the (unused,
default) `djhuey.HUEY` instance. This is harmless — that instance never runs
tasks — and has the useful side effect of creating the peewee tables. No Django
migration is required (peewee issues `create table if not exists`).

### 3. New app: `camp.apps.taskstats`

A minimal app whose only job is an `AppConfig.ready()` hook (the glue cannot live
inside the third-party package). Structure: `apps.py`, `__init__.py`, `tests.py`.
Add `camp.apps.taskstats` to `INSTALLED_APPS`.

The wiring logic lives in a small, testable function — e.g.
`configure_primary_stats(queue=None, db=None)`, where both arguments default to
the production values (`get_queue('primary')` and `stats_database()`) but can be
injected in tests. Called from `ready()` with no arguments:

1. Resolve the primary instance: `queue = queue or get_queue('primary')` (via
   `django_huey.get_queue`).
2. **Guard:** if `queue.immediate` is true, return immediately — there is no
   consumer, so a live dashboard is meaningless (covers tests and local DEBUG).
3. Obtain the stats DB if not injected: `db, options = stats_database()` from
   `huey.contrib.djhuey.stats.apps`.
4. `enable_stats(queue, db, **options)` — attaches the recorder to the primary
   instance (idempotent), so execution signals are recorded and `queue._stats`
   is populated.
5. Monkeypatch: `huey.contrib.djhuey.stats.admin.get_huey = lambda: queue` — the
   Dashboard page's live counts, charts, per-task stats, and flush/revoke
   controls now all target primary.

Note the guard means `ready()` is a no-op in the normal test run; the function
is exercised directly with injected arguments (see Testing).

`ready()` runs in every process that loads the Django app registry — including
the `djangohuey` consumers (management commands load apps first) and the web
server — so the recorder is attached wherever tasks execute, and the monkeypatch
is applied wherever the admin is served.

### 4. `HUEY_STATS` setting (base.py)

```python
HUEY_STATS = {
    'capture_args': False,   # do not persist task arguments
    # retention_hours / max_events left at defaults; stored in DATABASES['default']
}
```

### 5. Keep the test suite clean (test.py)

`test.py` inherits `INSTALLED_APPS` from base via `from .base import *`. Remove
`huey.contrib.djhuey.stats` from the inherited list in `test.py` so the
third-party app's `ready()` never connects to or creates tables in the test
database. Our own `camp.apps.taskstats.ready()` already no-ops under tests
because the test `DJANGO_HUEY` queues run `immediate=True`, but dropping the
vendor app removes the other path to the test DB as well.

## Out of scope (follow-ups)

- **"Registered tasks" list** in the dashboard will be sparse in the web
  process, because `django_huey` autodiscovers `tasks.py` modules only in the
  consumer. Populating it means importing the primary queue's task modules in
  `ready()`. Deferred; throughput/event data comes from the DB regardless.
- **secondary / summaries** queues — handled by other means.

## Testing

The wiring function is tested hermetically — it accepts injected `queue` and
`db` arguments, so the tests never depend on the third-party stats app being in
`INSTALLED_APPS` (it is removed in `test.py`) and never touch the default test
database.

- **Unit** (`camp/apps/taskstats/tests.py`): call `configure_primary_stats(...)`
  with a **non-immediate** `MemoryHuey` and an in-memory peewee
  `SqliteDatabase`, then assert (a) `queue._stats` is set after the call and
  (b) `huey.contrib.djhuey.stats.admin.get_huey()` returns that instance.
- **Immediate-mode guard:** call it with an `immediate=True` instance and assert
  `get_huey` is left unpatched and `queue._stats` is unset.

Each test restores `huey.contrib.djhuey.stats.admin.get_huey` to its original
value afterward so the monkeypatch does not leak across tests.

A rendered-dashboard check (staff `GET` → `200`) is **not** part of the
automated suite — the stats app is intentionally absent under tests. It is
covered instead by the manual verification step below.

Tests follow project conventions: inherit from Django's `TestCase`, use plain
`assert` statements, and use fixtures where needed.

## Ops / rollout notes

- **No Procfile change.** The recorder attaches in-process via `ready()`; the
  existing `djangohuey --queue primary` worker/scheduler pick it up automatically.
- **No Django migration.** The stats tables are created by peewee on first
  `enable_stats`.
- **Verify against a real consumer**, not just immediate-mode tests: run
  `djangohuey --queue primary`, enqueue a task, and confirm events land and the
  dashboard renders live data.

## Risks

- Relies on huey internals not covered by its public API: the
  `stats.admin.get_huey` attribute, `enable_stats`, `huey._stats`, and the
  dashboard template URL names. Pinned to huey 3.3.0. A rename on a future bump
  would fail loudly at `ready()` (AttributeError), which is easy to detect.
- The huey `3.0.1 → 3.3.0` bump is the largest change to validate; review the
  changelog for behavior affecting `PriorityRedisHuey` and run the full suite.
