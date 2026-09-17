# Pesticides Rollup Table and Sections API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace live aggregation over 6.5M `PesticideUse` rows with a per-section, per-month rollup table rebuilt at import time, switch the explorer's stats to it, and expose section-level totals as GeoJSON through the v2 API for the maps that follow.

**Architecture:** A new `PesticideUseRollup` model holds one row per (year, month, county, section, chemical, product, commodity) with summed pounds, acres, and application counts, rebuilt per year by a management command that `import_pur` calls. `stats.py` and the list-page annotations read the rollup; only "recent records" and the future records browser read raw rows. Two new v2 endpoints return sections by bounding box or radius, and one section's totals, all from the rollup plus the existing MTRS `Region` boundaries.

**Tech Stack:** Django 5.2, PostGIS (`django.contrib.gis`), `django-resticus` for the API, Huey for the existing warm task, pytest via `docker compose run --rm test`.

**Spec:** `docs/superpowers/specs/2026-09-16-pesticides-explorer-v2-design.md`, section "1. Rollup table and sections API". The v1 spec (`2026-09-16-pesticides-explorer-design.md`) describes the pages this keeps working.

## Global Constraints

- All commands run from the worktree root inside Docker: `docker compose run --rm test pytest <path> -q` for tests, `docker compose run --rm web python manage.py <cmd>` for management commands. `-T` is fine when a TTY is unavailable.
- Tests: `django.test.TestCase`, Django fixtures, plain `assert`. `assertNumQueries` allowed.
- New models use integer PKs; **no `SqidsField` on the rollup** (never exposed by id). `SqidsField` on other models is not a DB column: never use `sqid` in `.values()`, `.filter()` on related paths, or `order_by`.
- Field definitions: verbose name first via `_()`, no aligned `=`.
- Never `git add -A`; list files. Commit trailer exactly: `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. No other AI attribution.
- The `db` container is shared across worktrees. **Do not run `migrate` against it during this plan** except where a task says so; local rebuilds over 6.5M rows are run once, timed, and recorded.
- MTRS `Region` rows: `type='mtrs'`, `external_id` like `MDM-T13S-R14E-08`, `boundary.geometry` is a 5-point `MultiPolygon` square in SRID 4326. All 27,917 have boundaries.
- Existing explorer behavior (tests in `camp/apps/pesticides/tests/`) must stay green; assertions on exact query counts may change and are updated with the honest count.
- Timezone is `America/Los_Angeles`.

---

## File map

| File | Responsibility |
|---|---|
| `camp/apps/pesticides/models.py` | + `PesticideUseRollup` |
| `camp/apps/pesticides/migrations/0004_pesticideuserollup.py` | generated |
| `camp/apps/pesticides/rollup.py` | `rebuild_year(year)`, `rebuild_all()`, the INSERT…SELECT |
| `camp/apps/pesticides/management/commands/rebuild_pesticide_rollup.py` | CLI wrapper |
| `camp/apps/pesticides/management/commands/import_pur.py` | calls `rebuild_year` |
| `camp/apps/pesticides/stats.py` | reads the rollup; + `by_month`, `by_section` |
| `camp/apps/pesticides/views.py` | list annotations and detail aggregates read the rollup |
| `camp/apps/pesticides/tests/rollup_mixin.py` | `RollupTestMixin.setUpTestData` builds rollup rows from the fixture |
| `camp/apps/pesticides/tests/test_rollup.py` | model + rebuild tests |
| `fixtures/pesticides-explorer.yaml` | + 2 MTRS regions with boundaries; use rows get `mtrs` |
| `camp/api/v2/pesticides/sections.py` | section endpoints |
| `camp/api/v2/pesticides/urls.py` | + `sections/`, `sections/<sqid>/` |
| `camp/api/v2/pesticides/tests.py` | + section endpoint tests |
| `camp/api/v2/tests/test_openapi.py` | + documented-path assertions |

---

### Task 1: Fixture sections and the rollup model

**Files:**
- Modify: `fixtures/pesticides-explorer.yaml`
- Modify: `camp/apps/pesticides/models.py`
- Create: `camp/apps/pesticides/migrations/0004_pesticideuserollup.py` (generated)
- Test: `camp/apps/pesticides/tests/test_rollup.py`, `camp/apps/pesticides/tests/test_fixture.py`

**Interfaces:**
- Produces model `PesticideUseRollup` with fields `year, month, county, mtrs, chemical, product, commodity, lbs_chemical, lbs_product, acres_treated, applications`, `Meta.constraints` unique on the seven keys, indexes listed below, default manager `objects`.
- Produces fixture MTRS regions pk `9101` (Fresno, external_id `MDM-T14S-R20E-01`, square at lon -119.80..-119.78, lat 36.70..36.72) and `9102` (Kern, `MDM-T30S-R28E-01`, square at lon -119.05..-119.03, lat 35.35..35.37), boundaries pk `9101`/`9102`. Use rows 1, 2, 4, 6, 7, 9 get `mtrs: 9101`; rows 3, 5, 8 get `mtrs: 9102`.

- [ ] **Step 1: Extend the fixture**

Append to `fixtures/pesticides-explorer.yaml` after the two boundary entries:

```yaml
- model: regions.region
  pk: 9101
  fields:
    name: MDM-T14S-R20E-01
    slug: mdm-t14s-r20e-01
    type: mtrs
    external_id: MDM-T14S-R20E-01
    metadata: {county_code: '10'}
    boundary: 9101
- model: regions.region
  pk: 9102
  fields:
    name: MDM-T30S-R28E-01
    slug: mdm-t30s-r28e-01
    type: mtrs
    external_id: MDM-T30S-R28E-01
    metadata: {county_code: '15'}
    boundary: 9102
- model: regions.boundary
  pk: 9101
  fields:
    region: 9101
    version: 'test'
    metadata: {}
    geometry: SRID=4326;MULTIPOLYGON (((-119.80 36.70, -119.78 36.70, -119.78 36.72, -119.80 36.72, -119.80 36.70)))
