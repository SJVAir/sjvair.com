# Huey primary-queue admin dashboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a single Django-admin dashboard page showing live task stats for the `primary` `django_huey` queue, using huey's built-in `huey.contrib.djhuey.stats`, without disturbing the multi-queue setup.

**Architecture:** Upgrade huey to a version that ships the stats dashboard, install the vendor stats app (it provides the admin, models, and templates), then bridge it to our multi-queue world with a small app `camp.apps.queues`: its `AppConfig.ready()` attaches huey's per-instance stats recorder to the `primary` queue and monkeypatches the dashboard admin's `get_huey()` to return that instance, so the shipped dashboard renders `primary` instead of the unused default instance.

**Tech Stack:** Django, `django-huey` (multi-queue), huey `3.3.0` (`huey.contrib.djhuey.stats`, `huey.contrib.stats`), peewee `4.2.6` (stats storage), pytest / Django `TestCase`, Docker Compose.

## Global Constraints

- huey pinned to exactly `huey==3.3.0`; add `peewee==4.2.6` (undeclared soft dep of the stats contrib).
- Leave `django-huey==1.3.1` unchanged.
- Tests inherit Django's `TestCase` and use plain `assert` statements (not `self.assertX`); `pytest.raises` for exceptions.
- No AI-authorship attribution anywhere in commits or messages.
- Never `git add -A` — list files explicitly.
- Don't align `=` signs in field/dict definitions.
- Run tests via Docker: `docker compose run --rm test pytest <path> -v`. CI runs the bare full suite.
- New app follows the existing `camp.apps.*` AppConfig pattern (`name = 'camp.apps.queues'`, single `AppConfig` subclass in `apps.py`, auto-discovered).
- The monkeypatch relies on huey internals (`huey.contrib.djhuey.stats.admin.get_huey`, `huey.contrib.stats.enable_stats`, `huey._stats`); correct for pinned 3.3.0.

---

### Task 1: Upgrade huey to 3.3.0 and add peewee

**Files:**
- Modify: `requirements/base.txt:40` (the `huey==3.0.1` line) and add a `peewee` pin.

**Interfaces:**
- Produces (available to later tasks after this lands): the modules `huey.contrib.stats` (`enable_stats(huey, db, **kwargs)`), `huey.contrib.djhuey.stats` (Django app), `huey.contrib.djhuey.stats.apps.stats_database() -> (db, options)`, and `huey.contrib.djhuey.stats.admin.get_huey() -> Huey`.

- [ ] **Step 1: Edit the requirements pin**

In `requirements/base.txt`, change the huey line and add peewee immediately after it:

```
huey==3.3.0
peewee==4.2.6
```

(The original line 40 reads `huey==3.0.1`. `peewee` is not currently present — add it.)

- [ ] **Step 2: Rebuild the image so the new deps install**

Run: `docker compose build web test`
Expected: build succeeds; `huey==3.3.0` and `peewee==4.2.6` install.

- [ ] **Step 3: Verify the stats modules import and are compatible with peewee 4.x**

Run:
```bash
docker compose run --rm web python -c "
import huey, peewee
print('huey', huey.__version__, 'peewee', peewee.__version__)
from huey import MemoryHuey
from huey.contrib.stats import enable_stats
from huey.contrib.djhuey.stats.apps import stats_database
from huey.contrib.djhuey.stats import admin as a
h = MemoryHuey('compat-check', immediate=False)
s = enable_stats(h, peewee.SqliteDatabase(':memory:'))
print('enable_stats ok:', s is not None, 'has _stats:', getattr(h, '_stats', None) is not None)
print('get_huey present:', callable(a.get_huey))
"
```
Expected output includes: `huey 3.3.0 peewee 4.2.6`, `enable_stats ok: True has _stats: True`, `get_huey present: True`. This empirically confirms huey 3.3.0's stats code works with peewee 4.2.6.

- [ ] **Step 4: Run the full test suite to catch upgrade regressions**

Run: `docker compose run --rm test pytest`
Expected: PASS (same result as before the bump; the upgrade must not break existing tests). If failures appear, they are upgrade regressions — review the huey 3.0→3.3 changelog (esp. `PriorityRedisHuey` behavior) before proceeding.

- [ ] **Step 5: Commit**

```bash
git add requirements/base.txt
git commit -m "chore(deps): upgrade huey to 3.3.0, add peewee for stats dashboard"
```

---

### Task 2: Install the stats app and configure `HUEY_STATS`

**Files:**
- Modify: `camp/settings/base.py` (add `'huey.contrib.djhuey.stats'` to `INSTALLED_APPS` after `'huey.contrib.djhuey'` at line 88; add a `HUEY_STATS` setting after the `DJANGO_HUEY` block, which ends at line 362).
- Modify: `camp/settings/test.py` (add a `HUEY_STATS` override pointing stats storage at throwaway in-memory sqlite).

**Interfaces:**
- Consumes: the stats modules from Task 1.
- Produces: the vendor stats admin (a "Huey" section) is registered; `settings.HUEY_STATS` exists; under tests, stats storage is ephemeral sqlite (test Postgres untouched).

