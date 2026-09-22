# Admin Reports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `camp.apps.reports` app with a report index and five staff-only admin report pages (county subscription stats moved in, plus network overview, coverage and equity, fleet health, degraded monitors), each with CSV export.

**Architecture:** A `BaseReport` view (django-vanilla-views `TemplateView` behind `staff_member_required`) supplies admin chrome, `get_rows()` for the primary table, and a CSV response when `?format=csv` is present. A module-level registry drives URL generation and the index page. Each report is one class in `views.py` plus one template. No models, no migrations, no caching, no JavaScript.

**Tech Stack:** Django 5.2, PostGIS via `django.contrib.gis`, django-vanilla-views 3.0, pytest-django with Django `TestCase`.

**Spec:** `docs/superpowers/specs/2026-09-16-admin-reports-design.md`

## Global Constraints

- All commands run inside Docker. This branch lives in a worktree, so use the worktree test harness (see "Running tests" below).
- Tests inherit from `django.test.TestCase`, use plain `assert`, and use `/fixtures/*.yaml` via `fixtures = [...]` where they fit.
- No AI-authorship attribution in commit messages beyond the trailer the session reminder requires. Never `git add -A`; list files explicitly.
- Verbose names use `_()` as the first positional arg. Do not align `=` in field definitions. (No models here, but the rule applies to any form fields.)
- Timezone is `America/Los_Angeles`; use `django.utils.timezone` helpers.
- Alerts/subscription growth reports are out of scope. Caching is out of scope.
- Monitor "type" everywhere means a concrete subclass from `Monitor.get_subclasses()`, labelled by the class name (`PurpleAir`, `BAM1022`, ...). All subclasses are included, not only `MONITOR_ENABLED_TYPES`, because these are internal reports.

## Running tests

The worktree has no `.env.test`. Run tests through the main checkout's compose config with the worktree bind-mounted and a unique DB name:

```bash
docker compose -f /home/derek/dev/ccac/sjvair.com/docker-compose.yml \
  --project-directory /home/derek/dev/ccac/sjvair.com \
  run --rm -T -e DATABASE_URL=postgis://sjvair:changeme@db:5432/sjvair_reports \
  -v /home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+admin-reports:/app \
  test pytest camp/apps/reports/tests.py -v -p no:cacheprovider --create-db
```

Below, `RUN_TESTS <args>` means the command above with `camp/apps/reports/tests.py -v -p no:cacheprovider --create-db` replaced by `<args> -p no:cacheprovider --create-db`. The `fatal: not a git repository` line inside the container is harmless.

## Reference facts (verified in the codebase)

- `Monitor` (`camp/apps/monitors/models.py`) fields: `name`, `created`, `is_hidden`, `is_sjvair`, `device`, `host` (FK to `Host`, nullable), `position` (PointField, nullable), `county` (CharField, choices from `County.names`, set automatically on save from `position`), `location`, `health` (OneToOne to `qaqc.HealthCheck`, nullable). `Monitor.LAST_ACTIVE_LIMIT = 3600` seconds.
- `Monitor.get_subclasses()` returns concrete subclasses sorted by class name: `AQLite, AQview, AirGradient, AirNow, BAM1022, CIMIS, PurpleAir, VOZBox`. `subclass.monitor_type` is the model name (`purpleair`), `subclass._meta.app_label` is the app label (`purpleair`). Subclasses inherit `Monitor.objects` (a `MonitorManager` whose queryset has `with_last_entry_timestamp()` which annotates `last_entry_timestamp` from `LatestEntry`).
- `subclass.health_check_queryset_filter()` returns `{f'{monitor_type}__isnull': False}`, usable on `Monitor.objects` to select one subclass. `Monitor.objects.get_for_health_checks()` returns monitors whose class has two PM2.5 sensors.
- `HealthCheck` (`camp/apps/qaqc/models.py`): `monitor`, `hour`, `score` (3=A, 2=B, 1=C, 0=F), `sanity_flatline_a`, `sanity_flatline_b` (nullable booleans; `False` means the flatline check failed), `.grade` property.
- `LatestEntry` (`camp/apps/monitors/models.py`): `monitor`, `entry_type`, `entry_id`, `stage`, `processor`, `timestamp`; unique on `(monitor, entry_type, processor)`.
- `County` (`camp/utils/counties.py`): `County.names` is the sorted list of the 8 SJV county names; `County.keys` maps `fresno` → `Fresno`, `san_joaquin` → `San Joaquin`; `County.counties` maps name → `GEOSGeometry` (SRID unset, WGS84 coordinates).
- CES (`camp/apps/ces/models.py`): `CES4` and `CES5` share abstract `CESRecord` with `boundary` (OneToOne to `regions.Boundary`), `population`, `ci_score_p`, `dac_sb535`. `boundary.version` is the census vintage (`'2010'`, `'2020'`), `boundary.geometry` is a `MultiPolygonField` (SRID 4326). The default manager `select_related`s and defers geometry, so use `Model._base_manager` inside subqueries.
- Fixture `calenviroscreen.yaml`: two Fresno tracts. Tract 1.01 (2020 boundary pk 1003) covers lon −119.8..−119.7, lat 36.7..36.8, DAC, CES5 population 4650, percentile 89.2. Tract 1.02 (2020 boundary pk 1004) covers lon −119.7..−119.6, lat 36.7..36.8, not DAC, CES5 population 3350, percentile 51.0. Both have 2010 and 2020 boundaries and both CES4 and CES5 records for 2020.
- Fixture `purple-air.yaml`: one `PurpleAir` monitor pk `jLI5fer7S0uyR7eMYNSPpg`, `sensor_id=8892`, at lon −119.798678 lat 36.762742 (Fresno, inside tract 1.01). Loaded via `loaddata`, so its `county` field is blank (save() is not called). Tests below create their own monitors with `objects.create()` so `county` is populated.
- `User.objects.create_superuser(email=..., password=..., phone=..., full_name=...)` is the pattern in `camp/utils/tests/test_admin_maps.py`.
- Existing county stats: view `SubscriptionCountyStats` in `camp/apps/alerts/views.py`, URL registered in `SubscriptionAdmin.get_urls()` in `camp/apps/alerts/admin.py` under name `alerts_subscription_county_stats`, template `camp/templates/admin/alerts/subscription/county_stats.html`, linked from `camp/templates/admin/index.html` Quick Links.
- Admin is mounted at `batcave/` in `camp/urls.py`.

## File structure

```
camp/apps/reports/__init__.py           # empty
camp/apps/reports/apps.py               # ReportsConfig
camp/apps/reports/base.py               # REPORTS registry, register(), BaseReport, ReportIndex
camp/apps/reports/views.py              # concrete reports (one class each)
camp/apps/reports/urls.py               # index + one path per registered report
camp/apps/reports/tests.py              # all tests for the app
camp/templates/admin/reports/base.html
camp/templates/admin/reports/index.html
camp/templates/admin/reports/subscription_county_stats.html   # moved
camp/templates/admin/reports/network_overview.html
camp/templates/admin/reports/fleet_health.html
camp/templates/admin/reports/degraded_monitors.html
camp/templates/admin/reports/coverage.html
```

Modified: `camp/settings/base.py` (INSTALLED_APPS), `camp/urls.py` (include), `camp/templates/admin/index.html` (Quick Links), `camp/apps/alerts/admin.py` (redirect), `camp/apps/alerts/views.py` (remove moved view). Deleted: `camp/templates/admin/alerts/subscription/county_stats.html`.

---

### Task 1: App scaffold, `BaseReport`, index page

**Files:**
- Create: `camp/apps/reports/__init__.py`, `camp/apps/reports/apps.py`, `camp/apps/reports/base.py`, `camp/apps/reports/views.py`, `camp/apps/reports/urls.py`, `camp/apps/reports/tests.py`
- Create: `camp/templates/admin/reports/base.html`, `camp/templates/admin/reports/index.html`
- Modify: `camp/settings/base.py` (INSTALLED_APPS list, after `'camp.apps.regions',`)
- Modify: `camp/urls.py` (before `path('batcave/', admin.site.urls)`)

**Interfaces:**
- Produces: `camp.apps.reports.base.REPORTS: list[type[BaseReport]]`, `register(cls) -> cls`, `BaseReport` with class attrs `slug: str`, `title: str`, `description: str`, `template_name: str`, and methods `get_rows(self) -> list[dict]`, `get_csv_columns(self, rows) -> list[str]`, `get_context_data(**kwargs)` (adds admin context, `title`, `report`, `rows`, `csv_query`). URL names: `reports:index` and `reports:<slug>`.

