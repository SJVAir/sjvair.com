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

Only the **primary** queue is wired in this cut. The secondary queue is
low-traffic and the summaries queue is monitored by other means; both are
explicitly out of scope here.

### Wider intent (why the shape matters)

This is deliberately built as **bridge #1** over a known structural gap: huey's
Django integration (`huey.contrib.djhuey`) is single-instance by design, so its
new dashboard doesn't compose with the multi-queue `django-huey` we depend on.
The longer-term aim is a queue-aware observability layer — a
`/admin/queues/<name>/` surface across all queues — that could eventually be
extracted as an add-on to **`django-huey`** (the incumbent multi-queue package),
not a fork of `djhuey` and not a change to huey core. See **Strategic context**
at the end. Concretely, that means: the code lives in a real app
(`camp.apps.queues`) shaped to mirror `djhuey.stats` for portability, and the
wiring is written **queue-parametrized** (takes a queue name; this cut passes
`'primary'`) rather than hardcoding `primary` throughout.

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
- **Point the dashboard at the target queue by monkeypatching** `get_huey`
  rather than subclassing/re-registering the admin. Both admin methods reference
  the module-level `get_huey`, so reassigning that one attribute covers the whole
  dashboard, and we avoid copying ~40 lines of huey-internal method bodies that
  would need to be kept in sync across upgrades.
- **House it in a new app `camp.apps.queues`**, structured to mirror
  `huey.contrib.djhuey.stats` (an `AppConfig.ready()` that calls `enable_stats`),
  so a later extraction into a `django-huey` add-on is close to a copy rather
  than a redesign. The stats/dashboard concern is kept in its own submodule so a
  future `django.tasks` multi-queue backend can live beside it as a separate,
  independently-extractable module.
- **Scope note on the monkeypatch:** it points the *one* shipped dashboard at
  *one* queue. It is correct for this single-page cut but is **not** the
  mechanism for the eventual multi-page `/admin/queues/<name>/` surface — that
  needs queue-aware views (see Out of scope), because three monkeypatches would
  fight over the single `get_huey` and the shipped templates' global URL names.

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

### 3. New app: `camp.apps.queues`

A small app whose job (for now) is an `AppConfig.ready()` hook that wires the
dashboard to a queue — the glue cannot live inside the third-party package. Add
`camp.apps.queues` to `INSTALLED_APPS`. Layout, shaped to mirror
`djhuey.stats` and to keep concerns separable:

```
camp/apps/queues/
    __init__.py
    apps.py        # QueuesConfig.ready() -> configure_queue_stats('primary')
    stats.py       # configure_queue_stats(...) — the dashboard bridge
    tests.py
    # (future) tasks_backend.py — multi-queue django.tasks backend
```

The wiring lives in a small, testable, **queue-parametrized** function in
`stats.py` — e.g. `configure_queue_stats(queue_name, queue=None, db=None)`.
`queue`/`db` default to the production values but can be injected in tests.
`ready()` calls `configure_queue_stats('primary')`. Steps:

1. Resolve the instance: `queue = queue or get_queue(queue_name)` (via
   `django_huey.get_queue`).
2. **Guard:** if `queue.immediate` is true, return immediately — there is no
   consumer, so a live dashboard is meaningless (covers tests and local DEBUG).
3. Obtain the stats DB if not injected: `db, options = stats_database()` from
   `huey.contrib.djhuey.stats.apps`.
4. `enable_stats(queue, db, **options)` — attaches the recorder to that instance
   (idempotent), so execution signals are recorded and `queue._stats` is
   populated.
5. Monkeypatch: `huey.contrib.djhuey.stats.admin.get_huey = lambda: queue` — the
   Dashboard page's live counts, charts, per-task stats, and flush/revoke
   controls now all target that queue.

Note the guard means `ready()` is a no-op in the normal test run; the function
is exercised directly with injected arguments (see Testing).

`ready()` runs in every process that loads the Django app registry — including
the `djangohuey` consumers (management commands load apps first) and the web
server — so the recorder is attached wherever tasks execute, and the monkeypatch
is applied wherever the admin is served.