- model: regions.boundary
  pk: 9102
  fields:
    region: 9102
    version: 'test'
    metadata: {}
    geometry: SRID=4326;MULTIPOLYGON (((-119.05 35.35, -119.03 35.35, -119.03 35.37, -119.05 35.37, -119.05 35.35)))
```

Then add `mtrs: 9101` to the `fields` of pesticideuse pks 1, 2, 4, 6, 7, 9 and `mtrs: 9102` to pks 3, 5, 8 (each is a one-line `fields: {...}` mapping; insert `, mtrs: 9101` after `county: 9001`, and `, mtrs: 9102` after `county: 9002`).

- [ ] **Step 2: Write failing tests**

Add to `camp/apps/pesticides/tests/test_fixture.py`:

```python
    def test_use_rows_have_sections(self):
        from camp.apps.regions.models import Region
        assert Region.objects.filter(type='mtrs').count() == 2
        assert PesticideUse.objects.filter(mtrs__isnull=True).count() == 0
        assert PesticideUse.objects.filter(mtrs_id=9101).count() == 6
```

Create `camp/apps/pesticides/tests/test_rollup.py`:

```python
import pytest
from django.db import IntegrityError, transaction
from django.test import TestCase

from camp.apps.pesticides.models import PesticideUseRollup


class RollupModelTests(TestCase):
    fixtures = ['pesticides-explorer']

    def test_key_is_unique(self):
        kwargs = dict(year=2023, month=3, county_id=9001, mtrs_id=9101, chemical_id=1, product_id=1, commodity_id=1)
        PesticideUseRollup.objects.create(lbs_chemical=1, lbs_product=1, acres_treated=1, applications=1, **kwargs)
        with transaction.atomic(), pytest.raises(IntegrityError):
            PesticideUseRollup.objects.create(lbs_chemical=2, lbs_product=2, acres_treated=2, applications=2, **kwargs)

    def test_null_dimensions_are_part_of_the_key(self):
        kwargs = dict(year=2023, month=0, county_id=9001, mtrs=None, chemical=None, product=None, commodity=None)
        PesticideUseRollup.objects.create(applications=1, **kwargs)
        with transaction.atomic(), pytest.raises(IntegrityError):
            PesticideUseRollup.objects.create(applications=2, **kwargs)

    def test_nullable_dimensions(self):
        row = PesticideUseRollup.objects.create(
            year=2023, month=0, county_id=9001, mtrs=None, chemical=None, product=None, commodity=None,
            lbs_chemical=0, lbs_product=0, acres_treated=0, applications=1,
        )
        assert row.pk
```

- [ ] **Step 3: Run to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/pesticides/tests/test_rollup.py camp/apps/pesticides/tests/test_fixture.py -q`
Expected: `ImportError: cannot import name 'PesticideUseRollup'` and the fixture test failing on the `mtrs` count until Step 1 is loaded (fixture changes take effect immediately; the model is missing).

- [ ] **Step 4: Add the model**

Append to `camp/apps/pesticides/models.py`:

```python
class PesticideUseRollup(models.Model):
    """
    Per-section, per-month rollup of PesticideUse, rebuilt per year by
    camp.apps.pesticides.rollup. Every explorer aggregate reads this instead
    of the raw records. Never exposed by id, so no sqid.
    """
    year = models.IntegerField(_('Year'))
    month = models.IntegerField(_('Month'), help_text=_('1-12, or 0 when the record has no application date'))
    county = models.ForeignKey(
        'regions.Region',
        on_delete=models.CASCADE,
        related_name='pesticide_rollups',
        verbose_name=_('County'),
        limit_choices_to={'type': Region.Type.COUNTY},
    )
    mtrs = models.ForeignKey(
        'regions.Region',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='pesticide_rollups_mtrs',
        verbose_name=_('MTRS Section'),
        limit_choices_to={'type': Region.Type.MTRS},
    )
    chemical = models.ForeignKey('pesticides.Chemical', on_delete=models.CASCADE, null=True, blank=True, related_name='rollups', verbose_name=_('pesticides.Chemical'))
    product = models.ForeignKey('pesticides.Product', on_delete=models.CASCADE, null=True, blank=True, related_name='rollups', verbose_name=_('pesticides.Product'))
    commodity = models.ForeignKey('pesticides.Commodity', on_delete=models.CASCADE, null=True, blank=True, related_name='rollups', verbose_name=_('pesticides.Commodity'))
    lbs_chemical = models.FloatField(_('Pounds of Chemical'), default=0)
    lbs_product = models.FloatField(_('Pounds of Product'), default=0)
    acres_treated = models.FloatField(_('Acres Treated'), default=0)
    applications = models.IntegerField(_('Applications'), default=0)

    class Meta:
        verbose_name = _('Pesticide Use Rollup')
        verbose_name_plural = _('Pesticide Use Rollups')
        constraints = [
            models.UniqueConstraint(
                fields=['year', 'month', 'county', 'mtrs', 'chemical', 'product', 'commodity'],
                nulls_distinct=False,
                name='pesticides_rollup_key',
            ),
        ]
        indexes = [
            models.Index(fields=['year', 'mtrs']),
            models.Index(fields=['year', 'county']),
            models.Index(fields=['year', 'chemical']),
            models.Index(fields=['year', 'product']),
            models.Index(fields=['year', 'commodity']),
            models.Index(fields=['mtrs', 'year', 'month']),
        ]

    def __str__(self):
        return f'{self.year}-{self.month:02d} / {self.mtrs_id or "no section"}'
```

`nulls_distinct=False` (Django 5.0+, PostgreSQL 15+) makes NULL dimensions compare equal so a key with no product can't duplicate. Local Postgres is 17.5 (checked); production is Heroku Postgres, also 15+.

- [ ] **Step 5: Generate the migration**

Run: `docker compose run --rm web python manage.py makemigrations pesticides -n pesticideuserollup`

If the generated file also contains the unrelated pre-existing `AlterField` on `chemical.commodities` / `product.commodities` (a drift that already exists on `main`), delete those operations from the file so it contains only `CreateModel`, `AddIndex`, and `AddConstraint`. Then `docker compose run --rm web python manage.py migrate pesticides` — this one is safe to apply locally: it creates an empty table.