- [ ] **Step 1: Write the failing tests**

`camp/apps/reports/tests.py`:

```python
from django.test import TestCase
from django.urls import reverse

from camp.apps.accounts.models import User


class StaffClientMixin:
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_superuser(
            email='admin@example.com',
            password='password',
            phone='+15595551234',
            full_name='Admin',
        )
        self.client.force_login(self.user)


class ReportIndexTests(StaffClientMixin, TestCase):
    def test_index_renders_for_staff(self):
        response = self.client.get(reverse('reports:index'))
        assert response.status_code == 200
        assert b'Reports' in response.content

    def test_index_redirects_anonymous(self):
        self.client.logout()
        response = self.client.get(reverse('reports:index'))
        assert response.status_code == 302
        assert '/login/' in response['Location']
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `RUN_TESTS camp/apps/reports/tests.py -v`
Expected: ERROR at collection (`ModuleNotFoundError: No module named 'camp.apps.reports'`) or `NoReverseMatch: 'reports' is not a registered namespace`.

- [ ] **Step 3: Create the app**

`camp/apps/reports/__init__.py`: empty file.

`camp/apps/reports/apps.py`:

```python
from django.apps import AppConfig


class ReportsConfig(AppConfig):
    name = 'camp.apps.reports'
    verbose_name = 'Reports'
```

`camp/apps/reports/base.py`:

```python
import csv

from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse
from django.utils import timezone
from django.utils.decorators import method_decorator

import vanilla


REPORTS = []


def register(cls):
    """Class decorator: add a report to the index and URL registry."""
    REPORTS.append(cls)
    return cls