- [ ] **Step 1: Add the stats app to `INSTALLED_APPS` in `base.py`**

Find (line 88):
```python
    'huey.contrib.djhuey',
```
Replace with:
```python
    'huey.contrib.djhuey',
    'huey.contrib.djhuey.stats',
```

- [ ] **Step 2: Add the `HUEY_STATS` setting in `base.py`**

Find the end of the `DJANGO_HUEY` block followed by `MAX_QUEUE_SIZE` (around line 362-364):
```python
        },
    }
}

MAX_QUEUE_SIZE = int(env('MAX_QUEUE_SIZE', 500))
```
Replace with:
```python
        },
    }
}

HUEY_STATS = {
    'capture_args': False,
}

MAX_QUEUE_SIZE = int(env('MAX_QUEUE_SIZE', 500))
```

(The three-space-then-`}` closing lines belong to the innermost queue dict, the queues dict, and the `DJANGO_HUEY` dict respectively; match them exactly as they appear in the file.)

- [ ] **Step 3: Override `HUEY_STATS` in `test.py` to use ephemeral sqlite**

In `camp/settings/test.py`, after the `DJANGO_HUEY = { ... }` block, add:
```python
# Huey stats — keep the test Postgres untouched; the vendor stats app's
# startup recorder writes its (empty) tables to a throwaway sqlite db instead.
HUEY_STATS = {
    'capture_args': False,
    'database': 'sqlite:///:memory:',
}
```

- [ ] **Step 4: Verify settings load and the suite still passes**

