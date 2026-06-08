# Django 5.2 Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade SJVAir from Django 4.2 LTS to Django 5.2 LTS, resolving all breaking changes and incompatible third-party packages.

**Architecture:** Work in three phases — fix all deprecations that are safe on current Django 4.2 first (so tests keep passing throughout), then bump Django + packages together, then iterate on test failures and uncertain packages.

**Tech Stack:** Django 5.2.14, PostGIS, Huey, django-resticus (custom fork), docker compose for all commands.

---

## Compatibility Summary

### Breaking changes that affect this codebase

| Issue | Location | Fix |
|---|---|---|
| `OSMGeoAdmin` removed (Django 5.0) | `monitors/admin.py:80`, `regions/admin.py:86` | Replace with `GISModelAdmin` |
| `USE_L10N` setting removed (Django 5.0) | `camp/settings/base.py:244` | Remove the line |
| `DEFAULT_FILE_STORAGE` removed (Django 5.1) | `camp/settings/heroku.py:39` | Replace with `STORAGES` dict |
| `django-heroku` incompatible with Django 5.x | `camp/settings/heroku.py:2` | Remove import + remove from requirements |
| `dj-static` abandoned (2014), redundant with whitenoise | `camp/wsgi.py` | Replace `Cling(...)` with plain `get_wsgi_application()`, remove from requirements |
| `asgiref==3.7.2` too old (Django 5.1 needs ≥3.8.1) | `requirements/base.txt` | Remove — it's a Django transitive dep, not directly imported |

### Packages to remove (unused or redundant)

| Package | Reason |
|---|---|
| `django-heroku==0.3.1` | Import already removed in Task 2; incompatible and unmaintained |
| `dj-static==0.0.6` | Replaced in Task 2; abandoned since 2014, whitenoise handles static serving |
| `django-annoying==0.10.6` | Not imported anywhere in `camp/` |
| `channels==4.0.0` | Not in `INSTALLED_APPS`, no imports found in codebase |
| `channels-redis==4.1.0` | Only a dependency of `channels`, which isn't used |
| `python-aqi==0.6.1` | Not imported anywhere |
| `ctx-python==0.0.1a10` | Already at latest (PyPI only has up to a10); keep as-is |
| `asgiref==3.7.2` | Transitive Django dep, not directly imported; let Django manage it |

### Packages that definitely need version bumps

| Package | Current | Target | Notes |
|---|---|---|---|
| `Django` | 4.2.30 | 5.2.14 | Core upgrade |
| `dj-database-url` | 2.0.0 | 3.1.2 | Django 5.2 support |
| `django-cors-headers` | 4.2.0 | 4.9.0 | Compatible |
| `django-debug-toolbar` | 4.1.0 | 6.3.0 | Compatible |
| `django-dirtyfields` | 1.9.2 | 1.9.9 | Compatible |
| `django-extensions` | 3.2.3 | 4.1 | Compatible |
| `django-filter` | 23.2 | 25.2 | Now requires Django≥5.2 |
| `django-health-check` | 3.18.3 | 4.4.1 | **Major version** — see Task 4 |
| `django-huey` | 1.1.1 | 1.3.1 | Compatible |
| `django-jsonform` | 2.22.0 | 2.23.2 | Latest, assumed compatible |
| `django-model-utils` | 4.3.1 | 5.0.0 | Compatible |
| `django-pgactivity` | 1.7.1 | 1.8.0 | Compatible |
| `django-phonenumber-field` | 7.1.0 | 8.4.0 | Compatible, needs Python 3.10+ |
| `django-prose` | 2.0.0 | 2.1.0 | Compatible |
| `django-recaptcha` | 4.0.0 | 4.1.0 | Compatible |
| `django-storages` | 1.13.2 | 1.14.6 | S3 backend, compatible |
| `scout-apm` | 2.26.1 | 3.5.3 | Latest; Django 5.x untested but probably fine |
| `sentry-sdk` | 1.45.1 | 2.61.1 | Latest |
| `whitenoise` | 6.5.0 | 6.12.0 | Latest |

**Dev dependencies:**

| Package | Current | Target |
|---|---|---|
| `pytest` | 6.2.5 | 7.4+ (pytest-django 4.12 requires pytest≥7) |
| `pytest-django` | 4.5.2 | 4.12.0 |
| `pytest-asyncio` | 0.18.3 | 1.1.0 |

### Packages requiring investigation after the bump