@method_decorator(staff_member_required, name='dispatch')
class BaseReport(vanilla.TemplateView):
    slug = None
    title = None
    description = ''
    template_name = None

    def get_rows(self):
        """Primary table as a list of dicts. Keys become CSV columns."""
        raise NotImplementedError

    def get_csv_columns(self, rows):
        return list(rows[0].keys()) if rows else []

    def get_context_data(self, **kwargs):
        csv_query = self.request.GET.copy()
        csv_query['format'] = 'csv'
        return {
            **super().get_context_data(**kwargs),
            **admin.site.each_context(self.request),
            'title': self.title,
            'report': self,
            'rows': self.get_rows(),
            'csv_query': csv_query.urlencode(),
        }

    def render_to_response(self, context):
        if self.request.GET.get('format') == 'csv':
            return self.render_csv(context['rows'])
        return super().render_to_response(context)

    def render_csv(self, rows):
        today = timezone.localdate().isoformat()
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{self.slug}-{today}.csv"'
        writer = csv.DictWriter(response, fieldnames=self.get_csv_columns(rows), extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
        return response


@method_decorator(staff_member_required, name='dispatch')
class ReportIndex(vanilla.TemplateView):
    template_name = 'admin/reports/index.html'

    def get_context_data(self, **kwargs):
        return {
            **super().get_context_data(**kwargs),
            **admin.site.each_context(self.request),
            'title': 'Reports',
            'reports': REPORTS,
        }
```

`camp/apps/reports/views.py` (reports are added in later tasks):

```python
from camp.apps.reports.base import BaseReport, register
```

`camp/apps/reports/urls.py`:

```python
from django.urls import path

from camp.apps.reports import views  # noqa: F401 -- importing registers the reports
from camp.apps.reports.base import REPORTS, ReportIndex

urlpatterns = [
    path('', ReportIndex.as_view(), name='index'),
    *[path(f'{report.slug}/', report.as_view(), name=report.slug) for report in REPORTS],
]
```

- [ ] **Step 4: Register the app and URLs**

In `camp/settings/base.py`, INSTALLED_APPS, add `'camp.apps.reports',` directly after `'camp.apps.regions',`.

In `camp/urls.py`, immediately before `path('batcave/', admin.site.urls),` add:

```python
    path('batcave/reports/', include(('camp.apps.reports.urls', 'reports'), namespace='reports')),
```

- [ ] **Step 5: Templates**

`camp/templates/admin/reports/base.html`:

```django
{% extends 'admin/base_site.html' %}
{% load i18n %}

{% block breadcrumbs %}
<div class="breadcrumbs">
    <a href="{% url 'admin:index' %}">{% translate 'Home' %}</a>
    &rsaquo; <a href="{% url 'reports:index' %}">Reports</a>
    &rsaquo; {{ title }}
</div>
{% endblock %}

{% block content %}
<div id="content-main">
    {% if report.description %}<p>{{ report.description }}</p>{% endif %}

    <form method="get" class="report-filters">
        {% block filters %}{% endblock %}
    </form>

    <p><a class="button" href="?{{ csv_query }}">Download CSV</a></p>

    {% block report %}{% endblock %}
</div>
{% endblock %}
```

`camp/templates/admin/reports/index.html`:

```django
{% extends 'admin/base_site.html' %}
{% load i18n %}

{% block breadcrumbs %}
<div class="breadcrumbs">
    <a href="{% url 'admin:index' %}">{% translate 'Home' %}</a>
    &rsaquo; Reports
</div>
{% endblock %}

{% block content %}
<div id="content-main">
    <div class="module">
        <table>
            <caption>Reports</caption>
            {% for report in reports %}
            <tr>
                <td>
                    <h3><a href="{% url 'reports:'|add:report.slug %}">{{ report.title }}</a></h3>
                    <p>{{ report.description }}</p>
                </td>
            </tr>
            {% empty %}
            <tr><td>No reports registered.</td></tr>
            {% endfor %}
        </table>
    </div>
</div>
{% endblock %}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `RUN_TESTS camp/apps/reports/tests.py -v`
Expected: both tests PASS.

- [ ] **Step 7: Commit**

```bash
git add camp/apps/reports/__init__.py camp/apps/reports/apps.py camp/apps/reports/base.py \
  camp/apps/reports/views.py camp/apps/reports/urls.py camp/apps/reports/tests.py \
  camp/templates/admin/reports/base.html camp/templates/admin/reports/index.html \
  camp/settings/base.py camp/urls.py
git commit -m "feat(reports): add reports app with base view and index"
```

---

### Task 2: Move county subscription stats into reports

**Files:**
- Modify: `camp/apps/reports/views.py`
- Modify: `camp/apps/reports/tests.py`
- Create: `camp/templates/admin/reports/subscription_county_stats.html`
- Delete: `camp/templates/admin/alerts/subscription/county_stats.html`
- Modify: `camp/apps/alerts/views.py` (remove `SubscriptionCountyStats` and now-unused imports)
- Modify: `camp/apps/alerts/admin.py` (`get_urls` becomes a redirect)
- Modify: `camp/templates/admin/index.html` (Quick Links)

**Interfaces:**
- Consumes: `BaseReport`, `register` from Task 1.
- Produces: URL `reports:subscription-county-stats`; the old name `admin:alerts_subscription_county_stats` still resolves and redirects.

- [ ] **Step 1: Write the failing tests**

Append to `camp/apps/reports/tests.py`:

```python
from django.contrib.gis.geos import Point

from camp.apps.alerts.models import Subscription
from camp.apps.monitors.purpleair.models import PurpleAir


class SubscriptionCountyStatsTests(StaffClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.fresno = PurpleAir.objects.create(name='Fresno PA', sensor_id=1, position=Point(-119.75, 36.75), location='outside')
        self.kern = PurpleAir.objects.create(name='Kern PA', sensor_id=2, position=Point(-119.0, 35.4), location='outside')
        Subscription.objects.create(user=self.user, monitor=self.fresno, level='unhealthy')

    def test_rows_count_monitors_and_subscriptions_per_county(self):
        response = self.client.get(reverse('reports:subscription-county-stats'))
        assert response.status_code == 200
        rows = {row['county']: row for row in response.context['rows']}
        assert rows['Fresno'] == {'county': 'Fresno', 'total_monitors': 1, 'subscription_monitors': 1, 'total_subscriptions': 1}
        assert rows['Kern'] == {'county': 'Kern', 'total_monitors': 1, 'subscription_monitors': 0, 'total_subscriptions': 0}

    def test_csv_export(self):
        response = self.client.get(reverse('reports:subscription-county-stats'), {'format': 'csv'})
        assert response.status_code == 200
        assert response['Content-Type'] == 'text/csv'
        assert 'subscription-county-stats-' in response['Content-Disposition']
        lines = response.content.decode().splitlines()
        assert lines[0] == 'county,total_monitors,subscription_monitors,total_subscriptions'
        assert 'Fresno,1,1,1' in lines

    def test_old_admin_url_redirects(self):
        response = self.client.get(reverse('admin:alerts_subscription_county_stats'))
        assert response.status_code in (301, 302)
        assert response['Location'] == reverse('reports:subscription-county-stats')

    def test_listed_on_index(self):
        response = self.client.get(reverse('reports:index'))
        assert reverse('reports:subscription-county-stats') in response.content.decode()
```

Note: `Kern` monitor at (−119.0, 35.4) is inside Kern County; `County.lookup` runs on `save()` so `county` is populated.

- [ ] **Step 2: Run tests to verify they fail**

Run: `RUN_TESTS camp/apps/reports/tests.py -v -k SubscriptionCountyStats`
Expected: FAIL with `NoReverseMatch` for `reports:subscription-county-stats`.

- [ ] **Step 3: Add the report**

Replace `camp/apps/reports/views.py` with:

```python
from django.db.models import Count, Q

from camp.apps.alerts.models import Subscription
from camp.apps.monitors.models import Monitor
from camp.apps.reports.base import BaseReport, register
from camp.utils.counties import County


@register
class SubscriptionCountyStats(BaseReport):
    slug = 'subscription-county-stats'
    title = 'Subscription Stats by County'
    description = 'Monitors, monitors with at least one subscriber, and total subscriptions, per county.'
    template_name = 'admin/reports/subscription_county_stats.html'

    def get_rows(self):
        monitor_lookup = {}
        subscription_lookup = {}
        for key, county in County.keys.items():
            monitor_lookup[f'{key}_total_monitors'] = Count('pk', filter=Q(county=county))
            monitor_lookup[f'{key}_subscription_monitors'] = Count('pk',
                filter=Q(county=county, subscriptions__isnull=False), distinct=True)
            subscription_lookup[f'{key}_total_subscriptions'] = Count('pk', filter=Q(monitor__county=county))

        monitor_stats = Monitor.objects.aggregate(**monitor_lookup)
        subscription_stats = Subscription.objects.aggregate(**subscription_lookup)

        return [{
            'county': county,
            'total_monitors': monitor_stats[f'{key}_total_monitors'],
            'subscription_monitors': monitor_stats[f'{key}_subscription_monitors'],
            'total_subscriptions': subscription_stats[f'{key}_total_subscriptions'],
        } for key, county in County.keys.items()]
```

- [ ] **Step 4: Move the template**

Create `camp/templates/admin/reports/subscription_county_stats.html`:

```django
{% extends 'admin/reports/base.html' %}
{% load humanize %}

{% block report %}
<table>
    <thead>
        <tr>
            <th>County</th>
            <th>Total Monitors</th>
            <th>Monitors with Subscription</th>
            <th>Total Subscriptions</th>
        </tr>
    </thead>
    <tbody>
        {% for row in rows %}
        <tr>
            <th>{{ row.county }}</th>
            <td>{{ row.total_monitors|intcomma }}</td>
            <td>{{ row.subscription_monitors|intcomma }}</td>
            <td>{{ row.total_subscriptions|intcomma }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% endblock %}
```

Delete `camp/templates/admin/alerts/subscription/county_stats.html` with `git rm`.

- [ ] **Step 5: Remove the old view and redirect the old URL**

In `camp/apps/alerts/views.py`, delete the `SubscriptionCountyStats` class and the imports it alone used: `admin`, `staff_member_required`, `Count`, `Q`, `method_decorator`, `Monitor`, `County`. Keep `LoginRequiredMixin`, `vanilla`, `Alert`, `Subscription`.

In `camp/apps/alerts/admin.py`, replace the import `from .views import SubscriptionCountyStats` with:

```python
from django.urls import path, reverse_lazy
from django.views.generic import RedirectView
```

(merge with the existing `from django.urls import path`) and change `get_urls` to:

```python
    def get_urls(self):
        return [
            path(
                'county-stats/',
                RedirectView.as_view(url=reverse_lazy('reports:subscription-county-stats')),
                name='alerts_subscription_county_stats',
            ),
            *super().get_urls(),
        ]
```

- [ ] **Step 6: Point the admin index at the reports index**

In `camp/templates/admin/index.html`, replace

```django
            <li><a href="{% url 'admin:alerts_subscription_county_stats' %}">Subscription Stats by County</a></li>
```

with

```django
            <li><a href="{% url 'reports:index' %}">Reports</a></li>
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `RUN_TESTS camp/apps/reports/tests.py camp/apps/alerts/tests.py -v`
Expected: all PASS. (Alerts tests must still pass after the view removal.)

- [ ] **Step 8: Commit**

```bash
git add camp/apps/reports/views.py camp/apps/reports/tests.py \
  camp/templates/admin/reports/subscription_county_stats.html \
  camp/apps/alerts/views.py camp/apps/alerts/admin.py camp/templates/admin/index.html
git rm camp/templates/admin/alerts/subscription/county_stats.html
git commit -m "refactor(reports): move county subscription stats into reports app"
```

---

### Task 3: Network Overview report

**Files:**
- Modify: `camp/apps/reports/views.py`
- Modify: `camp/apps/reports/tests.py`
- Create: `camp/templates/admin/reports/network_overview.html`

**Interfaces:**
- Consumes: `BaseReport`, `register`.
- Produces: URL `reports:network-overview`. Context keys: `rows` (per-type county matrix), `tiles` (dict), `deployments` (list of dicts), `counties` (list of names), `include_hidden` (bool). Module-level helper `monitor_types() -> list[type[Monitor]]` and `type_label(cls) -> str` reused by Tasks 4 and 5. Query param `include_hidden=1`.

- [ ] **Step 1: Write the failing tests**

Append to `camp/apps/reports/tests.py`:

```python
from datetime import timedelta

from django.utils import timezone

from camp.apps.entries.models import PM25
from camp.apps.monitors.bam.models import BAM1022
from camp.apps.monitors.models import LatestEntry


def touch(monitor, timestamp):
    """Give a monitor a PM2.5 entry and matching LatestEntry at `timestamp`."""
    entry = PM25.objects.create(monitor=monitor, sensor='a', timestamp=timestamp, value=5.0, stage=PM25.Stage.RAW)
    LatestEntry.objects.update_or_create(
        monitor=monitor, entry_type=PM25.entry_type, processor='',
        defaults={'entry_id': entry.pk, 'timestamp': timestamp, 'stage': PM25.Stage.RAW},
    )
    return entry


class NetworkOverviewTests(StaffClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        now = timezone.now()
        self.pa_fresno = PurpleAir.objects.create(name='PA Fresno', sensor_id=1, position=Point(-119.75, 36.75), location='outside', is_sjvair=True)
        self.pa_kern = PurpleAir.objects.create(name='PA Kern', sensor_id=2, position=Point(-119.0, 35.4), location='outside')
        self.bam = BAM1022.objects.create(name='BAM Fresno', position=Point(-119.76, 36.76), location='outside', is_sjvair=True)
        self.hidden = PurpleAir.objects.create(name='Hidden', sensor_id=3, position=Point(-119.77, 36.77), location='outside', is_hidden=True)
        touch(self.pa_fresno, now - timedelta(minutes=10))
        touch(self.pa_kern, now - timedelta(days=3))
        # created is auto_now_add; push one monitor back a year for the deployments table
        PurpleAir.objects.filter(pk=self.pa_kern.pk).update(created=now - timedelta(days=365))

    def test_tiles(self):
        response = self.client.get(reverse('reports:network-overview'))
        assert response.status_code == 200
        assert response.context['tiles'] == {'total': 3, 'active': 1, 'sjvair': 2, 'partner': 1}

    def test_rows_by_type_and_county(self):
        response = self.client.get(reverse('reports:network-overview'))
        rows = {row['type']: row for row in response.context['rows']}
        assert rows['PurpleAir']['Fresno'] == 1
        assert rows['PurpleAir']['Kern'] == 1
        assert rows['PurpleAir']['total'] == 2
        assert rows['BAM1022']['Fresno'] == 1
        assert rows['BAM1022']['total'] == 1
        assert rows['All types']['Fresno'] == 2
        assert rows['All types']['total'] == 3

    def test_include_hidden(self):
        response = self.client.get(reverse('reports:network-overview'), {'include_hidden': '1'})
        rows = {row['type']: row for row in response.context['rows']}
        assert rows['PurpleAir']['total'] == 3
        assert response.context['tiles']['total'] == 4

    def test_deployments_are_contiguous_and_cumulative(self):
        response = self.client.get(reverse('reports:network-overview'))
        deployments = response.context['deployments']
        assert deployments[0]['new'] == 1
        assert deployments[0]['cumulative'] == 1
        assert deployments[-1]['cumulative'] == 3
        assert len(deployments) == 5  # a year ago through now spans 5 quarter buckets
        assert sum(d['new'] for d in deployments) == 3

    def test_csv_columns(self):
        response = self.client.get(reverse('reports:network-overview'), {'format': 'csv'})
        header = response.content.decode().splitlines()[0]
        assert header == 'type,Fresno,Kern,Kings,Madera,Merced,San Joaquin,Stanislaus,Tulare,total'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `RUN_TESTS camp/apps/reports/tests.py -v -k NetworkOverview`
Expected: FAIL with `NoReverseMatch` for `reports:network-overview`.

- [ ] **Step 3: Implement**

Add to `camp/apps/reports/views.py` (imports at top, class at bottom):

```python
from datetime import timedelta

from django.db.models import Count, Q
from django.db.models.functions import TruncQuarter
from django.utils import timezone


def monitor_types():
    """Concrete Monitor subclasses, sorted by class name."""
    return Monitor.get_subclasses()


def type_label(cls):
    return cls.__name__


def quarter_label(dt):
    return f'{dt.year} Q{(dt.month - 1) // 3 + 1}'


def next_quarter(dt):
    month = dt.month + 3
    year = dt.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    return dt.replace(year=year, month=month, day=1)


@register
class NetworkOverview(BaseReport):
    slug = 'network-overview'
    title = 'Network Overview'
    description = 'Monitor counts by type and county, and deployments per quarter. Hidden monitors are excluded unless requested.'
    template_name = 'admin/reports/network_overview.html'

    @property
    def include_hidden(self):
        return self.request.GET.get('include_hidden') == '1'

    def base_queryset(self):
        queryset = Monitor.objects.all()
        if not self.include_hidden:
            queryset = queryset.filter(is_hidden=False)
        return queryset

    def get_rows(self):
        counts = {}
        for cls in monitor_types():
            queryset = cls.objects.all()
            if not self.include_hidden:
                queryset = queryset.filter(is_hidden=False)
            for item in queryset.values('county').annotate(n=Count('pk')):
                counts[(type_label(cls), item['county'])] = item['n']

        rows = []
        totals = {county: 0 for county in County.names}
        for cls in monitor_types():
            label = type_label(cls)
            row = {'type': label}
            for county in County.names:
                row[county] = counts.get((label, county), 0)
                totals[county] += row[county]
            row['total'] = sum(row[county] for county in County.names)
            rows.append(row)

        rows.append({'type': 'All types', **totals, 'total': sum(totals.values())})
        return rows

    def get_tiles(self):
        cutoff = timezone.now() - timedelta(seconds=Monitor.LAST_ACTIVE_LIMIT)
        queryset = self.base_queryset()
        total = queryset.count()
        sjvair = queryset.filter(is_sjvair=True).count()
        active = queryset.with_last_entry_timestamp().filter(last_entry_timestamp__gte=cutoff).count()
        return {'total': total, 'active': active, 'sjvair': sjvair, 'partner': total - sjvair}

    def get_deployments(self):
        per_quarter = {
            item['quarter']: item['n']
            for item in (self.base_queryset()
                .annotate(quarter=TruncQuarter('created'))
                .values('quarter')
                .annotate(n=Count('pk'))
                .order_by('quarter'))
        }
        if not per_quarter:
            return []

        rows = []
        cumulative = 0
        quarter = min(per_quarter)
        last = max(max(per_quarter), timezone.now())
        while quarter <= last:
            new = per_quarter.get(quarter, 0)
            cumulative += new
            rows.append({'quarter': quarter_label(quarter), 'new': new, 'cumulative': cumulative})
            quarter = next_quarter(quarter)
        return rows

    def get_context_data(self, **kwargs):
        return {
            **super().get_context_data(**kwargs),
            'counties': County.names,
            'include_hidden': self.include_hidden,
            'tiles': self.get_tiles(),
            'deployments': self.get_deployments(),
        }
```

Note on `TruncQuarter`: it returns timezone-aware datetimes in the active timezone (Pacific, activated by `conftest.py` and in production via settings). `min(per_quarter)` is the first quarter start; `next_quarter` steps by three months on that aware datetime. Comparing `quarter <= last` against `timezone.now()` is fine because both are aware.

Note on the monitor-in-county matrix: monitors with a blank `county` (outside the SJV or with no position) are counted in `total` for the type? No: `total` sums only the county columns, so out-of-valley monitors are excluded from the matrix on purpose. The tiles count them. If that mismatch matters later, add an "Other" column.

- [ ] **Step 4: Template**

`camp/templates/admin/reports/network_overview.html`:

```django
{% extends 'admin/reports/base.html' %}
{% load humanize %}

{% block filters %}
<label><input type="checkbox" name="include_hidden" value="1" {% if include_hidden %}checked{% endif %} onchange="this.form.submit()"> Include hidden monitors</label>
{% endblock %}

{% block report %}
<div class="module">
    <table>
        <caption>Totals</caption>
        <tr>
            <th>Monitors</th><td>{{ tiles.total|intcomma }}</td>
            <th>Active (last hour)</th><td>{{ tiles.active|intcomma }}</td>
            <th>SJVAir-owned</th><td>{{ tiles.sjvair|intcomma }}</td>
            <th>Partner</th><td>{{ tiles.partner|intcomma }}</td>
        </tr>
    </table>
</div>

<div class="module">
    <table>
        <caption>Monitors by type and county</caption>
        <thead>
            <tr>
                <th>Type</th>
                {% for county in counties %}<th>{{ county }}</th>{% endfor %}
                <th>Total</th>
            </tr>
        </thead>
        <tbody>
            {% for row in rows %}
            <tr>
                <th>{{ row.type }}</th>
                {% for county in counties %}<td>{{ row|get_item:county|intcomma }}</td>{% endfor %}
                <td><strong>{{ row.total|intcomma }}</strong></td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>

<div class="module">
    <table>
        <caption>Deployments by quarter</caption>
        <thead><tr><th>Quarter</th><th>New</th><th>Cumulative</th></tr></thead>
        <tbody>
            {% for row in deployments %}
            <tr><th>{{ row.quarter }}</th><td>{{ row.new|intcomma }}</td><td>{{ row.cumulative|intcomma }}</td></tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endblock %}
```

The `get_item` filter does not exist yet. Add a template tag library `camp/apps/reports/templatetags/__init__.py` (empty) and `camp/apps/reports/templatetags/reports.py`:

```python
from django import template

register = template.Library()


@register.filter
def get_item(mapping, key):
    return mapping.get(key)
```

and add `{% load reports %}` after `{% load humanize %}` in the template above.

- [ ] **Step 5: Run tests to verify they pass**

Run: `RUN_TESTS camp/apps/reports/tests.py -v -k NetworkOverview`
Expected: all 5 PASS. If `test_deployments_are_contiguous_and_cumulative` fails on the `== 5` assertion by one, it is a quarter-boundary edge (a year ago and today straddle 4 or 5 quarter starts depending on the date). Change that assertion to `assert 4 <= len(deployments) <= 5`.

- [ ] **Step 6: Commit**

```bash
git add camp/apps/reports/views.py camp/apps/reports/tests.py \
  camp/apps/reports/templatetags/__init__.py camp/apps/reports/templatetags/reports.py \
  camp/templates/admin/reports/network_overview.html
git commit -m "feat(reports): add network overview report"
```

---

### Task 4: Fleet Health report

**Files:**
- Modify: `camp/apps/reports/views.py`
- Modify: `camp/apps/reports/tests.py`
- Create: `camp/templates/admin/reports/fleet_health.html`

**Interfaces:**
- Consumes: `monitor_types()`, `type_label()`, `touch()` test helper from Task 3.
- Produces: URL `reports:fleet-health`. Context: `rows` (per type silence buckets), `grades` (per type A/B/C/F/none), `county` (selected filter), `counties`. Query param `county=<name>`.

- [ ] **Step 1: Write the failing tests**

Append to `camp/apps/reports/tests.py`:

```python
from camp.apps.qaqc.models import HealthCheck


def give_health(monitor, score, flatline_a=None, flatline_b=None):
    check = HealthCheck.objects.create(
        monitor=monitor, hour=timezone.now().replace(minute=0, second=0, microsecond=0),
        score=score, sanity_flatline_a=flatline_a, sanity_flatline_b=flatline_b,
    )
    monitor.health = check
    monitor.save()
    return check


class FleetHealthTests(StaffClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        now = timezone.now()
        self.active = PurpleAir.objects.create(name='Active', sensor_id=1, position=Point(-119.75, 36.75), location='outside')
        self.day = PurpleAir.objects.create(name='Day', sensor_id=2, position=Point(-119.75, 36.75), location='outside')
        self.week = PurpleAir.objects.create(name='Week', sensor_id=3, position=Point(-119.0, 35.4), location='outside')
        self.long = PurpleAir.objects.create(name='Long', sensor_id=4, position=Point(-119.0, 35.4), location='outside')
        self.never = PurpleAir.objects.create(name='Never', sensor_id=5, position=Point(-119.0, 35.4), location='outside')
        self.hidden = PurpleAir.objects.create(name='Hidden', sensor_id=6, position=Point(-119.0, 35.4), location='outside', is_hidden=True)
        touch(self.active, now - timedelta(minutes=5))
        touch(self.day, now - timedelta(hours=6))
        touch(self.week, now - timedelta(days=3))
        touch(self.long, now - timedelta(days=30))
        touch(self.hidden, now - timedelta(minutes=5))
        give_health(self.active, 3)
        give_health(self.day, 1)

    def test_silence_buckets(self):
        response = self.client.get(reverse('reports:fleet-health'))
        assert response.status_code == 200
        row = {r['type']: r for r in response.context['rows']}['PurpleAir']
        assert row == {
            'type': 'PurpleAir', 'active': 1, 'silent_1d': 1, 'silent_7d': 1,
            'silent_long': 1, 'never': 1, 'hidden': 1, 'total': 6,
        }

    def test_county_filter(self):
        response = self.client.get(reverse('reports:fleet-health'), {'county': 'Fresno'})
        row = {r['type']: r for r in response.context['rows']}['PurpleAir']
        assert row['active'] == 1
        assert row['silent_1d'] == 1
        assert row['total'] == 2

    def test_grade_distribution(self):
        response = self.client.get(reverse('reports:fleet-health'))
        grades = {g['type']: g for g in response.context['grades']}
        assert grades['PurpleAir'] == {'type': 'PurpleAir', 'A': 1, 'B': 0, 'C': 1, 'F': 0, 'none': 4}
        assert 'BAM1022' not in grades
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `RUN_TESTS camp/apps/reports/tests.py -v -k FleetHealth`
Expected: FAIL with `NoReverseMatch` for `reports:fleet-health`.

- [ ] **Step 3: Implement**

Add to `camp/apps/reports/views.py`:

```python
@register
class FleetHealth(BaseReport):
    slug = 'fleet-health'
    title = 'Fleet Health'
    description = 'How recently each monitor type reported, and the current health grade distribution for dual-channel monitors.'
    template_name = 'admin/reports/fleet_health.html'

    @property
    def county(self):
        county = self.request.GET.get('county', '')
        return county if county in County.names else ''

    def scoped(self, queryset):
        if self.county:
            queryset = queryset.filter(county=self.county)
        return queryset

    def get_rows(self):
        now = timezone.now()
        hour = now - timedelta(hours=1)
        day = now - timedelta(days=1)
        week = now - timedelta(days=7)
        visible = Q(is_hidden=False)

        rows = []
        for cls in monitor_types():
            stats = self.scoped(cls.objects.with_last_entry_timestamp()).aggregate(
                active=Count('pk', filter=visible & Q(last_entry_timestamp__gte=hour)),
                silent_1d=Count('pk', filter=visible & Q(last_entry_timestamp__lt=hour, last_entry_timestamp__gte=day)),
                silent_7d=Count('pk', filter=visible & Q(last_entry_timestamp__lt=day, last_entry_timestamp__gte=week)),
                silent_long=Count('pk', filter=visible & Q(last_entry_timestamp__lt=week)),
                never=Count('pk', filter=visible & Q(last_entry_timestamp__isnull=True)),
                hidden=Count('pk', filter=Q(is_hidden=True)),
                total=Count('pk'),
            )
            rows.append({'type': type_label(cls), **stats})
        return rows

    def get_grades(self):
        eligible = Monitor.objects.get_for_health_checks()
        rows = []
        for cls in monitor_types():
            queryset = self.scoped(eligible.filter(**cls.health_check_queryset_filter()))
            if not queryset.exists():
                continue
            stats = queryset.aggregate(
                A=Count('pk', filter=Q(health__score=3)),
                B=Count('pk', filter=Q(health__score=2)),
                C=Count('pk', filter=Q(health__score=1)),
                F=Count('pk', filter=Q(health__score=0)),
                none=Count('pk', filter=Q(health__isnull=True)),
            )
            rows.append({'type': type_label(cls), **stats})
        return rows

    def get_context_data(self, **kwargs):
        return {
            **super().get_context_data(**kwargs),
            'counties': County.names,
            'county': self.county,
            'grades': self.get_grades(),
        }
```

Note: `aggregate()` with `filter=Q(last_entry_timestamp...)` on the `with_last_entry_timestamp()` subquery annotation works because Django wraps the annotated query in a subquery when an aggregate references an annotation. If Postgres complains about the annotation not being in GROUP BY, switch to `.annotate(...).values(...)` and count in Python; do not add a raw SQL fallback.

- [ ] **Step 4: Template**

`camp/templates/admin/reports/fleet_health.html`:

```django
{% extends 'admin/reports/base.html' %}
{% load humanize %}

{% block filters %}
<label>County
    <select name="county" onchange="this.form.submit()">
        <option value="">All counties</option>
        {% for name in counties %}<option value="{{ name }}" {% if name == county %}selected{% endif %}>{{ name }}</option>{% endfor %}
    </select>
</label>
{% endblock %}

{% block report %}
<div class="module">
    <table>
        <caption>Last report, by type</caption>
        <thead>
            <tr>
                <th>Type</th><th>Active (&lt;1h)</th><th>Silent 1–24h</th><th>Silent 1–7d</th>
                <th>Silent &gt;7d</th><th>Never reported</th><th>Hidden</th><th>Total</th>
            </tr>
        </thead>
        <tbody>
            {% for row in rows %}
            <tr>
                <th>{{ row.type }}</th>
                <td>{{ row.active|intcomma }}</td><td>{{ row.silent_1d|intcomma }}</td><td>{{ row.silent_7d|intcomma }}</td>
                <td>{{ row.silent_long|intcomma }}</td><td>{{ row.never|intcomma }}</td><td>{{ row.hidden|intcomma }}</td>
                <td><strong>{{ row.total|intcomma }}</strong></td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>

<div class="module">
    <table>
        <caption>Current health grade (dual-channel monitors)</caption>
        <thead><tr><th>Type</th><th>A</th><th>B</th><th>C</th><th>F</th><th>No check</th></tr></thead>
        <tbody>
            {% for row in grades %}
            <tr>
                <th>{{ row.type }}</th>
                <td>{{ row.A|intcomma }}</td><td>{{ row.B|intcomma }}</td><td>{{ row.C|intcomma }}</td>
                <td>{{ row.F|intcomma }}</td><td>{{ row.none|intcomma }}</td>
            </tr>
            {% empty %}
            <tr><td colspan="6">No health-check-eligible monitors.</td></tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endblock %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `RUN_TESTS camp/apps/reports/tests.py -v -k FleetHealth`
Expected: all 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add camp/apps/reports/views.py camp/apps/reports/tests.py camp/templates/admin/reports/fleet_health.html
git commit -m "feat(reports): add fleet health report"
```

---

### Task 5: Degraded Monitors report

**Files:**
- Modify: `camp/apps/reports/views.py`
- Modify: `camp/apps/reports/tests.py`
- Create: `camp/templates/admin/reports/degraded_monitors.html`

**Interfaces:**
- Consumes: `monitor_types()`, `type_label()`, `touch()`, `give_health()`.
- Produces: URL `reports:degraded-monitors`. Rows have keys `name, type, county, host, grade, last_seen, condition` plus non-CSV keys `admin_url`, `sort_key`. Query params `county`, `type` (monitor_type, e.g. `purpleair`), `include_hidden=1`.

- [ ] **Step 1: Write the failing tests**

Append to `camp/apps/reports/tests.py`:

```python
from camp.apps.monitors.models import Host


class DegradedMonitorsTests(StaffClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        now = timezone.now()
        host = Host.objects.create(name='Library')
        self.fine = PurpleAir.objects.create(name='Fine', sensor_id=1, position=Point(-119.75, 36.75), location='outside')
        self.grade_f = PurpleAir.objects.create(name='Grade F', sensor_id=2, position=Point(-119.75, 36.75), location='outside', host=host)
        self.grade_c = PurpleAir.objects.create(name='Grade C', sensor_id=3, position=Point(-119.75, 36.75), location='outside')
        self.flat = PurpleAir.objects.create(name='Flat', sensor_id=4, position=Point(-119.0, 35.4), location='outside')
        self.silent = PurpleAir.objects.create(name='Silent', sensor_id=5, position=Point(-119.0, 35.4), location='outside')
        self.never = BAM1022.objects.create(name='Never', position=Point(-119.0, 35.4), location='outside')
        self.hidden = PurpleAir.objects.create(name='Hidden', sensor_id=6, position=Point(-119.0, 35.4), location='outside', is_hidden=True)
        for monitor in (self.fine, self.grade_f, self.grade_c, self.flat):
            touch(monitor, now - timedelta(minutes=5))
        touch(self.silent, now - timedelta(days=3))
        give_health(self.fine, 3)
        give_health(self.grade_f, 0)
        give_health(self.grade_c, 1)
        give_health(self.flat, 3, flatline_b=False)

    def rows(self, **params):
        response = self.client.get(reverse('reports:degraded-monitors'), params)
        assert response.status_code == 200
        return response.context['rows']

    def test_lists_only_degraded_monitors_worst_first(self):
        rows = self.rows()
        assert [r['name'] for r in rows] == ['Never', 'Silent', 'Grade F', 'Grade C', 'Flat']

    def test_conditions_and_columns(self):
        rows = {r['name']: r for r in self.rows()}
        assert rows['Grade F']['condition'] == 'Grade F'
        assert rows['Grade F']['host'] == 'Library'
        assert rows['Grade F']['type'] == 'PurpleAir'
        assert rows['Grade F']['county'] == 'Fresno'
        assert rows['Flat']['condition'] == 'Flatline B'
        assert rows['Silent']['condition'] == 'Silent 3d'
        assert rows['Never']['condition'] == 'Never reported'
        assert rows['Never']['last_seen'] is None
        assert rows['Never']['type'] == 'BAM1022'
        assert rows['Never']['admin_url'] == reverse('admin:bam_bam1022_change', args=[self.never.pk])

    def test_filters(self):
        assert [r['name'] for r in self.rows(county='Fresno')] == ['Grade F', 'Grade C']
        assert [r['name'] for r in self.rows(type='bam1022')] == ['Never']
        assert 'Hidden' in [r['name'] for r in self.rows(include_hidden='1')]

    def test_csv_columns(self):
        response = self.client.get(reverse('reports:degraded-monitors'), {'format': 'csv'})
        header = response.content.decode().splitlines()[0]
        assert header == 'name,type,county,host,grade,last_seen,condition'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `RUN_TESTS camp/apps/reports/tests.py -v -k DegradedMonitors`
Expected: FAIL with `NoReverseMatch` for `reports:degraded-monitors`.

- [ ] **Step 3: Implement**

Add to `camp/apps/reports/views.py` (add `from django.urls import reverse` to the imports):

```python
@register
class DegradedMonitors(BaseReport):
    slug = 'degraded-monitors'
    title = 'Degraded Monitors'
    description = 'Monitors graded C or F, flatlined on a channel, or silent for more than 24 hours. Worst first.'
    template_name = 'admin/reports/degraded_monitors.html'
    csv_columns = ['name', 'type', 'county', 'host', 'grade', 'last_seen', 'condition']

    @property
    def include_hidden(self):
        return self.request.GET.get('include_hidden') == '1'

    @property
    def county(self):
        county = self.request.GET.get('county', '')
        return county if county in County.names else ''

    @property
    def monitor_type(self):
        wanted = self.request.GET.get('type', '')
        return wanted if wanted in {cls.monitor_type for cls in monitor_types()} else ''

    def get_csv_columns(self, rows):
        return self.csv_columns

    def get_rows(self):
        now = timezone.now()
        day = now - timedelta(days=1)
        degraded = (
            Q(health__score__lte=1)
            | Q(health__sanity_flatline_a=False)
            | Q(health__sanity_flatline_b=False)
            | Q(last_entry_timestamp__lt=day)
            | Q(last_entry_timestamp__isnull=True)
        )

        rows = []
        for cls in monitor_types():
            if self.monitor_type and cls.monitor_type != self.monitor_type:
                continue
            queryset = (cls.objects
                .with_last_entry_timestamp()
                .select_related('health', 'host')
                .filter(degraded)
            )
            if not self.include_hidden:
                queryset = queryset.filter(is_hidden=False)
            if self.county:
                queryset = queryset.filter(county=self.county)

            for monitor in queryset:
                rows.append(self.build_row(cls, monitor, now))

        rows.sort(key=lambda row: row['sort_key'])
        return rows

    def build_row(self, cls, monitor, now):
        health = monitor.health
        last_seen = monitor.last_entry_timestamp
        conditions = []
        # sort_key: lower sorts first. (0, -silence) silent, (1,) grade F, (2,) grade C, (3,) flatline only
        sort_key = (4, 0)

        if last_seen is None:
            conditions.append('Never reported')
            sort_key = (0, -float('inf'))
        elif last_seen < now - timedelta(days=1):
            silence = now - last_seen
            conditions.append(f'Silent {silence.days}d')
            sort_key = (0, -silence.total_seconds())

        if health is not None:
            if health.score == 0:
                conditions.append('Grade F')
                sort_key = min(sort_key, (1, 0))
            elif health.score == 1:
                conditions.append('Grade C')
                sort_key = min(sort_key, (2, 0))
            if health.sanity_flatline_a is False:
                conditions.append('Flatline A')
                sort_key = min(sort_key, (3, 0))
            if health.sanity_flatline_b is False:
                conditions.append('Flatline B')
                sort_key = min(sort_key, (3, 0))

        return {
            'name': monitor.name,
            'type': type_label(cls),
            'county': monitor.county,
            'host': monitor.host.name if monitor.host_id else '',
            'grade': health.grade if health is not None else '',
            'last_seen': last_seen,
            'condition': ', '.join(conditions),
            'admin_url': reverse(f'admin:{cls._meta.app_label}_{cls._meta.model_name}_change', args=[monitor.pk]),
            'sort_key': sort_key,
        }

    def get_context_data(self, **kwargs):
        return {
            **super().get_context_data(**kwargs),
            'counties': County.names,
            'county': self.county,
            'monitor_type': self.monitor_type,
            'types': [(cls.monitor_type, type_label(cls)) for cls in monitor_types()],
            'include_hidden': self.include_hidden,
        }
```

Sorting detail for the test's expected order `Never, Silent, Grade F, Grade C, Flat`: never has key `(0, -inf)`, silent 3d has `(0, -259200)`, F `(1, 0)`, C `(2, 0)`, flatline `(3, 0)`. Ties inside a bucket keep queryset order (name).

CSV: `last_seen` is a datetime; `csv.DictWriter` writes its `str()`, which is acceptable.

- [ ] **Step 4: Template**

`camp/templates/admin/reports/degraded_monitors.html`:

```django
{% extends 'admin/reports/base.html' %}

{% block filters %}
<label>County
    <select name="county" onchange="this.form.submit()">
        <option value="">All counties</option>
        {% for name in counties %}<option value="{{ name }}" {% if name == county %}selected{% endif %}>{{ name }}</option>{% endfor %}
    </select>
</label>
<label>Type
    <select name="type" onchange="this.form.submit()">
        <option value="">All types</option>
        {% for value, label in types %}<option value="{{ value }}" {% if value == monitor_type %}selected{% endif %}>{{ label }}</option>{% endfor %}
    </select>
</label>
<label><input type="checkbox" name="include_hidden" value="1" {% if include_hidden %}checked{% endif %} onchange="this.form.submit()"> Include hidden</label>
{% endblock %}

{% block report %}
<div class="module">
    <table>
        <caption>{{ rows|length }} degraded monitor{{ rows|length|pluralize }}</caption>
        <thead>
            <tr><th>Monitor</th><th>Type</th><th>County</th><th>Host</th><th>Grade</th><th>Last seen</th><th>Condition</th></tr>
        </thead>
        <tbody>
            {% for row in rows %}
            <tr>
                <th><a href="{{ row.admin_url }}">{{ row.name }}</a></th>
                <td>{{ row.type }}</td>
                <td>{{ row.county }}</td>
                <td>{{ row.host }}</td>
                <td>{{ row.grade }}</td>
                <td>{% if row.last_seen %}{{ row.last_seen|date:"Y-m-d H:i" }}{% else %}&mdash;{% endif %}</td>
                <td>{{ row.condition }}</td>
            </tr>
            {% empty %}
            <tr><td colspan="7">Nothing degraded. Nice.</td></tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endblock %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `RUN_TESTS camp/apps/reports/tests.py -v -k DegradedMonitors`
Expected: all 4 PASS.

- [ ] **Step 6: Commit**

```bash
git add camp/apps/reports/views.py camp/apps/reports/tests.py camp/templates/admin/reports/degraded_monitors.html
git commit -m "feat(reports): add degraded monitors report"
```

---

### Task 6: Coverage and Equity report

**Files:**
- Modify: `camp/apps/reports/views.py`
- Modify: `camp/apps/reports/tests.py`
- Create: `camp/templates/admin/reports/coverage.html`
- Modify: `docs/superpowers/specs/2026-09-16-admin-reports-design.md` (one sentence, see Step 3 note)

**Interfaces:**
- Consumes: `BaseReport`, `register`, `County`.
- Produces: URL `reports:coverage`. Context: `rows` (per county), `percentile_bands` (list), `ces_version` (string like `CES5 (2020)`), `radius` (int meters), `include_hidden`. Query params `radius=<meters>` (default 1000), `include_hidden=1`.

- [ ] **Step 1: Write the failing tests**

Append to `camp/apps/reports/tests.py`:

```python
class CoverageTests(StaffClientMixin, TestCase):
    fixtures = ['calenviroscreen.yaml']

    def setUp(self):
        super().setUp()
        # Inside tract 1.01 (DAC, pop 4650). Tract 1.02 (pop 3350) has no monitor.
        self.in_dac = PurpleAir.objects.create(name='In DAC', sensor_id=1, position=Point(-119.75, 36.75), location='outside')
        # Kern, outside any fixture tract.
        self.kern = PurpleAir.objects.create(name='Kern', sensor_id=2, position=Point(-119.0, 35.4), location='outside')

    def test_uses_newest_ces_version(self):
        response = self.client.get(reverse('reports:coverage'))
        assert response.status_code == 200
        assert response.context['ces_version'] == 'CES5 (2020)'

    def test_county_rows(self):
        response = self.client.get(reverse('reports:coverage'))
        rows = {row['county']: row for row in response.context['rows']}
        fresno = rows['Fresno']
        assert fresno['monitors'] == 1
        assert fresno['population'] == 8000
        assert fresno['per_10k'] == 1.25
        assert fresno['dac_tracts'] == 1
        assert fresno['dac_monitors'] == 1
        assert fresno['dac_population'] == 4650
        assert fresno['dac_population_covered'] == 4650
        assert fresno['dac_covered_pct'] == 100.0
        kern = rows['Kern']
        assert kern['monitors'] == 1
        assert kern['population'] == 0
        assert kern['per_10k'] is None
        total = rows['All counties']
        assert total['monitors'] == 2
        assert total['population'] == 8000

    def test_radius_param_changes_coverage(self):
        # A monitor in tract 1.01 is at most ~11km from tract 1.02's edge? No: tract 1.02 starts at
        # lon -119.7, the monitor is at -119.75, about 4.5 km away. A 5 km radius reaches it.
        response = self.client.get(reverse('reports:coverage'), {'radius': '5000'})
        bands = {b['band']: b for b in response.context['percentile_bands']}
        assert response.context['radius'] == 5000
        assert bands['75–100']['tracts'] == 1
        assert bands['50–75']['tracts'] == 1
        assert bands['50–75']['monitors'] == 0
        assert bands['75–100']['monitors'] == 1

    def test_percentile_bands(self):
        response = self.client.get(reverse('reports:coverage'))
        bands = {b['band']: b for b in response.context['percentile_bands']}
        assert set(bands) == {'0–25', '25–50', '50–75', '75–100'}
        assert bands['75–100'] == {'band': '75–100', 'tracts': 1, 'population': 4650, 'monitors': 1, 'per_10k': 2.15}
        assert bands['50–75'] == {'band': '50–75', 'tracts': 1, 'population': 3350, 'monitors': 0, 'per_10k': 0.0}
        assert bands['0–25']['tracts'] == 0

    def test_csv_columns(self):
        response = self.client.get(reverse('reports:coverage'), {'format': 'csv'})
        header = response.content.decode().splitlines()[0]
        assert header == 'county,monitors,population,per_10k,dac_tracts,dac_monitors,dac_population,dac_population_covered,dac_covered_pct'
```

Note on `test_radius_param_changes_coverage`: the primary assertion is that the parameter is parsed and the report still computes. The band figures do not depend on radius, which is what the assertions check; the covered-population figure is exercised in `test_county_rows` with the default radius (the monitor sits inside the DAC tract, so distance is 0).

- [ ] **Step 2: Run tests to verify they fail**

Run: `RUN_TESTS camp/apps/reports/tests.py -v -k Coverage`
Expected: FAIL with `NoReverseMatch` for `reports:coverage`.

- [ ] **Step 3: Implement**

Add to `camp/apps/reports/views.py`. New imports:

```python
from django.contrib.gis.db.models.functions import Centroid
from django.contrib.gis.measure import D
from django.db.models import Exists, OuterRef, Sum

from camp.apps.ces.models import CES4, CES5
```

Class:

```python
def per_10k(monitors, population):
    if not population:
        return None
    return round(monitors / population * 10000, 2)


@register
class Coverage(BaseReport):
    slug = 'coverage'
    title = 'Coverage and Equity'
    description = 'Monitors relative to population and disadvantaged-community (SB535 DAC) census tracts, from the newest CalEnviroScreen data loaded.'
    template_name = 'admin/reports/coverage.html'

    DEFAULT_RADIUS = 1000
    BANDS = [('0–25', 0, 25), ('25–50', 25, 50), ('50–75', 50, 75), ('75–100', 75, 100.0001)]

    @property
    def include_hidden(self):
        return self.request.GET.get('include_hidden') == '1'

    @property
    def radius(self):
        try:
            return max(0, int(self.request.GET.get('radius', self.DEFAULT_RADIUS)))
        except (TypeError, ValueError):
            return self.DEFAULT_RADIUS

    def monitors(self):
        queryset = Monitor.objects.filter(position__isnull=False)
        if not self.include_hidden:
            queryset = queryset.filter(is_hidden=False)
        return queryset

    def ces(self):
        """(model, version) for the newest CES data present, or (None, None)."""
        if not hasattr(self, '_ces'):
            self._ces = (None, None)
            for model in (CES5, CES4):
                version = (model._base_manager
                    .order_by('-boundary__version')
                    .values_list('boundary__version', flat=True)
                    .first())
                if version:
                    self._ces = (model, version)
                    break
        return self._ces

    def tracts(self):
        model, version = self.ces()
        if model is None:
            return None
        return model._base_manager.filter(boundary__version=version)

    def covered(self, tracts):
        """Annotate tracts with whether any monitor is within `radius` meters."""
        nearby = self.monitors().filter(
            position__distance_lte=(OuterRef('boundary__geometry'), D(m=self.radius))
        )
        return tracts.annotate(covered=Exists(nearby))

    def get_rows(self):
        tracts = self.tracts()
        monitor_counts = {
            item['county']: item
            for item in (self.monitors()
                .annotate(in_dac=Exists(
                    tracts.filter(dac_sb535=True, boundary__geometry__contains=OuterRef('position'))
                ) if tracts is not None else Exists(Monitor.objects.none()))
                .values('county')
                .annotate(monitors=Count('pk'), dac_monitors=Count('pk', filter=Q(in_dac=True))))
        }

        rows = []
        for county in County.names:
            counts = monitor_counts.get(county, {'monitors': 0, 'dac_monitors': 0})
            stats = {'population': 0, 'dac_tracts': 0, 'dac_population': 0, 'dac_population_covered': 0}
            if tracts is not None:
                county_tracts = (self.covered(tracts)
                    .annotate(centroid=Centroid('boundary__geometry'))
                    .filter(centroid__within=County.counties[county]))
                stats = county_tracts.aggregate(
                    population=Sum('population', default=0),
                    dac_tracts=Count('pk', filter=Q(dac_sb535=True)),
                    dac_population=Sum('population', filter=Q(dac_sb535=True), default=0),
                    dac_population_covered=Sum('population', filter=Q(dac_sb535=True, covered=True), default=0),
                )
            rows.append(self.build_row(county, counts['monitors'], counts['dac_monitors'], stats))

        rows.append(self.build_row(
            'All counties',
            sum(row['monitors'] for row in rows),
            sum(row['dac_monitors'] for row in rows),
            {key: sum(row[key] for row in rows) for key in ('population', 'dac_tracts', 'dac_population', 'dac_population_covered')},
        ))
        return rows

    def build_row(self, county, monitors, dac_monitors, stats):
        dac_population = stats['dac_population']
        covered = stats['dac_population_covered']
        return {
            'county': county,
            'monitors': monitors,
            'population': stats['population'],
            'per_10k': per_10k(monitors, stats['population']),
            'dac_tracts': stats['dac_tracts'],
            'dac_monitors': dac_monitors,
            'dac_population': dac_population,
            'dac_population_covered': covered,
            'dac_covered_pct': round(covered / dac_population * 100, 1) if dac_population else None,
        }

    def get_percentile_bands(self):
        tracts = self.tracts()
        if tracts is None:
            return []
        rows = []
        for label, low, high in self.BANDS:
            band = tracts.filter(ci_score_p__gte=low, ci_score_p__lt=high)
            stats = band.aggregate(tracts=Count('pk'), population=Sum('population', default=0))
            monitors = self.monitors().filter(
                Exists(band.filter(boundary__geometry__contains=OuterRef('position')))
            ).count()
            rows.append({
                'band': label,
                'tracts': stats['tracts'],
                'population': stats['population'],
                'monitors': monitors,
                'per_10k': per_10k(monitors, stats['population']),
            })
        return rows

    def get_context_data(self, **kwargs):
        model, version = self.ces()
        return {
            **super().get_context_data(**kwargs),
            'ces_version': f'{model.__name__} ({version})' if model else None,
            'radius': self.radius,
            'include_hidden': self.include_hidden,
            'percentile_bands': self.get_percentile_bands(),
        }
```

Implementation notes for the engineer:

- `County.counties[county]` is a `GEOSGeometry` with no SRID. Django's GIS lookups treat an SRID-less value as being in the field's SRID (4326), so `centroid__within=` works directly. If PostGIS raises a mixed-SRID error, clone and set: `geom = County.counties[county].clone(); geom.srid = 4326`.
- `distance_lte` with `D(m=...)` on a geodetic geometry field makes Django use `ST_DistanceSphere`, which accepts meters. Do not use `dwithin` here: on geographic SRIDs Django only accepts degrees for `dwithin`.
- `Sum(..., default=0)` requires Django 4.0+; we're on 5.2.
- `per_10k` for tract 1.01: 1 monitor / 4650 × 10000 = 2.1505 → `2.15`. For Fresno: 1 / 8000 × 10000 = `1.25`.
- The spec said county assignment for tracts uses county `Region` boundaries. This implementation uses `County.counties` from `camp/utils/counties.py` instead, the same in-process geometries `Monitor.save()` uses, so monitors and tracts are bucketed by the same polygons and the report does not depend on county `Region` rows being imported. Update the spec sentence under "Coverage and Equity" → "Spatial work" to say so.

- [ ] **Step 4: Template**

`camp/templates/admin/reports/coverage.html`:

```django
{% extends 'admin/reports/base.html' %}
{% load humanize %}

{% block filters %}
<label>Coverage radius (m) <input type="number" name="radius" value="{{ radius }}" min="0" step="100"></label>
<label><input type="checkbox" name="include_hidden" value="1" {% if include_hidden %}checked{% endif %}> Include hidden monitors</label>
<button type="submit">Apply</button>
{% endblock %}

{% block report %}
{% if not ces_version %}
<p class="errornote">No CalEnviroScreen data loaded. Run the CES import first.</p>
{% else %}
<p>Source: {{ ces_version }}. "Covered" means within {{ radius|intcomma }} m of a monitor.</p>
{% endif %}

<div class="module">
    <table>
        <caption>By county</caption>
        <thead>
            <tr>
                <th>County</th><th>Monitors</th><th>Population</th><th>Per 10k</th>
                <th>DAC tracts</th><th>Monitors in DAC</th><th>DAC population</th><th>DAC pop. covered</th><th>Covered %</th>
            </tr>
        </thead>
        <tbody>
            {% for row in rows %}
            <tr>
                <th>{{ row.county }}</th>
                <td>{{ row.monitors|intcomma }}</td>
                <td>{{ row.population|intcomma }}</td>
                <td>{{ row.per_10k|default_if_none:"—" }}</td>
                <td>{{ row.dac_tracts|intcomma }}</td>
                <td>{{ row.dac_monitors|intcomma }}</td>
                <td>{{ row.dac_population|intcomma }}</td>
                <td>{{ row.dac_population_covered|intcomma }}</td>
                <td>{{ row.dac_covered_pct|default_if_none:"—" }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>

<div class="module">
    <table>
        <caption>By CES score percentile</caption>
        <thead><tr><th>Percentile</th><th>Tracts</th><th>Population</th><th>Monitors</th><th>Per 10k</th></tr></thead>
        <tbody>
            {% for row in percentile_bands %}
            <tr>
                <th>{{ row.band }}</th>
                <td>{{ row.tracts|intcomma }}</td>
                <td>{{ row.population|intcomma }}</td>
                <td>{{ row.monitors|intcomma }}</td>
                <td>{{ row.per_10k|default_if_none:"—" }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endblock %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `RUN_TESTS camp/apps/reports/tests.py -v -k Coverage`
Expected: all 5 PASS.

- [ ] **Step 6: Update the spec sentence and commit**

In the spec's "Coverage and Equity" section, replace the sentence beginning "County assignment for tracts uses the county `Region` boundaries" with: "County assignment for tracts uses the in-process county polygons in `camp/utils/counties.py` (the same ones `Monitor.save()` uses), via centroid containment."

```bash
git add camp/apps/reports/views.py camp/apps/reports/tests.py camp/templates/admin/reports/coverage.html \
  docs/superpowers/specs/2026-09-16-admin-reports-design.md
git commit -m "feat(reports): add coverage and equity report"
```

---

### Task 7: Full verification

**Files:** none new.

- [ ] **Step 1: Run the reports, alerts, and admin-map suites**

Run: `RUN_TESTS camp/apps/reports/tests.py camp/apps/alerts/tests.py camp/utils/tests/test_admin_maps.py -v`
Expected: all PASS.

- [ ] **Step 2: Run the whole suite once**

Run: `RUN_TESTS camp -q`
Expected: PASS. If unrelated failures appear, check whether another session is running tests against the shared `db` container before treating them as real (see memory note on shared DB contention). Re-run the failing file alone.

- [ ] **Step 3: Smoke the pages in a browser**

Start the dev environment from the main checkout with the worktree mounted, or from the worktree if `.env` exists there, and open `/batcave/reports/`. Click through all five reports and the CSV link on each. Confirm the admin index Quick Links shows "Reports".

- [ ] **Step 4: Check the index lists reports in a sensible order**

`REPORTS` is in registration order, which is definition order in `views.py`: county stats, network overview, fleet health, degraded monitors, coverage. Reorder the class definitions to: Network Overview, Coverage and Equity, Subscription Stats by County, Fleet Health, Degraded Monitors (ED-facing first, then ops). Commit if changed:

```bash
git add camp/apps/reports/views.py
git commit -m "chore(reports): order reports index ED-facing first"
```

---

## Self-review

- **Spec coverage:** Structure (Task 1), moving county stats + redirect + Quick Links (Task 2), the four reports (Tasks 3–6), CSV on every report (Task 1 base, tested in Tasks 2, 3, 5, 6), filters `include_hidden`/`county`/`type`/`radius` (Tasks 3–6), tests per report plus index and redirect (Tasks 1–6), no caching, no JS beyond form auto-submit. Spec deviation (county polygons source) is recorded in Task 6.
- **Placeholders:** none. Every step has the code.
- **Type consistency:** `get_rows()` returns `list[dict]` everywhere; `get_csv_columns(rows)` signature matches its override in Task 5; `monitor_types()` / `type_label()` defined in Task 3 and used in Tasks 4–5; `touch()` and `give_health()` test helpers defined in Tasks 3 and 4 and used in Tasks 4–5; URL names are `reports:<slug>` throughout.