The function is queue-parametrized so the eventual multi-queue work reuses it to
register recorders per queue; the single shipped admin still shows one queue via
the monkeypatch (that's this cut), and the multi-page surface is a later,
separate step (Out of scope).

### 4. `HUEY_STATS` setting (base.py)

```python
HUEY_STATS = {
    'capture_args': False,   # do not persist task arguments
    # retention_hours / max_events left at defaults; stored in DATABASES['default']
}
```

### 5. Keep the test suite clean (test.py)

The stats app **stays installed** under tests — its models are Django models, so
`configure_queue_stats` importing `huey.contrib.djhuey.stats.admin` (to patch
`get_huey`) requires the app in `INSTALLED_APPS`, otherwise it raises
`RuntimeError: Model ... doesn't declare an explicit app_label`. Removing the app
would make the wiring function un-importable and therefore un-testable.

Instead, keep the test Postgres untouched by pointing stats storage at throwaway
in-memory sqlite in `test.py`:

```python
HUEY_STATS = {'capture_args': False, 'database': 'sqlite:///:memory:'}
```

With this, the vendor app's own startup `enable_stats(djhuey.HUEY, db)` creates
its (empty) tables in an ephemeral sqlite db on a separate peewee connection,
never in the test Postgres. Our `camp.apps.queues.ready()` still no-ops under
tests because the test `DJANGO_HUEY` queues run `immediate=True`. The stats
models are `managed=False`, so Django's test-DB setup never creates them either.
The unit test injects its *own* in-memory sqlite db into `configure_queue_stats`,
so it depends on none of this.

## Out of scope (follow-ups)

- **Multi-queue dashboard** (`/admin/queues/<name>/`). This cut points the one
  shipped admin at `primary` via the monkeypatch. Covering all queues means:
  (a) register recorders on every queue (`configure_queue_stats(name)` per queue,
  into the one shared stats DB — events are already `queue`-tagged), and
  (b) build **queue-aware views** on huey's public `live_counts()` /
  `dashboard_context()` / `HueyStats` helpers. It does **not** mean calling the
  wiring three times against the shipped admin — that would collide on the single
  `get_huey` and the shipped templates' global URL names. This is the seed of the
  extractable `django-huey` add-on.
- **`django.tasks` multi-queue backend** — a `HueyBackend` variant routing
  `queue_name → get_queue(name)`; the main design problem is namespacing result
  ids per queue. Separate module (`tasks_backend.py`), separate effort.
- **"Registered tasks" list** in the dashboard will be sparse in the web
  process, because `django_huey` autodiscovers `tasks.py` modules only in the
  consumer. Populating it means importing the primary queue's task modules in
  `ready()`. Deferred; throughput/event data comes from the DB regardless.
- **secondary / summaries** queues — handled by other means.

## Testing

The wiring function is tested hermetically — it accepts injected `queue` and
`db` arguments, so the tests never touch the default test database (they use an
in-memory sqlite peewee db) and don't rely on the vendor app's own startup
recorder.

- **Unit** (`camp/apps/queues/tests.py`): call `configure_queue_stats(...)`
  with a **non-immediate** `MemoryHuey` and an in-memory peewee
  `SqliteDatabase`, then assert (a) `queue._stats` is set after the call and
  (b) `huey.contrib.djhuey.stats.admin.get_huey()` returns that instance.
- **Immediate-mode guard:** call it with an `immediate=True` instance and assert
  `get_huey` is left unpatched and `queue._stats` is unset.

Each test restores `huey.contrib.djhuey.stats.admin.get_huey` to its original
value afterward so the monkeypatch does not leak across tests.

A rendered-dashboard check (staff `GET` → `200`) is **not** part of the
automated suite — under tests the queues run `immediate=True`, so `get_huey` is
never patched to a real instance and the live panel has nothing meaningful to
render. It is covered instead by the manual verification step below.

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

## Strategic context

Recorded so future work has the reasoning, not just the code.

- **Why this exists as a bridge.** huey's Django layer (`huey.contrib.djhuey`)
  is single-instance *by design*; the maintainer treats single-queue-in-Django
  as a deliberate choice (huey issue #838) and steers users toward one queue +
  priorities. We need multiple queues for genuine worker isolation (see the
  queue-topology note below), so we run `django-huey`, and every new huey
  Django-layer feature — this dashboard, later the `django.tasks` backend — has
  to be bridged by hand. This is **bridge #1**.

- **Queue topology is correct, keep it.** The three queues buy worker isolation,
  which task priorities cannot provide (priority is dequeue ordering, not
  capacity reservation or preemption). `primary` = latency-sensitive ingest +
  scheduler; `secondary` = on-demand heavy bulk imports that must never starve
  `primary`; `summaries` = long, memory-tuned rollups. huey's own docs list
  "isolation … must never starve critical tasks of workers" as the reason to use
  separate queues. Do **not** collapse queues to simplify monitoring — that is
  the tail wagging the dog.

- **Tripwire — when to reconsider the whole stack.** The migration trigger is not
  "we use `django-huey`." It is the **number of hand-built bridges** we maintain
  to keep `django-huey` composing with modern huey, and whether each huey upgrade
  threatens them. One or two (this dashboard, maybe a rate-limit helper): fine,
  stay. If we reach bridge #3–#4 and huey bumps become tense regression checks on
  our monkeypatches, we have structurally outgrown the arrangement — and at that
  point the principled move is **Celery** (native multi-queue routing) or
  **Dramatiq**, chosen for the *isolation/routing* need, not for ecosystem size.

- **Upstream posture (if we choose to give back).** Ranked: (1) build here first
  — the deliverable and the proving ground, no external commitment; (2) if giving
  back, contribute the two add-on modules (stats/dashboard + `django.tasks`
  backend) to **`django-huey`**, the incumbent — additive features to a
  maintained project, no ecosystem fragmentation; (3) a standalone package only
  as a fallback if `django-huey` won't take them. A **new unified djhuey/django-
  huey rewrite is explicitly rejected** — `django-huey` already covers multi-queue
  config, per-queue consumers, decorators, signals, and DB-connection handling;
  the only real gaps are those two modules. A separate, minimal upstream nicety
  worth floating to huey *issue-first* (not as a surprise PR, and with low
  expectations given #838): make `djhuey.stats`' instance resolution configurable
  (e.g. honor `HUEY_STATS['huey']`), which turns this cut's monkeypatch into a
  supported setting and helps single-queue users too.

## Risks

- Relies on huey internals not covered by its public API: the
  `stats.admin.get_huey` attribute, `enable_stats`, `huey._stats`, and the
  dashboard template URL names. Pinned to huey 3.3.0. A rename on a future bump
  would fail loudly at `ready()` (AttributeError), which is easy to detect.
- The huey `3.0.1 → 3.3.0` bump is the largest change to validate; review the
  changelog for behavior affecting `PriorityRedisHuey` and run the full suite.