| Package | Current | Issue |
|---|---|---|
| `django-vanilla-views` | 3.0.0 | Only tested to Django 3.2; used in 6 view files |
| `django-smalluuid` | 1.2.1 | Only tested to Django 4.0; used as PK field |
| `django-admin-inline-paginator` | 0.4.0 | Last release 2023, no explicit Django 5.x classifiers |

---

## Task 1: Fix OSMGeoAdmin → GISModelAdmin

`OSMGeoAdmin` and `GeoModelAdmin` were removed in Django 5.0. The replacement is `GISModelAdmin` (from `django.contrib.gis.admin`). This is safe to do on Django 4.2 — `GISModelAdmin` exists in 4.2 already.

**Files:**
- Modify: `camp/apps/monitors/admin.py`
- Modify: `camp/apps/regions/admin.py`

- [ ] **Step 1: Fix monitors/admin.py**

Open `camp/apps/monitors/admin.py`. Line 9 currently imports `from django.contrib.gis import admin as gisadmin`. Line 80 has `class MonitorAdmin(gisadmin.OSMGeoAdmin):`.

Replace:
```python
# line 9 — current
from django.contrib.gis import admin as gisadmin

# line 80 — current
class MonitorAdmin(gisadmin.OSMGeoAdmin):
```

With:
```python
# line 9 — new
from django.contrib.gis import admin as gisadmin

# line 80 — new
class MonitorAdmin(gisadmin.GISModelAdmin):
```

(Only the class base changes; the import alias stays the same.)

- [ ] **Step 2: Fix regions/admin.py**

Open `camp/apps/regions/admin.py`. Line 6 has `from django.contrib.gis.admin import OSMGeoAdmin`. Line 86 uses `OSMGeoAdmin` as a base.

Replace:
```python
from django.contrib.gis.admin import OSMGeoAdmin
```
with:
```python
from django.contrib.gis.admin import GISModelAdmin
```

And:
```python
class RegionAdmin(ReadOnlyAdminMixin, OSMGeoAdmin):
```
with:
```python
class RegionAdmin(ReadOnlyAdminMixin, GISModelAdmin):
```

- [ ] **Step 3: Verify tests still pass on Django 4.2**

```bash
docker compose run --rm test pytest camp/apps/monitors/ camp/apps/regions/ -v
```

Expected: all tests pass (this change is backward-compatible).

- [ ] **Step 4: Commit**

```bash
git add camp/apps/monitors/admin.py camp/apps/regions/admin.py
git commit -m "Replace OSMGeoAdmin with GISModelAdmin (removed in Django 5.0)"
```

---

## Task 2: Remove USE_L10N and fix settings/wsgi deprecations

`USE_L10N` was deprecated in Django 4.0 and removed in 5.0. Also remove the unused `import django_heroku`, migrate `DEFAULT_FILE_STORAGE` to the `STORAGES` dict format (removed in Django 5.1), and replace the abandoned `dj-static` `Cling` wrapper in `wsgi.py` with plain `get_wsgi_application()` — whitenoise middleware already handles static serving.

**Files:**
- Modify: `camp/settings/base.py`
- Modify: `camp/settings/heroku.py`
- Modify: `camp/wsgi.py`

- [ ] **Step 1: Remove USE_L10N from base.py**

In `camp/settings/base.py` around line 244, remove this line:
```python
USE_L10N = True
```

Leave `USE_I18N = True` and `USE_TZ = True` in place.

- [ ] **Step 2: Remove django_heroku from heroku.py**

In `camp/settings/heroku.py`, remove line 2:
```python
import django_heroku
```

That's the only reference — the `django_heroku.settings(locals())` call that would normally follow it was never added to this file, so removing the import is the entire change.

- [ ] **Step 3: Replace DEFAULT_FILE_STORAGE with STORAGES dict in heroku.py**

In `camp/settings/heroku.py`, replace:
```python
DEFAULT_FILE_STORAGE = 'camp.utils.storage.S3UploadStorage'
```

With:
```python
STORAGES = {
    "default": {
        "BACKEND": "camp.utils.storage.S3UploadStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}
```

This preserves existing behavior: S3 for media files, default local storage for static files (static files are managed separately via whitenoise middleware and manual S3 sync).

- [ ] **Step 4: Replace dj-static in wsgi.py**

`dj-static` hasn't been updated since 2014 and its `Cling` wrapper is redundant — `WhiteNoiseMiddleware` already handles static file serving. In `camp/wsgi.py`, replace:

```python
from dj_static import Cling

dotenv.load_dotenv(dotenv.find_dotenv())
application = Cling(get_wsgi_application())
```

With:

```python
dotenv.load_dotenv(dotenv.find_dotenv())
application = get_wsgi_application()
```

Remove the `from dj_static import Cling` line entirely.

- [ ] **Step 5: Verify tests still pass**

```bash
docker compose run --rm test pytest -v -x
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add camp/settings/base.py camp/settings/heroku.py camp/wsgi.py
git commit -m "Remove Django 4.x deprecations: USE_L10N, DEFAULT_FILE_STORAGE, django_heroku, dj-static"
```

---

## Task 3: Bump Django and all compatible packages

Update `requirements/base.txt` and `requirements/develop.txt` with the new versions identified above, then rebuild the Docker image and run the test suite for the first time on Django 5.2.

**Files:**
- Modify: `requirements/base.txt`
- Modify: `requirements/develop.txt`

- [ ] **Step 1: Update requirements/base.txt**

**Remove these lines entirely:**
```
asgiref==3.7.2
channels==4.0.0
channels-redis==4.1.0
dj-static==0.0.6
django-annoying==0.10.6
django-heroku==0.3.1
python-aqi==0.6.1
```

**Bump these lines (old → new):**
```
Django==4.2.30                                          → Django==5.2.14
dj-database-url==2.0.0                                  → dj-database-url==3.1.2
django-cors-headers==4.2.0                              → django-cors-headers==4.9.0
django-debug-toolbar==4.1.0                             → django-debug-toolbar==6.3.0
django-dirtyfields==1.9.2                               → django-dirtyfields==1.9.9
django-extensions==3.2.3                                → django-extensions==4.1
django-filter==23.2                                     → django-filter==25.2
django-health-check==3.18.3                             → django-health-check==4.4.1
django-huey==1.1.1                                      → django-huey==1.3.1
django-jsonform==2.22.0                                 → django-jsonform==2.23.2
django-model-utils==4.3.1                               → django-model-utils==5.0.0
django-pgactivity==1.7.1                                → django-pgactivity==1.8.0
django-phonenumber-field[phonenumberslite]==7.1.0       → django-phonenumber-field[phonenumberslite]==8.4.0
django-prose==2.0.0                                     → django-prose==2.1.0
django-recaptcha==4.0.0                                 → django-recaptcha==4.1.0
django-storages==1.13.2                                 → django-storages==1.14.6
scout-apm==2.26.1                                       → scout-apm==3.5.3
sentry-sdk==1.45.1                                      → sentry-sdk==2.61.1
whitenoise==6.5.0                                       → whitenoise==6.12.0
# ctx-python stays at 0.0.1a10 — already the latest on PyPI
```

Leave `django-vanilla-views`, `django-smalluuid`, and `django-admin-inline-paginator` at their current versions for now — they will be tested in Task 5.

- [ ] **Step 2: Update requirements/develop.txt**

In `requirements/develop.txt`, bump:
```
# Change:
pytest==6.2.5
# To:
pytest==7.4.4

# Change:
pytest-django==4.5.2
# To:
pytest-django==4.12.0

# Change:
pytest-asyncio==0.18.3
# To:
pytest-asyncio==1.1.0
```

- [ ] **Step 3: Rebuild Docker image**

```bash
docker compose build
```

Expected: image builds successfully. If pip dependency resolution fails, there's a version conflict — read the error carefully and adjust the conflicting package version.

- [ ] **Step 4: Run Django system check**

```bash
docker compose run --rm web python manage.py check
```

Expected: `System check identified no issues (0 silenced).`

If any errors appear, address them before running tests.

- [ ] **Step 5: Commit requirements**

```bash
git add requirements/base.txt requirements/develop.txt
git commit -m "Upgrade Django 4.2 → 5.2.14 and bump compatible third-party packages"
```

---

## Task 4: Handle django-health-check 3.x → 4.x migration

`django-health-check` 4.0 is a major release with significant internal changes (switched to asyncio, dropped the old `health_check_status` database table). It requires a migration to clean up the old table.

- [ ] **Step 1: Run the health_check migration**

```bash
docker compose run --rm web python manage.py migrate
```

The `django-health-check` 4.0 migration drops the obsolete `health_check_status` table. This must run before starting the app.

Expected output includes lines like:
```
Running migrations:
  Applying health_check.0001_squashed_0004_auto_20160822_2132... OK
```

- [ ] **Step 2: Verify health check URLs still work**