- [ ] **Step 6: Run tests**

Run: `docker compose run --rm test pytest camp/apps/pesticides/tests/test_rollup.py camp/apps/pesticides/tests/test_fixture.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add fixtures/pesticides-explorer.yaml camp/apps/pesticides/models.py camp/apps/pesticides/migrations/0004_pesticideuserollup.py camp/apps/pesticides/tests/test_rollup.py camp/apps/pesticides/tests/test_fixture.py
git commit -m "feat(pesticides): add PesticideUseRollup model and fixture sections

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Rebuild function, command, and import hook

**Files:**
- Create: `camp/apps/pesticides/rollup.py`
- Create: `camp/apps/pesticides/management/commands/rebuild_pesticide_rollup.py`
- Modify: `camp/apps/pesticides/management/commands/import_pur.py`
- Create: `camp/apps/pesticides/tests/rollup_mixin.py`
- Test: `camp/apps/pesticides/tests/test_rollup.py`

**Interfaces:**
- Produces `rollup.rebuild_year(year: int) -> int` (rows written), `rollup.rebuild_all() -> dict[int, int]`, `rollup.loaded_years() -> list[int]`.
- Produces `RollupTestMixin` with a `setUpTestData` classmethod that calls `super().setUpTestData()` then `rebuild_all()`; later test classes that aggregate use `class X(RollupTestMixin, TestCase)`.
- Command: `rebuild_pesticide_rollup --year 2023 | --all`.

- [ ] **Step 1: Write failing tests**

Create `camp/apps/pesticides/tests/rollup_mixin.py`:

```python
from camp.apps.pesticides import rollup


class RollupTestMixin:
    """Build rollup rows from the loaded fixture before the class's tests run."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        rollup.rebuild_all()
```

Append to `camp/apps/pesticides/tests/test_rollup.py`:

```python
from django.core.management import call_command
from io import StringIO

from camp.apps.pesticides import rollup
from camp.apps.pesticides.models import PesticideUse
from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin


class RebuildTests(TestCase):
    fixtures = ['pesticides-explorer']

    def test_rebuild_year_sums_by_key(self):
        written = rollup.rebuild_year(2023)
        # 2023 fixture rows are all distinct keys (different month or entity), so 6 rows.
        assert written == 6
        row = PesticideUseRollup.objects.get(year=2023, chemical_id=1, commodity_id=1, county_id=9001)
        assert (row.month, row.mtrs_id, row.product_id) == (3, 9101, 1)
        assert (row.lbs_chemical, row.lbs_product, row.acres_treated, row.applications) == (100.0, 250.0, 10.0, 1)

    def test_rebuild_collapses_same_key(self):
        use = PesticideUse.objects.get(pk=1)
        use.pk = None
        use.use_no = 99
        use.lbs_chemical = 5
        use.lbs_product = 7
        use.acres_treated = 1
        use.save()   # same year, month, county, section, chemical, product, commodity as pk 1
        rollup.rebuild_year(2023)
        row = PesticideUseRollup.objects.get(year=2023, chemical_id=1, commodity_id=1, county_id=9001, month=3)
        assert (row.lbs_chemical, row.lbs_product, row.acres_treated, row.applications) == (105.0, 257.0, 11.0, 2)

    def test_rebuild_is_idempotent_and_replaces_the_year(self):
        assert rollup.rebuild_year(2023) == 6
        assert rollup.rebuild_year(2023) == 6
        assert PesticideUseRollup.objects.filter(year=2023).count() == 6
        PesticideUse.objects.filter(pk=6).delete()
        assert rollup.rebuild_year(2023) == 5

    def test_null_date_goes_to_month_zero(self):
        PesticideUse.objects.filter(pk=6).update(application_date=None)
        rollup.rebuild_year(2023)
        assert PesticideUseRollup.objects.get(year=2023, chemical_id=3).month == 0

    def test_null_section_is_kept(self):
        PesticideUse.objects.filter(pk=6).update(mtrs=None)
        rollup.rebuild_year(2023)
        row = PesticideUseRollup.objects.get(year=2023, chemical_id=3)
        assert row.mtrs_id is None
        assert row.county_id == 9001

    def test_rebuild_all_and_loaded_years(self):
        assert rollup.loaded_years() == [2022, 2023]
        assert rollup.rebuild_all() == {2022: 3, 2023: 6}

    def test_command(self):
        out = StringIO()
        call_command('rebuild_pesticide_rollup', '--all', stdout=out)
        assert PesticideUseRollup.objects.count() == 9
        assert '2023' in out.getvalue()
        call_command('rebuild_pesticide_rollup', '--year', '2022', stdout=out)
        assert PesticideUseRollup.objects.filter(year=2022).count() == 3


class MixinTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def test_mixin_builds_rows_before_tests(self):
        assert PesticideUseRollup.objects.count() == 9
```

- [ ] **Step 2: Run to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/pesticides/tests/test_rollup.py -q`
Expected: FAIL with `ImportError: cannot import name 'rollup'`.

- [ ] **Step 3: Implement the rebuild**

Create `camp/apps/pesticides/rollup.py`:

```python
"""
Rebuild PesticideUseRollup from PesticideUse, one year at a time.

A single INSERT ... SELECT ... GROUP BY inside a transaction, so readers never
see a half-built year and re-running is safe. Called at the end of import_pur
and from the rebuild_pesticide_rollup command.
"""
from django.db import connection, transaction

from camp.apps.pesticides.models import PesticideUse, PesticideUseRollup

REBUILD_SQL = """
INSERT INTO pesticides_pesticideuserollup
    (year, month, county_id, mtrs_id, chemical_id, product_id, commodity_id,
     lbs_chemical, lbs_product, acres_treated, applications)
SELECT
    year,
    COALESCE(EXTRACT(MONTH FROM application_date)::int, 0) AS month,
    county_id,
    mtrs_id,
    chemical_id,
    product_id,
    commodity_id,
    COALESCE(SUM(lbs_chemical), 0),
    COALESCE(SUM(lbs_product), 0),
    COALESCE(SUM(acres_treated), 0),
    COUNT(*)