Run: `docker compose run --rm test pytest`
Expected: PASS. (The vendor app's `ready()` now calls `enable_stats(djhuey.HUEY, <sqlite>)` at startup; because `HUEY_STATS['database']` is in-memory sqlite, no test-Postgres tables are created, and the test queues are `immediate=True` so nothing records.)

- [ ] **Step 5: Commit**

```bash
git add camp/settings/base.py camp/settings/test.py
git commit -m "feat(queues): install huey stats dashboard app, add HUEY_STATS config"
```

---

### Task 3: Create `camp.apps.queues` and wire the dashboard to the primary queue

**Files:**
- Create: `camp/apps/queues/__init__.py`
- Create: `camp/apps/queues/apps.py`
- Create: `camp/apps/queues/stats.py`
- Create: `camp/apps/queues/tests.py`
- Modify: `camp/settings/base.py` (add `'camp.apps.queues'` to the `camp.apps.*` block in `INSTALLED_APPS`).

**Interfaces:**
- Consumes: `django_huey.get_queue(name) -> Huey`; `huey.contrib.stats.enable_stats(huey, db, **options)`; `huey.contrib.djhuey.stats.apps.stats_database() -> (db, options)`; `huey.contrib.djhuey.stats.admin.get_huey` (module attribute to reassign).
- Produces: `camp.apps.queues.stats.configure_queue_stats(queue_name, queue=None, db=None) -> Huey | None` — attaches the recorder to the resolved queue and points the dashboard admin at it; returns the instance, or `None` when the queue is in immediate mode.

- [ ] **Step 1: Create the package and empty `__init__.py`**

Create `camp/apps/queues/__init__.py` (empty file).

- [ ] **Step 2: Write the failing tests**

Create `camp/apps/queues/tests.py`:
```python
import peewee
from django.test import TestCase
from huey import MemoryHuey
from huey.contrib.djhuey.stats import admin as stats_admin

from camp.apps.queues.stats import configure_queue_stats


class ConfigureQueueStatsTests(TestCase):
    def setUp(self):
        # Restore the dashboard's queue resolver after each test so the
        # monkeypatch never leaks between tests.
        original = stats_admin.get_huey
        self.original_get_huey = original
        self.addCleanup(setattr, stats_admin, 'get_huey', original)

    def test_wires_recorder_and_dashboard_for_live_queue(self):
        queue = MemoryHuey('test-live', immediate=False)
        db = peewee.SqliteDatabase(':memory:')

        result = configure_queue_stats('ignored', queue=queue, db=db)

        assert result is queue
        assert getattr(queue, '_stats', None) is not None
        assert stats_admin.get_huey() is queue

    def test_noop_when_queue_is_immediate(self):
        queue = MemoryHuey('test-immediate', immediate=True)
        db = peewee.SqliteDatabase(':memory:')

        result = configure_queue_stats('ignored', queue=queue, db=db)

        assert result is None
        assert getattr(queue, '_stats', None) is None
        assert stats_admin.get_huey is self.original_get_huey
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/queues/tests.py -v`
Expected: FAIL with `ModuleNotFoundError` / `ImportError` for `camp.apps.queues.stats` (it doesn't exist yet).

- [ ] **Step 4: Implement `configure_queue_stats`**

Create `camp/apps/queues/stats.py`:
```python
def configure_queue_stats(queue_name, queue=None, db=None):
    """Attach huey's stats recorder to a django-huey queue and point the
    built-in dashboard admin at that same instance.

    Idempotent per huey instance (``enable_stats`` no-ops if already attached).
    Returns the wired queue, or ``None`` when the queue runs in immediate mode
    (tests / local DEBUG), where there is no consumer to monitor.
    """
    from django_huey import get_queue
    from huey.contrib.stats import enable_stats
    from huey.contrib.djhuey.stats import admin as stats_admin
    from huey.contrib.djhuey.stats.apps import stats_database

    if queue is None:
        queue = get_queue(queue_name)

    if queue.immediate:
        return None

    if db is None:
        db, options = stats_database()
    else:
        options = {}

    enable_stats(queue, db, **options)
    stats_admin.get_huey = lambda: queue
    return queue
```

- [ ] **Step 5: Create the AppConfig that calls it at startup**

Create `camp/apps/queues/apps.py`:
```python
from django.apps import AppConfig


class QueuesConfig(AppConfig):
    name = 'camp.apps.queues'

    def ready(self):
        from .stats import configure_queue_stats
        configure_queue_stats('primary')
```

- [ ] **Step 6: Register the app in `INSTALLED_APPS`**

In `camp/settings/base.py`, in the `camp.apps.*` block, add the app. Find:
```python
    'camp.apps.qaqc',
```
Replace with:
```python
    'camp.apps.qaqc',
    'camp.apps.queues',
```

- [ ] **Step 7: Run the new tests to verify they pass**

Run: `docker compose run --rm test pytest camp/apps/queues/tests.py -v`
Expected: PASS (both tests).

- [ ] **Step 8: Run the full suite to confirm nothing else broke**

Run: `docker compose run --rm test pytest`
Expected: PASS. (App `ready()` runs at startup; the test `primary` queue is `immediate=True`, so `configure_queue_stats('primary')` no-ops and leaves `get_huey` untouched during the suite.)

- [ ] **Step 9: Commit**

```bash
git add camp/apps/queues/__init__.py camp/apps/queues/apps.py camp/apps/queues/stats.py camp/apps/queues/tests.py camp/settings/base.py
git commit -m "feat(queues): point huey stats dashboard at the primary queue"
```

---

## Manual verification (post-implementation, not automated)

The automated suite runs in immediate mode, so it cannot exercise the live dashboard. Verify against a real consumer once (dev environment):

- [ ] Start the stack: `docker compose --profile web up` (brings up web + `djangohuey` consumers + Redis + Postgres).
- [ ] Confirm the stats tables were created in the dev Postgres (peewee `create table if not exists` on first `enable_stats`): `docker compose run --rm web python -c "from huey.contrib.djhuey.stats.apps import stats_database; db,_=stats_database(); print(db.get_tables())"` — expect `huey_event` and `huey_inflight` present.
- [ ] Enqueue a primary-queue task (any existing `db_task` on the primary/default queue) and let the consumer run it.
- [ ] Log into `/admin/`, open the **Huey** section → **Dashboard**. Confirm: the live tiles (Pending/Scheduled/Results/Running) reflect the `primary` queue, the task appears under recent events / throughput, and the **Events** changelist lists it with `queue = primary_tasks`.
- [ ] Confirm the flush/revoke controls act on the primary queue (optional; revoke a scheduled task and verify).

If the dashboard shows an empty/default instance instead of primary, `get_huey` was not patched — check that `camp.apps.queues` is in `INSTALLED_APPS` and that the primary queue is not running in immediate mode in that environment.

---

## Self-Review

**Spec coverage:**
- Dependency upgrade `3.0.1 → 3.3.0` → Task 1. ✅ (plus the peewee soft-dep the spec's `stats_database()`/peewee tables imply → Task 1.)
- `INSTALLED_APPS` adds `huey.contrib.djhuey.stats` → Task 2 Step 1. ✅
- `HUEY_STATS` with `capture_args: False` → Task 2 Step 2. ✅
- Test-suite isolation via sqlite `HUEY_STATS['database']` (revised §5) → Task 2 Step 3. ✅
- New app `camp.apps.queues` mirroring `djhuey.stats`, with `stats.py` separable from a future `tasks_backend.py` → Task 3 (package layout, `stats.py`). ✅
- Queue-parametrized `configure_queue_stats(queue_name, queue=None, db=None)` with immediate guard, `enable_stats`, monkeypatch → Task 3 Step 4. ✅
- `ready()` calls it with `'primary'` → Task 3 Step 5. ✅
- Unit tests: recorder+patch on live queue, and immediate-mode no-op, with `get_huey` restored per test → Task 3 Step 2. ✅
- No Procfile change; no Django migration (`managed=False` + peewee DDL) → reflected: no such tasks; manual-verification confirms tables. ✅
- Manual rendered-dashboard verification → Manual verification section. ✅
- Out-of-scope items (multi-queue pages, `django.tasks` backend, "registered tasks" list, secondary/summaries) → intentionally not tasked. ✅

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every run step shows the exact command and expected result. ✅

**Type consistency:** `configure_queue_stats(queue_name, queue=None, db=None)` is defined in Task 3 Step 4 and consumed identically in the tests (Step 2) and `apps.py` (Step 5). `stats_admin.get_huey` reassigned in Step 4 and asserted in Step 2. `stats_database() -> (db, options)` used as declared. ✅