The health check URL is mounted at `system-status/` in `camp/urls.py`. Start the dev server and check:

```bash
docker compose --profile web up
```

Then visit `http://localhost:8000/system-status/` in a browser. All checks should display (db, cache, storage, redis, migrations, psutil, s3).

If the redis health check fails or errors, it may need explicit configuration. In `django-health-check` 4.x, the redis check's `redis_url` option was removed; it now reads from Django's cache settings or from a direct client. Since Redis is used only for Huey (not as a Django cache backend), the `health_check.contrib.redis` app may need to be removed from `INSTALLED_APPS` if it no longer auto-detects the connection.

If redis health check is broken:
- Remove `'health_check.contrib.redis'` from `INSTALLED_APPS` in `camp/settings/base.py`
- Commit the change

- [ ] **Step 3: Commit if any settings changed**

```bash
git add camp/settings/base.py
git commit -m "Fix health_check redis config for django-health-check 4.x"
```

---

## Task 5: Run the full test suite and fix initial failures

- [ ] **Step 1: Run all tests**

```bash
docker compose run --rm test pytest -v 2>&1 | tee /tmp/test_output.txt
```

- [ ] **Step 2: Categorize failures**

Look at the output and group failures:
- Import errors at startup → package incompatibility, fix before individual test errors
- `AttributeError` or `ImportError` related to `vanilla` → django-vanilla-views issue (see Task 6)
- `AttributeError` on `SmallUUIDField` or `pk` → django-smalluuid issue (see Task 7)
- Other Django errors → address inline

For any failure not related to vanilla or smalluuid: read the traceback, identify the root cause, and fix it.

- [ ] **Step 3: Fix any misc failures**

Common patterns to watch for:

**Form renderer**: If forms render differently (Django 5.0 defaulted to div-based rendering), update affected templates. Check any templates that test form output against expected HTML.

**Admin HTML changes**: Django 5.0 changed `<h1>` → `<div>` for `site_header`, and 5.1 changed filter `<div>` → `<nav>`, footer `<div>` → `<footer>`. If any tests assert against admin HTML, update the expected output.

- [ ] **Step 4: Commit any misc fixes**

```bash
git add <changed files>
git commit -m "Fix miscellaneous Django 5.2 compatibility issues"
```

---

## Task 6: Verify django-vanilla-views under Django 5.2

`django-vanilla-views` 3.0.0 was only tested to Django 3.2 but may still work under Django 5.2 since it wraps Django's own generic CBVs. The fix depends on what actually fails.

**Files using vanilla views:**
- `camp/apps/accounts/views.py` — `vanilla.CreateView`, `UpdateView`, `FormView`
- `camp/apps/alerts/views.py` — `vanilla.ListView`, `TemplateView`
- `camp/apps/contact/views.py` — `vanilla.FormView`, `TemplateView`
- `camp/apps/helpdesk/views.py` — `vanilla.TemplateView`, `DetailView`, `ListView`
- `camp/utils/views.py` — `vanilla.TemplateView`
- `camp/apps/accounts/urls.py` — references `vanilla` for URL reversals

- [ ] **Step 1: Check if vanilla views work at all**

```bash
docker compose run --rm test pytest camp/apps/accounts/ camp/apps/alerts/ camp/apps/contact/ camp/apps/helpdesk/ -v
```

**If tests pass:** vanilla views work fine under Django 5.2. No action needed beyond noting it.

**If tests fail with ImportError or AttributeError from vanilla:** Proceed to Step 2.

- [ ] **Step 2 (only if Step 1 fails): Replace vanilla with Django built-ins**

`django-vanilla-views` is a thin wrapper. Each `vanilla.*` class maps directly to a `django.views.generic.*` equivalent:

| vanilla | Django built-in |
|---|---|
| `vanilla.TemplateView` | `generic.TemplateView` |
| `vanilla.ListView` | `generic.ListView` |
| `vanilla.DetailView` | `generic.DetailView` |
| `vanilla.FormView` | `generic.FormView` |
| `vanilla.CreateView` | `generic.CreateView` |
| `vanilla.UpdateView` | `generic.UpdateView` |

In each file that imports `vanilla`, replace:
```python
import vanilla
```
with nothing (remove), and change all `vanilla.TemplateView` etc. to `generic.TemplateView` etc., where `generic` is already imported as:
```python
from django.views import generic
```

If `from django.views import generic` is not already in the file, add it.

After replacing all 6 files, remove `django-vanilla-views==3.0.0` from `requirements/base.txt` and rebuild.