FROM pesticides_pesticideuse
WHERE year = %s
GROUP BY year, month, county_id, mtrs_id, chemical_id, product_id, commodity_id
"""


def loaded_years():
    return list(PesticideUse.objects.order_by('year').values_list('year', flat=True).distinct())


def rebuild_year(year):
    """Replace the rollup rows for `year`. Returns the number of rows written."""
    with transaction.atomic():
        PesticideUseRollup.objects.filter(year=year).delete()
        with connection.cursor() as cursor:
            cursor.execute(REBUILD_SQL, [year])
            return cursor.rowcount


def rebuild_all():
    return {year: rebuild_year(year) for year in loaded_years()}
```

Note: `GROUP BY ... month` refers to the select alias; PostgreSQL allows grouping by output-column aliases. Table names come from the default `app_model` naming; confirm with `PesticideUseRollup._meta.db_table` if unsure.

Create `camp/apps/pesticides/management/commands/rebuild_pesticide_rollup.py`:

```python
import time

from django.core.management.base import BaseCommand, CommandError

from camp.apps.pesticides import rollup


class Command(BaseCommand):
    help = 'Rebuild the per-section, per-month PesticideUse rollup for one year or all loaded years.'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--year', type=int)
        group.add_argument('--all', action='store_true')

    def handle(self, *args, **options):
        years = rollup.loaded_years() if options['all'] else [options['year']]
        if not years:
            raise CommandError('No PesticideUse rows loaded.')
        for year in years:
            started = time.monotonic()
            written = rollup.rebuild_year(year)
            self.stdout.write(f'{year}: {written:,} rollup rows in {time.monotonic() - started:.1f}s')
```

In `import_pur.py`, replace the block after `self._import_use_records(paths, year)`:

```python
            self._import_use_records(paths, year)

            from camp.apps.pesticides import rollup, stats
            written = rollup.rebuild_year(year)
            self.stdout.write(f'Rollup: {written:,} rows for {year}')
            stats.refresh_landing_stats()
```

- [ ] **Step 4: Run tests**

Run: `docker compose run --rm test pytest camp/apps/pesticides/tests/test_rollup.py -q`
Expected: all pass. If `test_rebuild_year_sums_by_key` reports 5 instead of 6 rows, two fixture rows share a key; re-check the fixture table in the v1 plan (the 2023 rows differ by month or entity, so 6 is right).

- [ ] **Step 5: Build the real rollup once and time it**

Run: `docker compose run --rm web python manage.py rebuild_pesticide_rollup --all`
Record the per-year row counts and seconds in the task report; they go in the PR description. Then:

```bash
docker compose run --rm web python manage.py shell -c "from camp.apps.pesticides.models import PesticideUseRollup as R; print(R.objects.count())"
```

- [ ] **Step 6: Commit**

```bash
git add camp/apps/pesticides/rollup.py camp/apps/pesticides/management/commands/rebuild_pesticide_rollup.py camp/apps/pesticides/management/commands/import_pur.py camp/apps/pesticides/tests/rollup_mixin.py camp/apps/pesticides/tests/test_rollup.py
git commit -m "feat(pesticides): rebuild a per-section monthly rollup after each PUR import

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Switch `stats.py` to the rollup

**Files:**
- Modify: `camp/apps/pesticides/stats.py`
- Modify: `camp/apps/pesticides/tests/test_stats.py`

**Interfaces:**
- Every aggregate now takes a **rollup queryset** (`PesticideUseRollup.objects.filter(...)`) where it took a `PesticideUse` queryset: `by_year(rows, lbs_field)`, `by_county(rows, year, lbs_field)`, `year_totals(rows, year, lbs_field)`, `top_related(rows, year, field, lbs_field, limit)`. Return shapes unchanged. `applications` is `Sum('applications')`.
- `recent_uses(uses, limit)` still takes a `PesticideUse` queryset.
- New: `by_month(rows, year, lbs_field='lbs_chemical') -> list[dict]` with exactly twelve entries `{month: 1..12, lbs, acres, applications}` (zeros filled), and `by_section(rows, year, lbs_field='lbs_chemical') -> list[dict]` with `{mtrs_id, lbs, acres, applications}` ordered by lbs desc.
- `latest_year()`, `available_years()`, `years_loaded()` read the rollup too (`PesticideUseRollup`), so an un-rebuilt year is invisible to the explorer until its rollup exists.
- `landing_stats()` reads the rollup; `refresh_landing_stats()` unchanged in behavior.

- [ ] **Step 1: Update the stats tests**

In `camp/apps/pesticides/tests/test_stats.py`:
- Add `from camp.apps.pesticides.models import PesticideUseRollup` and `from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin`.
- Change `class StatsTests(TestCase)` to `class StatsTests(RollupTestMixin, TestCase)`.
- Replace every `PesticideUse.objects.filter(chemical_id=1)` / `product_id=1` / `.all()` passed to `by_year`, `by_county`, `year_totals`, `top_related` with `PesticideUseRollup.objects.filter(...)` / `.all()`. `recent_uses` keeps `PesticideUse`.
- `test_latest_year_is_cached`: after `PesticideUse.objects.all().delete()` also `PesticideUseRollup.objects.all().delete()`; expected values unchanged.
- `test_top_related_ignores_rows_with_unknown_pounds` and the two cache tests that create a `PesticideUse`: after creating the use row, call `rollup.rebuild_year(2023)` (import `rollup`) so the rollup reflects it. In the "ignores unknown pounds" test the rebuilt rollup row has `lbs_chemical = 0`, so the assertion changes to: the confidential chemical is present but **last** (`[...][-1].obj.name == 'AI IS CONFIDENTIAL'`) — zero-pound rows rank last, they are no longer null. Update the docstring comment accordingly.
- `test_landing_stats_empty_db`: delete rollup rows too.
- Add:

```python
    def test_by_month_fills_twelve(self):
        rows = stats.by_month(PesticideUseRollup.objects.filter(chemical_id=1), 2023)
        assert [r['month'] for r in rows] == list(range(1, 13))
        assert [r['lbs'] for r in rows][2:5] == [100.0, 50.0, 30.0]   # Mar, Apr, May
        assert sum(r['applications'] for r in rows) == 3

    def test_by_section(self):
        rows = stats.by_section(PesticideUseRollup.objects.filter(chemical_id=1), 2023)
        assert [(r['mtrs_id'], r['lbs'], r['applications']) for r in rows] == [(9101, 150.0, 2), (9102, 30.0, 1)]
```

- [ ] **Step 2: Run to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/pesticides/tests/test_stats.py -q`
Expected: failures on `by_month`/`by_section` (missing) and on `applications` counts (Count('id') over rollup rows is wrong).

- [ ] **Step 3: Implement**

In `stats.py`:
- Import `PesticideUseRollup`.
- `_totals(lbs_field)` becomes `{'lbs': Sum(lbs_field), 'acres': Sum('acres_treated'), 'applications': Sum('applications')}`.
- `year_totals`: `applications=Sum('applications')`, `counties=Count('county', distinct=True)`.
- `latest_year`, `available_years`, `years_loaded`: query `PesticideUseRollup` instead of `PesticideUse`.
- `top_related`: drop the `lbs_field__isnull=False` filter (rollup sums are never null); keep `field__isnull=False`; `model = PesticideUseRollup._meta.get_field(field).related_model`.
- `_top_chemicals_of_concern` fallback: `PesticideUseRollup.objects.filter(chemical__in=...)`.
- `_build_landing_stats`: `uses = PesticideUseRollup.objects.all()`; the year aggregate uses `Sum('applications')` for applications and the three distinct counts unchanged.
- Add:

```python
def by_month(rows, year, lbs_field='lbs_chemical'):
    """Twelve entries, one per month, zero-filled. Month 0 (undated) is folded into the totals elsewhere, not shown here."""
    found = {
        row['month']: row
        for row in rows.filter(year=year, month__gte=1).values('month').annotate(**_totals(lbs_field))
    }
    return [
        {
            'month': m,
            'lbs': (found.get(m) or {}).get('lbs') or 0,
            'acres': (found.get(m) or {}).get('acres') or 0,
            'applications': (found.get(m) or {}).get('applications') or 0,
        }
        for m in range(1, 13)
    ]


def by_section(rows, year, lbs_field='lbs_chemical'):
    return [
        {'mtrs_id': r['mtrs'], 'lbs': r['lbs'] or 0, 'acres': r['acres'] or 0, 'applications': r['applications'] or 0}
        for r in rows.filter(year=year, mtrs__isnull=False).values('mtrs').annotate(**_totals(lbs_field)).order_by(F('lbs').desc(nulls_last=True), 'mtrs')
    ]
```

Update the module docstring: the rollup is now the source; remove the "seam" sentence.

- [ ] **Step 4: Run tests**

Run: `docker compose run --rm test pytest camp/apps/pesticides/tests/test_stats.py -q`
Expected: all pass. The views tests will now fail (they still pass `PesticideUse` querysets); that's Task 4.

- [ ] **Step 5: Commit**

```bash
git add camp/apps/pesticides/stats.py camp/apps/pesticides/tests/test_stats.py
git commit -m "feat(pesticides): read explorer aggregates from the rollup

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Switch views to the rollup

**Files:**
- Modify: `camp/apps/pesticides/views.py`
- Modify: `camp/apps/pesticides/tests/test_views.py`, `camp/apps/pesticides/tests/test_maps.py` (mixin only)

**Interfaces:**
- `lbs_subquery(field, year, lbs_field)` and the commodity `chemical_count` subquery read `PesticideUseRollup`.
- `related_pks(field, obj, target)` reads `PesticideUseRollup`.
- `ExplorerDetailMixin.get_rollup()` returns `PesticideUseRollup.objects.filter(**{self.use_field: self.object})`; `get_uses()` still returns raw rows for `recent_uses`.
- Detail context gains `by_month` (twelve rows) for the future month chart; nothing renders it yet.

- [ ] **Step 1: Update the view tests**

In `test_views.py`: import `RollupTestMixin` and make every test class that reads aggregates (`ChemicalListTests`, `ProductListTests`, `CommodityListTests`, the three `*DetailTests`, `HomeTests`) inherit `RollupTestMixin, TestCase`. Tests that create `PesticideUse` rows or `ProductChemical` rows to exercise annotations must call `rollup.rebuild_all()` afterwards (search for `PesticideUse.objects.create` and `ProductChemical.objects.create` in the file; `ProductChemical` ones don't need a rebuild since counts read `ProductChemical` directly). Add to `ChemicalDetailTests`:

```python
    def test_by_month_in_context(self):
        ctx = self.client.get(self.chemical.get_absolute_url()).context
        assert len(ctx['by_month']) == 12
        assert ctx['by_month'][2]['lbs'] == 100.0
```

Leave `test_query_ceiling` in place; update the number to the honest count after Step 3 and adjust its comment.

In `test_maps.py`, `CountyMapTests` and `CountyMapLabelTests` don't aggregate; no change.

- [ ] **Step 2: Run to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/pesticides/tests/test_views.py -q`
Expected: failures on lbs annotations (they read `PesticideUse`), detail totals (`Count('id')` over rollup), and the missing `by_month`.

- [ ] **Step 3: Implement**

In `views.py`:
- Import `PesticideUseRollup`.
- `lbs_subquery`: `PesticideUseRollup.objects.filter(**{field: OuterRef('pk')}, year=year).values(field).annotate(total=Sum(lbs_field)).values('total')`.
- `related_pks`: `PesticideUseRollup.objects.filter(**{field: obj}).values(target)`.
- `CommodityList.annotate_queryset`: the `chemical_count` subquery reads `PesticideUseRollup` (`Count('chemical', distinct=True)` is still right there).
- `ExplorerDetailMixin`: add `get_rollup()`; in `get_context_data` use `rows = self.get_rollup()` for `year_totals`, `by_year`, `by_county`, `get_related`, and `stats.by_month(rows, year, self.lbs_field)`; keep `recent_uses=stats.recent_uses(self.get_uses().filter(year=year))`. Each `get_related` implementation switches `uses = self.get_uses()` to `rows = self.get_rollup()` for its `top_related` calls.

- [ ] **Step 4: Run tests and measure**

Run: `docker compose run --rm test pytest camp/apps/pesticides/ -q`
Expected: all pass after updating `test_query_ceiling` to the honest count.

Then, against the real rollup (Task 2 Step 5 built it) with the worktree server on port 8001:

```bash
for u in "chemicals/" "chemicals/?sort=-lbs&page=2" "products/?sort=-lbs" "commodities/" "?year=2022"; do
  curl -s -o /dev/null -w "$u %{http_code} %{time_total}s\n" "http://localhost:8001/tools/pesticides/$u"
done
```

Record the timings in the report; the spec's acceptance is "well under a second".

- [ ] **Step 5: Commit**

```bash
git add camp/apps/pesticides/views.py camp/apps/pesticides/tests/test_views.py
git commit -m "feat(pesticides): list and detail pages aggregate from the rollup

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Sections API

**Files:**
- Create: `camp/api/v2/pesticides/sections.py`
- Modify: `camp/api/v2/pesticides/urls.py`
- Test: `camp/api/v2/pesticides/tests.py`, `camp/api/v2/tests/test_openapi.py`

**Interfaces:**
- `GET /api/2.0/pesticides/sections/` → GeoJSON `FeatureCollection`. Params: `bbox=west,south,east,north` **or** `lat`,`lng`,`radius` (miles; allowed 1, 3, 5); `year` (default latest), `month` (1–12), `chemical` (chem code), `product` (prodno), `commodity` (site code), `county` (slug). Feature `id` = section sqid; `properties = {id, mtrs, county, lbs_chemical, lbs_product, acres_treated, applications}`. Sections with no rollup rows for the filter are included with zeros so the map can outline them. Cap: more than 2,500 sections in the bbox → `400 {"error": "bbox too large; zoom in"}`.
- `GET /api/2.0/pesticides/sections/<sqid>/` → `{id, mtrs, county, geometry, years: [{year, lbs_chemical, lbs_product, acres_treated, applications}], months: [{month, ...}] (for `year` param, default latest), top_chemicals, top_products, top_commodities: [{id, name, lbs}] (top 5 each for the year)}`.
- Both cached 1 hour via `CachedEndpointMixin` from `camp/utils/views.py` (keyed on class + kwargs + querystring; supports `?_cc=1` to clear).

- [ ] **Step 1: Write failing tests**

Append to `camp/api/v2/pesticides/tests.py` (it already has `make_county`, `make_chemical`, etc.; these tests use the fixture instead):

```python
from camp.apps.pesticides import rollup
from camp.apps.pesticides.models import PesticideUseRollup
from camp.apps.regions.models import Region


class SectionEndpointTests(TestCase):
    fixtures = ['pesticides-explorer']

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        rollup.rebuild_all()

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.url = reverse('api:v2:pesticides:section-list')

    def test_bbox_returns_geojson_with_totals(self):
        response = self.client.get(self.url, {'bbox': '-119.9,36.6,-119.7,36.8', 'year': 2023})
        assert response.status_code == 200
        data = response.json()
        assert data['type'] == 'FeatureCollection'
        assert len(data['features']) == 1
        feature = data['features'][0]
        assert feature['id'] == Region.objects.get(pk=9101).sqid
        assert feature['geometry']['type'] == 'MultiPolygon'
        assert feature['properties']['mtrs'] == 'MDM-T14S-R20E-01'
        assert feature['properties']['county'] == 'Fresno County'
        # 2023 in section 9101: uses 1, 2, 4, 6 = 100 + 50 + 20 + 500 lbs, 4 applications
        assert feature['properties']['lbs_chemical'] == 670.0
        assert feature['properties']['applications'] == 4

    def test_bbox_includes_empty_sections_with_zeros(self):
        response = self.client.get(self.url, {'bbox': '-119.9,36.6,-119.7,36.8', 'year': 2022, 'chemical': 253})
        feature = response.json()['features'][0]
        assert feature['properties']['lbs_chemical'] == 0
        assert feature['properties']['applications'] == 0

    def test_filters(self):
        response = self.client.get(self.url, {'bbox': '-119.9,36.6,-119.7,36.8', 'year': 2023, 'chemical': 1855})
        assert response.json()['features'][0]['properties']['lbs_chemical'] == 150.0
        response = self.client.get(self.url, {'bbox': '-119.9,36.6,-119.7,36.8', 'year': 2023, 'month': 8})
        assert response.json()['features'][0]['properties']['lbs_chemical'] == 500.0
        response = self.client.get(self.url, {'bbox': '-119.9,36.6,-119.7,36.8', 'year': 2023, 'commodity': '3001'})
        assert response.json()['features'][0]['properties']['lbs_chemical'] == 120.0

    def test_radius(self):
        response = self.client.get(self.url, {'lat': 35.36, 'lng': -119.04, 'radius': 1, 'year': 2023})
        data = response.json()
        assert [f['properties']['mtrs'] for f in data['features']] == ['MDM-T30S-R28E-01']
        assert data['features'][0]['properties']['lbs_chemical'] == 70.0

    def test_radius_must_be_allowed_value(self):
        assert self.client.get(self.url, {'lat': 35.36, 'lng': -119.04, 'radius': 2}).status_code == 400

    def test_requires_bbox_or_point(self):
        assert self.client.get(self.url, {'year': 2023}).status_code == 400

    def test_bbox_cap(self):
        from camp.api.v2.pesticides import sections
        old = sections.MAX_SECTIONS
        sections.MAX_SECTIONS = 1
        try:
            response = self.client.get(self.url, {'bbox': '-120,35,-118,37', 'year': 2023})
        finally:
            sections.MAX_SECTIONS = old
        assert response.status_code == 400
        assert 'zoom' in response.json()['error']

    def test_default_year_is_latest(self):
        response = self.client.get(self.url, {'bbox': '-119.9,36.6,-119.7,36.8'})
        assert response.json()['year'] == 2023

    def test_cached(self):
        self.client.get(self.url, {'bbox': '-119.9,36.6,-119.7,36.8', 'year': 2023})
        PesticideUseRollup.objects.all().delete()
        response = self.client.get(self.url, {'bbox': '-119.9,36.6,-119.7,36.8', 'year': 2023})
        assert response.json()['features'][0]['properties']['applications'] == 4

    def test_detail(self):
        section = Region.objects.get(pk=9101)
        response = self.client.get(reverse('api:v2:pesticides:section-detail', kwargs={'section_id': section.sqid}))
        assert response.status_code == 200
        data = response.json()
        assert data['mtrs'] == 'MDM-T14S-R20E-01'
        assert data['geometry']['type'] == 'MultiPolygon'
        assert [(y['year'], y['lbs_chemical'], y['applications']) for y in data['years']] == [(2023, 670.0, 4), (2022, 480.0, 2)]
        assert len(data['months']) == 12 and data['months'][7]['lbs_chemical'] == 500.0
        assert [c['name'] for c in data['top_chemicals']] == ['SULFUR', 'GLYPHOSATE', 'CHLORPYRIFOS']
        assert data['top_commodities'][0]['name'] == 'GRAPE'

    def test_detail_404(self):
        assert self.client.get(reverse('api:v2:pesticides:section-detail', kwargs={'section_id': 'nope'})).status_code == 404
```

And in `camp/api/v2/tests/test_openapi.py`, inside `test_pesticides_endpoints_are_documented`, add:

```python
        assert any('pesticides' in p and p.endswith('sections/') for p in self.paths)
        assert any('pesticides' in p and 'sections/{' in p for p in self.paths)
```

- [ ] **Step 2: Run to verify they fail**

Run: `docker compose run --rm test pytest camp/api/v2/pesticides/tests.py -k Section -q`
Expected: `NoReverseMatch` for `section-list`.

- [ ] **Step 3: Implement**

Create `camp/api/v2/pesticides/sections.py`:

```python
"""
Section-level (MTRS, one square mile) pesticide use for the explorer maps.
Totals come from PesticideUseRollup; geometry from the MTRS Region boundaries.
"""
import json

from django.contrib.gis.geos import Point, Polygon
from django.contrib.gis.measure import D
from django.db.models import Sum
from django.shortcuts import get_object_or_404

from resticus import generics, http

from camp.apps.pesticides import stats
from camp.apps.pesticides.models import Chemical, Commodity, PesticideUseRollup, Product
from camp.apps.regions.models import Region
from camp.utils.views import CachedEndpointMixin

MAX_SECTIONS = 2500
RADII = (1, 3, 5)
TOTALS = {
    'lbs_chemical': Sum('lbs_chemical'),
    'lbs_product': Sum('lbs_product'),
    'acres_treated': Sum('acres_treated'),
    'applications': Sum('applications'),
}
ZERO = {'lbs_chemical': 0, 'lbs_product': 0, 'acres_treated': 0, 'applications': 0}


def bad_request(message):
    # Returned through CachedEndpointMixin, which caches it for the same bad
    # querystring; harmless, since the same params always produce the same error.
    return http.Http400({'error': message})


def apply_filters(rows, params):
    """Entity/county/month filters shared by both endpoints. Returns (rows, error)."""
    if params.get('month'):
        try:
            month = int(params['month'])
        except ValueError:
            return rows, 'month must be 1-12'
        if not 1 <= month <= 12:
            return rows, 'month must be 1-12'
        rows = rows.filter(month=month)
    lookups = {
        'chemical': ('chemical__chem_code', int),
        'product': ('product__prodno', int),
        'commodity': ('commodity__site_code', str),
        'county': ('county__slug', str),
    }
    for param, (lookup, cast) in lookups.items():
        value = params.get(param)
        if value:
            try:
                rows = rows.filter(**{lookup: cast(value)})
            except ValueError:
                return rows, f'{param} is invalid'
    return rows, None


def parse_year(params):
    year = stats.resolve_year(params.get('year'))
    return year


class SectionList(CachedEndpointMixin, generics.Endpoint):
    """
    MTRS sections with pesticide-use totals, as GeoJSON.

    Give either `bbox=west,south,east,north` or `lat`, `lng`, `radius` (miles: 1, 3, or 5).
    Filters: `year` (default latest), `month`, `chemical` (chem code), `product`
    (prodno), `commodity` (site code), `county` (slug).
    """
    cache_timeout = 60 * 60

    def get_sections(self, params):
        sections = Region.objects.filter(type=Region.Type.MTRS, boundary__isnull=False).select_related('boundary')
        if params.get('bbox'):
            try:
                west, south, east, north = (float(v) for v in params['bbox'].split(','))
            except ValueError:
                return None, 'bbox must be west,south,east,north'
            if not (west < east and south < north):
                return None, 'bbox must be west,south,east,north'
            return sections.filter(boundary__geometry__bboverlaps=Polygon.from_bbox((west, south, east, north))), None
        if params.get('lat') and params.get('lng'):
            try:
                lat, lng = float(params['lat']), float(params['lng'])
                radius = int(params.get('radius', 1))
            except ValueError:
                return None, 'lat, lng, and radius must be numbers'
            if radius not in RADII:
                return None, f'radius must be one of {", ".join(str(r) for r in RADII)}'
            point = Point(lng, lat, srid=4326)
            return sections.filter(boundary__geometry__distance_lte=(point, D(mi=radius))), None
        return None, 'give bbox=west,south,east,north or lat, lng, and radius'

    def get(self, request):
        params = request.GET
        sections, error = self.get_sections(params)
        if error:
            return bad_request(error)
        if sections.count() > MAX_SECTIONS:
            return bad_request('bbox too large; zoom in')
        year = parse_year(params)

        rows = PesticideUseRollup.objects.filter(year=year, mtrs__in=sections)
        rows, error = apply_filters(rows, params)
        if error:
            return bad_request(error)
        totals = {r['mtrs']: r for r in rows.values('mtrs').annotate(**TOTALS)}

        features = []
        for section in sections.order_by('external_id'):
            t = totals.get(section.pk, ZERO)
            features.append({
                'type': 'Feature',
                'id': section.sqid,
                'geometry': json.loads(section.boundary.geometry.geojson),
                'properties': {
                    'id': section.sqid,
                    'mtrs': section.external_id,
                    'county': (section.metadata or {}).get('county_name') or county_name_for(section),
                    'lbs_chemical': t['lbs_chemical'] or 0,
                    'lbs_product': t['lbs_product'] or 0,
                    'acres_treated': t['acres_treated'] or 0,
                    'applications': t['applications'] or 0,
                },
            })
        # A plain dict: CachedEndpointMixin caches it and wraps it in Http200.
        return {'type': 'FeatureCollection', 'year': year, 'features': features}
```

County name per section: MTRS regions don't store their county. Resolve it once per response from the rollup (`rows.values('mtrs', 'county__name')`) rather than spatially; sections with no rollup rows in the year get `null`. Implement `county_name_for` as a lookup into a dict built before the loop (`{r['mtrs']: r['county__name'] for r in PesticideUseRollup.objects.filter(mtrs__in=sections).values('mtrs', 'county__name').distinct()}`) and drop the `metadata` branch; the sketch above shows intent, the implementation should build the dict once.

Detail endpoint, same file:

```python
class SectionDetail(CachedEndpointMixin, generics.Endpoint):
    """One MTRS section: geometry, totals by year and by month, and top chemicals, products, and commodities for `year` (default latest)."""
    cache_timeout = 60 * 60

    def get(self, request, section_id):
        section = get_object_or_404(
            Region.objects.filter(type=Region.Type.MTRS).select_related('boundary'), sqid=section_id,
        )
        year = parse_year(request.GET)
        rows = PesticideUseRollup.objects.filter(mtrs=section)
        years = list(rows.values('year').annotate(**TOTALS).order_by('-year'))
        months = stats.by_month(rows, year) if year else []
        county = rows.values_list('county__name', flat=True).first()

        def top(field, model, lbs_field='lbs_chemical', limit=5):
            related = stats.top_related(rows, year, field, lbs_field=lbs_field, limit=limit) if year else []
            return [{'id': r.obj.sqid, 'name': r.obj.name, 'lbs': r.lbs} for r in related]

        return {
            'id': section.sqid,
            'mtrs': section.external_id,
            'county': county,
            'year': year,
            'geometry': json.loads(section.boundary.geometry.geojson) if section.boundary else None,
            'years': years,
            'months': [
                {'month': m['month'], 'lbs_chemical': m['lbs'], 'acres_treated': m['acres'], 'applications': m['applications']}
                for m in months
            ],
            'top_chemicals': top('chemical', Chemical),
            'top_products': top('product', Product, lbs_field='lbs_product'),
            'top_commodities': top('commodity', Commodity),
        }
```

`CachedEndpointMixin.get` (camp/utils/views.py) calls `super().get(...)`, caches whatever it returns for `cache_timeout` seconds keyed on class + kwargs + querystring, and wraps a non-HttpResponse return value in resticus `Http200` (JSON). So the endpoints return plain dicts on success and `http.Http400(...)` on error, and inherit `?_cc=1` / `?_warm=1` for free. The MRO must be `(CachedEndpointMixin, generics.Endpoint)` so the mixin's `get` runs first.

`camp/api/v2/pesticides/urls.py`, add:

```python
    path('sections/', sections.SectionList.as_view(), name='section-list'),
    path('sections/<str:section_id>/', sections.SectionDetail.as_view(), name='section-detail'),
```

with `from . import endpoints, sections`.

- [ ] **Step 4: Run tests**

Run: `docker compose run --rm test pytest camp/api/v2/pesticides/tests.py camp/api/v2/tests/test_openapi.py -q`
Expected: all pass. If `test_radius` returns both sections, the `distance_lte` lookup is being evaluated in degrees; switch to `boundary__geometry__dwithin=(point, radius_in_degrees)` only as a last resort — first confirm the field is geodetic (SRID 4326) and PostGIS is using `ST_DistanceSphere`, which `distance_lte` selects for geographic SRIDs in Django's PostGIS backend.

- [ ] **Step 5: Try it against real data and time it**

With the worktree server on 8001:

```bash
curl -s -o /dev/null -w '%{http_code} %{time_total}s\n' 'http://localhost:8001/api/2.0/pesticides/sections/?bbox=-119.9,36.6,-119.6,36.9&year=2023'
curl -s 'http://localhost:8001/api/2.0/pesticides/sections/?bbox=-119.9,36.6,-119.6,36.9&year=2023' | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d['features']), max(f['properties']['lbs_chemical'] for f in d['features']))"
curl -s -o /dev/null -w '%{http_code} %{time_total}s\n' 'http://localhost:8001/api/2.0/pesticides/sections/?lat=36.74&lng=-119.79&radius=3&year=2023'
curl -s -o /dev/null -w '%{http_code} %{time_total}s\n' 'http://localhost:8001/api/2.0/pesticides/sections/?bbox=-121,35,-118,38&year=2023'
```

The last should be a fast 400. Record counts and timings (cold and warm) in the report.

- [ ] **Step 6: Commit**

```bash
git add camp/api/v2/pesticides/sections.py camp/api/v2/pesticides/urls.py camp/api/v2/pesticides/tests.py camp/api/v2/tests/test_openapi.py
git commit -m "feat(api): add pesticide section endpoints backed by the rollup

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Wrap up

- [ ] **Step 1: Full suite**

Run: `docker compose run --rm test pytest -q`. Shared DB: re-run a failing unrelated file once before treating it as real.

- [ ] **Step 2: Report for the PR description**

Collect from the task reports: rollup row counts and rebuild seconds per year; list-page timings before (v1 PR: 15s/8s/7.5s) and after; sections endpoint timings; the note that `rebuild_pesticide_rollup --all` must be run once on each environment after deploy (it's a one-off dyno command, like `cleanup_vozbox_pm`), and that `import_pur` keeps it current from then on. Also note the two migrations on this branch (`0003` indexes, `0004` rollup) and that `0004` is cheap (empty table) while `0003` builds three indexes over the raw table.

- [ ] **Step 3: Hand off**

The branch stays local until the user says otherwise (they are testing locally before a PR). Do not push.