- [ ] **Step 3: Run tests again to confirm**

```bash
docker compose run --rm test pytest camp/apps/accounts/ camp/apps/alerts/ camp/apps/contact/ camp/apps/helpdesk/ -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add camp/apps/accounts/views.py camp/apps/alerts/views.py camp/apps/contact/views.py \
        camp/apps/helpdesk/views.py camp/utils/views.py camp/apps/accounts/urls.py \
        requirements/base.txt
git commit -m "Replace django-vanilla-views with Django built-in generic CBVs (vanilla-views untested on Django 5.x)"
```

---

## Task 7: Verify django-smalluuid under Django 5.2

`django-smalluuid` provides `SmallUUIDField` used as primary keys throughout legacy models. It was only tested to Django 4.0. The most common failure mode is if Django's internal `Field` API changed in a way that breaks `SmallUUIDField`.

- [ ] **Step 1: Run model-heavy tests**

```bash
docker compose run --rm test pytest camp/apps/monitors/ camp/apps/entries/ camp/apps/calibrations/ -v
```

**If tests pass:** smalluuid is fine. No action needed.

**If tests fail with errors from `smalluuid`:** Note the exact error (e.g., `TypeError` in `contribute_to_class`, `AttributeError` on field internals). Then:

- [ ] **Step 2 (only if Step 1 fails): Diagnose the smalluuid error**

Check the traceback. The most likely fix is a simple monkey-patch in the custom fork or a minor subclass override.

If `django-smalluuid` is broken and unfixable via a quick patch:
- The `SmallUUIDField` field stores URL-safe UUIDs. A drop-in replacement is `django.db.models.UUIDField` combined with a custom `to_python` / `from_db_value` for URL-safe encoding.
- However, this would require migrations on all affected models and is a significant change. Escalate to the project owner before proceeding.

If the fix is small (e.g., a one-line patch to the smalluuid source), apply it and install from the local path or a fork.

- [ ] **Step 3: Commit any fix**

```bash
git add <changed files>
git commit -m "Fix django-smalluuid compatibility with Django 5.2"
```

---

## Task 8: Run the complete test suite and confirm green

- [ ] **Step 1: Run all tests**

```bash
docker compose run --rm test pytest -v
```

Expected: all tests pass (0 failures, 0 errors).

- [ ] **Step 2: Run Django system check in strict mode**

```bash
docker compose run --rm web python manage.py check --deploy 2>&1
```

Review any warnings; address any that are errors.

- [ ] **Step 3: Run a database migration check**

```bash
docker compose run --rm web python manage.py migrate --check
```

Expected: no pending migrations.

- [ ] **Step 4: Smoke test the admin and API**

Start the dev server:
```bash
docker compose --profile web up
```

Manually verify:
- Admin login works at `http://localhost:8000/admin/`
- Monitor list is visible in admin (tests that `GISModelAdmin` map renders)
- API responds at `http://localhost:8000/api/2.0/monitors/`
- Health check responds at `http://localhost:8000/system-status/`

- [ ] **Step 5: Final commit if any remaining changes**

```bash
git add <any remaining files>
git commit -m "Django 5.2 upgrade: all tests passing"
```

---

## Known non-issues

These look concerning but are safe to ignore:

- **`pytz` usage in management commands** (`aqview/models.py`, `qaqc/admin.py`, `test/helpers.py`, several management commands): Django 5.0 removed pytz from Django's *own* timezone handling but `pytz` as a library still works. These files use `pytz.timezone()` only for Python datetime arithmetic, not in Django ORM queries, so they are unaffected. Clean up is optional.

- **`django-form-utils` in INSTALLED_APPS**: This custom GitHub fork is listed in installed apps but has no Python imports in camp/. It likely provides template tags used in admin forms. If it causes errors at startup, remove it from INSTALLED_APPS and requirements.

- **`channels` / `channels-redis` not in INSTALLED_APPS**: These packages are in requirements but `channels` is not in `INSTALLED_APPS` and is never imported. They may be unused. If they cause install errors, they can be removed.

- **`form-renderer` changes**: Django 5.0 switched default form rendering from table-based to div-based. This codebase does not use `.as_table()`, `.as_p()`, or `_html_output()` anywhere in templates or Python, so no changes are needed.

---

## If things go badly wrong

If the upgrade introduces regressions you can't quickly fix, the safe fallback is:

```bash
git checkout main
```

All work is on a separate branch. Nothing in the above plan modifies production data.
