# Pesticides Data Explorer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A public, server-rendered explorer at `/tools/pesticides/` for browsing pesticide chemicals, products, and commodities, cross-linked to each other and to confirmed (PUR) and planned (SprayDays) applications by county.

**Architecture:** New `vanilla` views, URL conf, forms, template tags, a `stats.py` aggregate module, and a `maps.py` county-choropleth module inside the existing `camp.apps.pesticides` app; Bulma templates under `camp/templates/pesticides/`. No new models. Aggregates are computed live over `PesticideUse` (accepted risk; summary table is the future fix). Landing page numbers and simplified county geometries are cached 24h. Maps reuse `camp.utils.leaflet.LeafletMap` (merged to main in PR #271).

**Tech Stack:** Django 5.2, PostGIS, `django-vanilla-views`, `django_sqids`, Postgres full-text search (`django.contrib.postgres.search`), Bulma 0.9 via the existing sass build, Font Awesome kit already on `page.html`, Leaflet via `camp/utils/leaflet.py` and the static assets under `js/admin/leaflet/`.

**Spec:** `docs/superpowers/specs/2026-09-16-pesticides-explorer-design.md`

## Global Constraints

- All commands run inside Docker from the worktree root: `docker compose run --rm test pytest <path> -v` for tests, `docker compose run --rm web python manage.py <cmd>` for management commands.
- Tests: `django.test.TestCase`, Django fixtures, plain `assert` statements, `pytest.raises` for exceptions. Never `self.assertFoo()` except `assertNumQueries` (context manager, no plain-assert equivalent) and `assertTemplateUsed`.
- Field definitions: verbose name is the first positional arg via `_()`, no aligned `=` signs.
- Never `git add -A`; list files explicitly.
- No AI-authorship attribution anywhere. Commit messages carry no co-author trailer.
- The DB container is shared across worktrees; an unrelated-looking full-suite failure may be contention from another session. Re-run before treating as real.
- Timezone is `America/Los_Angeles`.
- Public identifiers are `sqid`; never expose integer PKs in URLs.
- The `SqidsField` is not a DB column: it cannot be used in `.values()`, `.filter()` on related paths, or `order_by`. Filter by `sqid=<value>` on the model's own manager only (django_sqids supports that), and fetch related objects via `in_bulk` to read their `sqid`.
- URL namespace for the explorer is `pesticides`; the API namespace chain is `api:v2:pesticides`.

---

## File map

| File | Responsibility |
|---|---|
| `camp/apps/pesticides/tests/__init__.py` | test package |
| `camp/apps/pesticides/tests/test_spraydays.py` | existing `tests.py`, moved verbatim |
| `camp/apps/pesticides/tests/test_models.py` | classification props, `get_absolute_url` |
| `camp/apps/pesticides/tests/test_querysets.py` | `.search()` |
| `camp/apps/pesticides/tests/test_stats.py` | aggregate helpers |
| `camp/apps/pesticides/tests/test_views.py` | list, detail, redirect, home, nav |
| `fixtures/pesticides-explorer.yaml` | shared test fixture |
| `camp/apps/pesticides/models.py` | + properties, `get_absolute_url` |
| `camp/apps/pesticides/querysets.py` | + `search()` on the three querysets |
| `camp/apps/pesticides/stats.py` | `latest_year`, `by_year`, `by_county`, `top_related`, `recent_uses`, `upcoming_notices`, `upcoming_by_county`, `landing_stats`, `years_loaded`, `notice_window` |
| `camp/apps/pesticides/maps.py` | `county_geometries`, `county_map` |
| `camp/apps/pesticides/tests/test_maps.py` | county map |
| `camp/apps/pesticides/forms.py` | `ChemicalFilterForm`, `ProductFilterForm`, `CommodityFilterForm` |
| `camp/apps/pesticides/views.py` | `Home`, list views, detail views, redirect views |
| `camp/apps/pesticides/urls.py` | explorer URL conf |
| `camp/apps/pesticides/templatetags/__init__.py`, `pesticides_explorer.py` | `qs_replace`, `sort_link`, `lbs` filter |
| `camp/urls.py` | mount at `tools/pesticides/` |
| `camp/templates/pesticides/*.html` | templates (see tasks) |
| `camp/templates/page.html` | Data Tools dropdown + footer link |
| `assets/sass/sjvair/pages/pesticides.sass`, `assets/sass/style.sass` | explorer styles |

---

### Task 1: Test package and shared fixture

**Files:**
- Move: `camp/apps/pesticides/tests.py` → `camp/apps/pesticides/tests/test_spraydays.py`
- Create: `camp/apps/pesticides/tests/__init__.py`
- Create: `fixtures/pesticides-explorer.yaml`
- Create: `camp/apps/pesticides/tests/test_fixture.py`

**Interfaces:**
- Produces: fixture name `pesticides-explorer` with the objects below. Every later test module uses `fixtures = ['pesticides-explorer']`.

Fixture contents (PKs are fixed so tests can reference them):

| Model | pk | Key fields |
|---|---|---|
| regions.region | 9001 | Fresno County, slug `fresno`, type `county`, external_id `06019`, metadata `{ca_county_code: '10'}` |
| regions.region | 9002 | Kern County, slug `kern`, type `county`, external_id `06029`, metadata `{ca_county_code: '15'}` |
| regions.boundary | 9001, 9002 | one square MultiPolygon per county, and each region's `boundary` FK points at its square |
| pesticides.chemical | 1 | GLYPHOSATE, chem_code 1855, cas `1071-83-6`, iarc `2A`, categories `[carcinogen]` |
| pesticides.chemical | 2 | CHLORPYRIFOS, chem_code 253, cas `2921-88-2`, iarc blank, categories `[toxic_air_contaminant, cholinesterase_inhibitor]` |
| pesticides.chemical | 3 | SULFUR, chem_code 560, cas `7704-34-9`, iarc blank, categories `[]` |
| pesticides.product | 1 | ROUNDUP PRO, prodno 1, reg `524-475` |
| pesticides.product | 2 | LORSBAN 4E, prodno 2, reg `62719-220`, fumigant true, california_restricted true |
| pesticides.product | 3 | SULFUR DUST, prodno 3, reg `100-1` |
| pesticides.productchemical | 1..3 | (1,1,41.0) (2,2,44.9) (3,3,90.0) as (product, chemical, pct_active) |
| pesticides.commodity | 1 | ALMOND, site_code `3001` |
| pesticides.commodity | 2 | GRAPE, site_code `29143` |
| pesticides.commodity | 3 | COTTON, site_code `2500` |
| pesticides.pesticideuse | 1..9 | see YAML |
| pesticides.pesticidenotice | 1..3 | one past (2020), two upcoming (2099) |

Use-record arithmetic the tests rely on (lbs_chemical):

| year | county | chemical | product | commodity | lbs_chemical | lbs_product | acres |
|---|---|---|---|---|---|---|---|
| 2023 | Fresno | GLYPHOSATE | ROUNDUP | ALMOND | 100 | 250 | 10 |
| 2023 | Fresno | GLYPHOSATE | ROUNDUP | GRAPE | 50 | 125 | 5 |
| 2023 | Kern | GLYPHOSATE | ROUNDUP | ALMOND | 30 | 75 | 3 |
| 2023 | Fresno | CHLORPYRIFOS | LORSBAN | ALMOND | 20 | 45 | 2 |
| 2023 | Kern | CHLORPYRIFOS | LORSBAN | COTTON | 40 | 90 | 4 |
| 2023 | Fresno | SULFUR | SULFUR DUST | GRAPE | 500 | 550 | 50 |
| 2022 | Fresno | GLYPHOSATE | ROUNDUP | ALMOND | 80 | 200 | 8 |
| 2022 | Kern | CHLORPYRIFOS | LORSBAN | COTTON | 60 | 135 | 6 |
| 2022 | Fresno | SULFUR | SULFUR DUST | GRAPE | 400 | 440 | 40 |

Derived: latest year 2023. 2023 totals: GLYPHOSATE 180 lbs / 3 apps / 2 counties; CHLORPYRIFOS 60 / 2 / 2; SULFUR 500 / 1 / 1; all = 740. Commodities 2023: GRAPE 550, ALMOND 150, COTTON 40. GLYPHOSATE by year: 2023 → 180, 2022 → 80. GLYPHOSATE by county 2023: Fresno 150, Kern 30.

- [ ] **Step 1: Move the existing tests into a package**

```bash
mkdir -p camp/apps/pesticides/tests
git mv camp/apps/pesticides/tests.py camp/apps/pesticides/tests/test_spraydays.py
touch camp/apps/pesticides/tests/__init__.py
```

- [ ] **Step 2: Run the moved tests to confirm nothing broke**

Run: `docker compose run --rm test pytest camp/apps/pesticides/tests/ -q`
Expected: same pass count as before the move (the SprayDays suite), 0 failures.

- [ ] **Step 3: Write the fixture**

Create `fixtures/pesticides-explorer.yaml`:

```yaml
- model: regions.region
  pk: 9001
  fields:
    name: Fresno County
    slug: fresno
    type: county
    external_id: '06019'
    metadata: {ca_county_code: '10'}
    boundary: 9001
- model: regions.region
  pk: 9002
  fields:
    name: Kern County
    slug: kern
    type: county
    external_id: '06029'
    metadata: {ca_county_code: '15'}
    boundary: 9002
- model: regions.boundary
  pk: 9001
  fields:
    region: 9001
    version: 'test'
    metadata: {}
    geometry: SRID=4326;MULTIPOLYGON (((-120.5 36.0, -119.0 36.0, -119.0 37.0, -120.5 37.0, -120.5 36.0)))
- model: regions.boundary
  pk: 9002
  fields:
    region: 9002
    version: 'test'
    metadata: {}
    geometry: SRID=4326;MULTIPOLYGON (((-120.0 35.0, -118.0 35.0, -118.0 35.9, -120.0 35.9, -120.0 35.0)))

- model: pesticides.chemical
  pk: 1
  fields: {chem_code: 1855, name: GLYPHOSATE, cas_number: 1071-83-6, dtxsid: DTXSID1024143, iarc_group: 2A, categories: [carcinogen]}
- model: pesticides.chemical
  pk: 2
  fields: {chem_code: 253, name: CHLORPYRIFOS, cas_number: 2921-88-2, dtxsid: '', iarc_group: '', categories: [toxic_air_contaminant, cholinesterase_inhibitor]}
- model: pesticides.chemical
  pk: 3
  fields: {chem_code: 560, name: SULFUR, cas_number: 7704-34-9, dtxsid: '', iarc_group: '', categories: []}

- model: pesticides.product
  pk: 1
  fields: {prodno: 1, reg_number: 524-475, name: ROUNDUP PRO, fumigant: false, california_restricted: false}
- model: pesticides.product
  pk: 2
  fields: {prodno: 2, reg_number: 62719-220, name: LORSBAN 4E, fumigant: true, california_restricted: true}
- model: pesticides.product
  pk: 3
  fields: {prodno: 3, reg_number: 100-1, name: SULFUR DUST, fumigant: false, california_restricted: false}

- model: pesticides.productchemical
  pk: 1
  fields: {product: 1, chemical: 1, pct_active: 41.0}
- model: pesticides.productchemical
  pk: 2
  fields: {product: 2, chemical: 2, pct_active: 44.9}
- model: pesticides.productchemical
  pk: 3
  fields: {product: 3, chemical: 3, pct_active: 90.0}

- model: pesticides.commodity
  pk: 1
  fields: {site_code: '3001', name: ALMOND}
- model: pesticides.commodity
  pk: 2
  fields: {site_code: '29143', name: GRAPE}
- model: pesticides.commodity
  pk: 3
  fields: {site_code: '2500', name: COTTON}

- model: pesticides.pesticideuse
  pk: 1
  fields: {year: 2023, use_no: 1, county: 9001, product: 1, chemical: 1, commodity: 1, lbs_chemical: 100, lbs_product: 250, acres_treated: 10, application_date: 2023-03-01, aerial_ground: G}
- model: pesticides.pesticideuse
  pk: 2
  fields: {year: 2023, use_no: 2, county: 9001, product: 1, chemical: 1, commodity: 2, lbs_chemical: 50, lbs_product: 125, acres_treated: 5, application_date: 2023-04-01, aerial_ground: G}
- model: pesticides.pesticideuse
  pk: 3
  fields: {year: 2023, use_no: 3, county: 9002, product: 1, chemical: 1, commodity: 1, lbs_chemical: 30, lbs_product: 75, acres_treated: 3, application_date: 2023-05-01, aerial_ground: A}
- model: pesticides.pesticideuse
  pk: 4
  fields: {year: 2023, use_no: 4, county: 9001, product: 2, chemical: 2, commodity: 1, lbs_chemical: 20, lbs_product: 45, acres_treated: 2, application_date: 2023-06-01, aerial_ground: G}
- model: pesticides.pesticideuse
  pk: 5
  fields: {year: 2023, use_no: 5, county: 9002, product: 2, chemical: 2, commodity: 3, lbs_chemical: 40, lbs_product: 90, acres_treated: 4, application_date: 2023-07-01, aerial_ground: A}
- model: pesticides.pesticideuse
  pk: 6
  fields: {year: 2023, use_no: 6, county: 9001, product: 3, chemical: 3, commodity: 2, lbs_chemical: 500, lbs_product: 550, acres_treated: 50, application_date: 2023-08-01, aerial_ground: G}
- model: pesticides.pesticideuse
  pk: 7
  fields: {year: 2022, use_no: 1, county: 9001, product: 1, chemical: 1, commodity: 1, lbs_chemical: 80, lbs_product: 200, acres_treated: 8, application_date: 2022-03-01, aerial_ground: G}
- model: pesticides.pesticideuse
  pk: 8
  fields: {year: 2022, use_no: 2, county: 9002, product: 2, chemical: 2, commodity: 3, lbs_chemical: 60, lbs_product: 135, acres_treated: 6, application_date: 2022-07-01, aerial_ground: A}
- model: pesticides.pesticideuse
  pk: 9
  fields: {year: 2022, use_no: 3, county: 9001, product: 3, chemical: 3, commodity: 2, lbs_chemical: 400, lbs_product: 440, acres_treated: 40, application_date: 2022-08-01, aerial_ground: G}

- model: pesticides.pesticidenotice
  pk: 1
  fields: {application_id: 1, comtrs: 10M13S14E08, county: 9001, scheduled_application: 2020-01-15 08:00:00+00:00, treated_amount: 5, treated_units: Acres, application_method: Ground, products: [2], chemicals: [2]}
- model: pesticides.pesticidenotice
  pk: 2
  fields: {application_id: 2, comtrs: 10M13S14E09, county: 9001, scheduled_application: 2099-01-10 08:00:00+00:00, treated_amount: 12.5, treated_units: Acres, application_method: Ground, products: [2], chemicals: [2]}
- model: pesticides.pesticidenotice
  pk: 3
  fields: {application_id: 3, comtrs: 15M30S28E01, county: 9002, scheduled_application: 2099-02-01 08:00:00+00:00, treated_amount: 40, treated_units: Acres, application_method: Aerial, products: [1, 2], chemicals: [1, 2]}
```

- [ ] **Step 4: Write a fixture smoke test**

Create `camp/apps/pesticides/tests/test_fixture.py`:

```python
from django.test import TestCase

from camp.apps.pesticides.models import Chemical, Commodity, PesticideNotice, PesticideUse, Product


class FixtureTests(TestCase):
    fixtures = ['pesticides-explorer']

    def test_fixture_loads_expected_counts(self):
        assert Chemical.objects.count() == 3
        assert Product.objects.count() == 3
        assert Commodity.objects.count() == 3
        assert PesticideUse.objects.count() == 9
        assert PesticideNotice.objects.count() == 3

    def test_counties_have_boundaries(self):
        from camp.apps.regions.models import Region
        for region in Region.objects.filter(type='county'):
            assert region.boundary is not None
            assert region.boundary.geometry.srid == 4326

    def test_array_field_and_m2m_loaded(self):
        chlorpyrifos = Chemical.objects.get(pk=2)
        assert 'toxic_air_contaminant' in chlorpyrifos.categories
        notice = PesticideNotice.objects.get(pk=3)
        assert set(notice.chemicals.values_list('pk', flat=True)) == {1, 2}
```

- [ ] **Step 5: Run it**

Run: `docker compose run --rm test pytest camp/apps/pesticides/tests/test_fixture.py -v`
Expected: 3 passed. If `categories` fails to deserialize, change the YAML value to a JSON string (`categories: '["carcinogen"]'`); `ArrayField.to_python` accepts either.

- [ ] **Step 6: Commit**

```bash
git add camp/apps/pesticides/tests/__init__.py camp/apps/pesticides/tests/test_spraydays.py camp/apps/pesticides/tests/test_fixture.py fixtures/pesticides-explorer.yaml
git commit -m "test(pesticides): convert tests to a package and add explorer fixture"
```

---

### Task 2: Classification properties and `get_absolute_url`

**Files:**
- Modify: `camp/apps/pesticides/models.py` (Chemical, Product, Commodity)
- Test: `camp/apps/pesticides/tests/test_models.py`

**Interfaces:**
- Produces on `Chemical`: `is_prop65: bool`, `is_tac: bool`, `is_of_concern: bool`, `slug: str`, `get_absolute_url() -> str`, `comptox_url: str | None`.
- Produces on `Product`: `contains_prop65`, `contains_tac`, `contains_iarc` (bool, any chemical with group in 1/2A/2B), `is_of_concern`, `slug`, `get_absolute_url()`.
- Produces on `Commodity`: `slug`, `get_absolute_url()`.
- URL names consumed (defined in Task 5): `pesticides:chemical-detail`, `pesticides:product-detail`, `pesticides:commodity-detail`, each with kwargs `sqid` and `slug`.

- [ ] **Step 1: Write failing tests**

Create `camp/apps/pesticides/tests/test_models.py`:

```python
from django.test import TestCase

from camp.apps.pesticides.models import Chemical, Commodity, Product


class ChemicalClassificationTests(TestCase):
    fixtures = ['pesticides-explorer']

    def test_prop65_derived_from_categories(self):
        assert Chemical.objects.get(pk=1).is_prop65 is True   # carcinogen
        assert Chemical.objects.get(pk=2).is_prop65 is False
        assert Chemical.objects.get(pk=3).is_prop65 is False

    def test_tac_derived_from_categories(self):
        assert Chemical.objects.get(pk=2).is_tac is True
        assert Chemical.objects.get(pk=1).is_tac is False

    def test_of_concern(self):
        assert Chemical.objects.get(pk=1).is_of_concern is True   # prop65 + 2A
        assert Chemical.objects.get(pk=2).is_of_concern is True   # tac
        assert Chemical.objects.get(pk=3).is_of_concern is False

    def test_iarc_group_3_alone_is_not_of_concern(self):
        chem = Chemical.objects.get(pk=3)
        chem.iarc_group = Chemical.IARCGroup.GROUP_3
        assert chem.is_of_concern is False

    def test_comptox_url(self):
        assert Chemical.objects.get(pk=1).comptox_url == 'https://comptox.epa.gov/dashboard/chemical/details/DTXSID1024143'
        assert Chemical.objects.get(pk=2).comptox_url is None


class ProductClassificationTests(TestCase):
    fixtures = ['pesticides-explorer']

    def test_contains_flags(self):
        roundup = Product.objects.get(pk=1)
        lorsban = Product.objects.get(pk=2)
        dust = Product.objects.get(pk=3)
        assert roundup.contains_prop65 is True
        assert roundup.contains_iarc is True
        assert roundup.contains_tac is False
        assert lorsban.contains_tac is True
        assert lorsban.contains_prop65 is False
        assert dust.is_of_concern is False
        assert roundup.is_of_concern is True


class AbsoluteUrlTests(TestCase):
    fixtures = ['pesticides-explorer']

    def test_chemical_url(self):
        chem = Chemical.objects.get(pk=1)
        assert chem.slug == 'glyphosate'
        assert chem.get_absolute_url() == f'/tools/pesticides/chemicals/{chem.sqid}/glyphosate/'

    def test_product_url(self):
        product = Product.objects.get(pk=2)
        assert product.get_absolute_url() == f'/tools/pesticides/products/{product.sqid}/lorsban-4e/'

    def test_commodity_url(self):
        commodity = Commodity.objects.get(pk=1)
        assert commodity.get_absolute_url() == f'/tools/pesticides/commodities/{commodity.sqid}/almond/'

    def test_slug_never_empty(self):
        chem = Chemical(name='???', chem_code=999)
        assert chem.slug == 'chemical'
```

- [ ] **Step 2: Run to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/pesticides/tests/test_models.py -q`
Expected: FAIL with `AttributeError: 'Chemical' object has no attribute 'is_prop65'` (URL tests fail with `NoReverseMatch` until Task 5; that's expected and they stay red until then).

- [ ] **Step 3: Implement**

In `camp/apps/pesticides/models.py`, add imports at the top:

```python
from django.urls import reverse
from django.utils.text import slugify
```

Add to `Chemical` after `__str__`:

```python
    PROP65_CATEGORIES = {'carcinogen', 'reproductive_toxin', 'developmental_toxin'}
    IARC_CONCERN_GROUPS = {'1', '2A', '2B'}

    @property
    def slug(self):
        return slugify(self.name) or 'chemical'

    def get_absolute_url(self):
        return reverse('pesticides:chemical-detail', kwargs={'sqid': self.sqid, 'slug': self.slug})

    @property
    def is_prop65(self):
        return bool(self.PROP65_CATEGORIES & set(self.categories or []))

    @property
    def is_tac(self):
        return self.Category.TOXIC_AIR_CONTAMINANT in (self.categories or [])

    @property
    def is_iarc_concern(self):
        return self.iarc_group in self.IARC_CONCERN_GROUPS

    @property
    def is_of_concern(self):
        return self.is_prop65 or self.is_tac or self.is_iarc_concern

    @property
    def comptox_url(self):
        if not self.dtxsid:
            return None
        return f'https://comptox.epa.gov/dashboard/chemical/details/{self.dtxsid}'
```

Add to `Commodity` after `__str__`:

```python
    @property
    def slug(self):
        return slugify(self.name) or 'commodity'

    def get_absolute_url(self):
        return reverse('pesticides:commodity-detail', kwargs={'sqid': self.sqid, 'slug': self.slug})
```

Add to `Product` after `__str__`:

```python
    @property
    def slug(self):
        return slugify(self.name) or 'product'

    def get_absolute_url(self):
        return reverse('pesticides:product-detail', kwargs={'sqid': self.sqid, 'slug': self.slug})

    def _chemical_list(self):
        # Uses the prefetch cache when the view prefetched 'chemicals'; otherwise one query.
        return list(self.chemicals.all())

    @property
    def contains_prop65(self):
        return any(c.is_prop65 for c in self._chemical_list())

    @property
    def contains_tac(self):
        return any(c.is_tac for c in self._chemical_list())

    @property
    def contains_iarc(self):
        return any(c.is_iarc_concern for c in self._chemical_list())

    @property
    def is_of_concern(self):
        return any(c.is_of_concern for c in self._chemical_list())
```

- [ ] **Step 4: Run tests**

Run: `docker compose run --rm test pytest camp/apps/pesticides/tests/test_models.py -q`
Expected: classification tests pass; the 4 `AbsoluteUrlTests` fail with `NoReverseMatch` until Task 5 adds the URLs.

- [ ] **Step 5: Commit**

```bash
git add camp/apps/pesticides/models.py camp/apps/pesticides/tests/test_models.py
git commit -m "feat(pesticides): add classification properties and absolute URLs"
```

---

### Task 3: Full-text `.search()` querysets

**Files:**
- Modify: `camp/apps/pesticides/querysets.py`
- Test: `camp/apps/pesticides/tests/test_querysets.py`

**Interfaces:**
- Produces: `ChemicalQuerySet.search(query)`, `ProductQuerySet.search(query)`, `CommodityQuerySet.search(query)`. Each returns a queryset annotated with `rank`, filtered to matches, ordered by `-rank, name`. Later `.order_by()` calls override the ordering; the `rank` annotation stays available.

- [ ] **Step 1: Write failing tests**

Create `camp/apps/pesticides/tests/test_querysets.py`:

```python
from django.test import TestCase

from camp.apps.pesticides.models import Chemical, Commodity, Product


class ChemicalSearchTests(TestCase):
    fixtures = ['pesticides-explorer']

    def test_partial_substring_matches(self):
        names = list(Chemical.objects.search('chlor').values_list('name', flat=True))
        assert names == ['CHLORPYRIFOS']

    def test_case_insensitive_full_word(self):
        names = list(Chemical.objects.search('glyphosate').values_list('name', flat=True))
        assert names == ['GLYPHOSATE']

    def test_cas_number_matches(self):
        names = list(Chemical.objects.search('7704-34-9').values_list('name', flat=True))
        assert names == ['SULFUR']

    def test_no_match(self):
        assert Chemical.objects.search('zzzz').count() == 0

    def test_exact_name_ranks_first(self):
        Chemical.objects.create(chem_code=9999, name='SULFUR DIOXIDE')
        names = list(Chemical.objects.search('sulfur').values_list('name', flat=True))
        assert names[0] == 'SULFUR'
        assert set(names) == {'SULFUR', 'SULFUR DIOXIDE'}

    def test_chainable_with_filter(self):
        qs = Chemical.objects.search('sulfur').filter(iarc_group='')
        assert qs.count() == 1


class ProductSearchTests(TestCase):
    fixtures = ['pesticides-explorer']

    def test_name(self):
        assert list(Product.objects.search('lorsban').values_list('pk', flat=True)) == [2]

    def test_reg_number(self):
        assert list(Product.objects.search('62719-220').values_list('pk', flat=True)) == [2]


class CommoditySearchTests(TestCase):
    fixtures = ['pesticides-explorer']

    def test_name(self):
        assert list(Commodity.objects.search('alm').values_list('pk', flat=True)) == [1]

    def test_site_code(self):
        assert list(Commodity.objects.search('29143').values_list('pk', flat=True)) == [2]
```

- [ ] **Step 2: Run to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/pesticides/tests/test_querysets.py -q`
Expected: FAIL with `AttributeError: 'ChemicalQuerySet' object has no attribute 'search'`.

- [ ] **Step 3: Implement**

Replace the top of `camp/apps/pesticides/querysets.py` and add a mixin:

```python
from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db.models import Prefetch, Q, QuerySet


class SearchMixin:
    """
    Postgres full-text search following camp/apps/helpdesk/managers.py, plus an
    icontains fallback so partial tokens ("chlor") still match. Subclasses set
    `search_primary` (weight A) and `search_secondary` (weight B, an identifier
    column matched with icontains as well).
    """
    search_primary = 'name'
    search_secondary = None

    def search(self, query):
        query = (query or '').strip()
        if not query:
            return self
        search_query = SearchQuery(query)
        search_vector = SearchVector(self.search_primary, weight='A')
        substring = Q(**{f'{self.search_primary}__icontains': query})
        if self.search_secondary:
            search_vector = search_vector + SearchVector(self.search_secondary, weight='B')
            substring = substring | Q(**{f'{self.search_secondary}__icontains': query})
        return (self
            .annotate(rank=SearchRank(search_vector, search_query))
            .filter(Q(rank__gt=0) | substring)
            .order_by('-rank', self.search_primary)
        )
```

Then make the three querysets use it and declare their fields:

```python
class ChemicalQuerySet(SearchMixin, QuerySet):
    search_secondary = 'cas_number'
    # existing with_commodities() unchanged


class CommodityQuerySet(SearchMixin, QuerySet):
    search_secondary = 'site_code'
    # existing with_chemicals() / with_products() unchanged


class ProductQuerySet(SearchMixin, QuerySet):
    search_secondary = 'reg_number'
    # existing with_commodities() unchanged
```

Note: `rank__gt=0` is used instead of `filter(search=search_query)` so we don't need a second annotation; `SearchRank` is 0 when the tsquery doesn't match.

- [ ] **Step 4: Run tests**

Run: `docker compose run --rm test pytest camp/apps/pesticides/tests/test_querysets.py -q`
Expected: 10 passed. If `test_exact_name_ranks_first` fails because both rank equal, the secondary `name` ordering puts `SULFUR` before `SULFUR DIOXIDE` anyway; if it still fails, print the ranks and adjust to `.order_by('-rank', Length('name'), 'name')` importing `Length` from `django.db.models.functions`.

- [ ] **Step 5: Commit**

```bash
git add camp/apps/pesticides/querysets.py camp/apps/pesticides/tests/test_querysets.py
git commit -m "feat(pesticides): add full-text search to chemical, product, and commodity querysets"
```

---

### Task 4: Aggregate helpers (`stats.py`)

**Files:**
- Create: `camp/apps/pesticides/stats.py`
- Test: `camp/apps/pesticides/tests/test_stats.py`

**Interfaces (all produced here, consumed by Tasks 6–9):**

```python
LATEST_YEAR_KEY = 'pesticides:latest-year'
LANDING_KEY = 'pesticides:landing-stats'
SJV_COUNTY_COUNT = 8

def latest_year() -> int | None                      # cached 1h
def years_loaded() -> tuple[int, int] | None          # (min, max) of PesticideUse.year
def by_year(uses, lbs_field='lbs_chemical') -> list[dict]        # {year, lbs, acres, applications}, newest first
def by_county(uses, year, lbs_field='lbs_chemical') -> list[dict] # {county_id, county_name, county_slug, lbs, acres, applications}, by lbs desc
def year_totals(uses, year, lbs_field='lbs_chemical') -> dict     # {lbs, applications, counties}
def top_related(uses, year, field, lbs_field='lbs_chemical', limit=10) -> list[Related]
    # Related = SimpleNamespace(obj=<Chemical|Product|Commodity>, lbs=float)
def recent_uses(uses, limit=10) -> QuerySet[PesticideUse]        # select_related, newest first
def upcoming_notices(notices, limit=10) -> QuerySet[PesticideNotice]
def upcoming_by_county(notices) -> list[dict]                     # {county_name, count}
def upcoming_count(notices) -> int
def notice_window() -> dict | None                                # {count, first, last} over all notices
def landing_stats() -> dict                                       # cached 24h; keys below
```

`landing_stats()` keys: `latest_year`, `years` (tuple or None), `chemical_count`, `product_count`, `commodity_count`, `total_lbs` (latest year), `upcoming_week` (notices in next 7 days), `top_chemicals`, `top_chemicals_of_concern`, `top_commodities` (each a list of `Related`), `by_county` (the `by_county()` rows for all uses in the latest year, for the map).

- [ ] **Step 1: Write failing tests**

Create `camp/apps/pesticides/tests/test_stats.py`:

```python
from django.core.cache import cache
from django.test import TestCase

from camp.apps.pesticides import stats
from camp.apps.pesticides.models import Chemical, Commodity, PesticideNotice, PesticideUse, Product


class StatsTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()

    def test_latest_year(self):
        assert stats.latest_year() == 2023

    def test_latest_year_is_cached(self):
        assert stats.latest_year() == 2023
        PesticideUse.objects.all().delete()
        assert stats.latest_year() == 2023
        cache.clear()
        assert stats.latest_year() is None

    def test_years_loaded(self):
        assert stats.years_loaded() == (2022, 2023)

    def test_by_year_for_chemical(self):
        rows = stats.by_year(PesticideUse.objects.filter(chemical_id=1))
        assert [(r['year'], r['lbs'], r['acres'], r['applications']) for r in rows] == [
            (2023, 180.0, 18.0, 3),
            (2022, 80.0, 8.0, 1),
        ]

    def test_by_year_uses_lbs_product_for_products(self):
        rows = stats.by_year(PesticideUse.objects.filter(product_id=1), lbs_field='lbs_product')
        assert rows[0]['lbs'] == 450.0

    def test_by_county(self):
        rows = stats.by_county(PesticideUse.objects.filter(chemical_id=1), 2023)
        assert [(r['county_name'], r['lbs'], r['applications']) for r in rows] == [
            ('Fresno County', 150.0, 2),
            ('Kern County', 30.0, 1),
        ]

    def test_year_totals(self):
        totals = stats.year_totals(PesticideUse.objects.filter(chemical_id=1), 2023)
        assert totals == {'lbs': 180.0, 'applications': 3, 'counties': 2}

    def test_year_totals_empty(self):
        totals = stats.year_totals(PesticideUse.objects.none(), 2023)
        assert totals == {'lbs': 0, 'applications': 0, 'counties': 0}

    def test_top_related_commodities_for_chemical(self):
        rows = stats.top_related(PesticideUse.objects.filter(chemical_id=1), 2023, 'commodity')
        assert [(r.obj.name, r.lbs) for r in rows] == [('ALMOND', 130.0), ('GRAPE', 50.0)]
        assert isinstance(rows[0].obj, Commodity)

    def test_top_related_respects_limit(self):
        rows = stats.top_related(PesticideUse.objects.all(), 2023, 'chemical', limit=2)
        assert [r.obj.name for r in rows] == ['SULFUR', 'GLYPHOSATE']
        assert isinstance(rows[0].obj, Chemical)

    def test_recent_uses_newest_first(self):
        uses = list(stats.recent_uses(PesticideUse.objects.filter(chemical_id=1), limit=2))
        assert [u.pk for u in uses] == [3, 2]

    def test_upcoming_notices_excludes_past(self):
        notices = list(stats.upcoming_notices(PesticideNotice.objects.filter(chemicals=2)))
        assert [n.pk for n in notices] == [2, 3]

    def test_upcoming_by_county(self):
        rows = stats.upcoming_by_county(PesticideNotice.objects.filter(chemicals=2))
        assert rows == [
            {'county_name': 'Fresno County', 'count': 1},
            {'county_name': 'Kern County', 'count': 1},
        ]

    def test_notice_window(self):
        window = stats.notice_window()
        assert window['count'] == 3
        assert window['first'].year == 2020
        assert window['last'].year == 2099

    def test_landing_stats(self):
        data = stats.landing_stats()
        assert data['latest_year'] == 2023
        assert data['years'] == (2022, 2023)
        assert data['chemical_count'] == 3
        assert data['product_count'] == 3
        assert data['commodity_count'] == 3
        assert data['total_lbs'] == 740.0
        assert data['upcoming_week'] == 0
        assert [r.obj.name for r in data['top_chemicals']] == ['SULFUR', 'GLYPHOSATE', 'CHLORPYRIFOS']
        assert [r.obj.name for r in data['top_chemicals_of_concern']] == ['GLYPHOSATE', 'CHLORPYRIFOS']
        assert [r.obj.name for r in data['top_commodities']] == ['GRAPE', 'ALMOND', 'COTTON']
        assert [(r['county_name'], r['lbs']) for r in data['by_county']] == [('Fresno County', 670.0), ('Kern County', 70.0)]

    def test_landing_stats_cached(self):
        stats.landing_stats()
        Chemical.objects.create(chem_code=1, name='NEW')
        assert stats.landing_stats()['chemical_count'] == 3

    def test_landing_stats_empty_db(self):
        PesticideNotice.objects.all().delete()
        PesticideUse.objects.all().delete()
        data = stats.landing_stats()
        assert data['latest_year'] is None
        assert data['total_lbs'] == 0
        assert data['top_chemicals'] == []
        assert data['by_county'] == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/pesticides/tests/test_stats.py -q`
Expected: FAIL with `ImportError: cannot import name 'stats'`.

- [ ] **Step 3: Implement**

Create `camp/apps/pesticides/stats.py`:

```python
"""
Aggregate helpers for the pesticides explorer. Every function takes an
already-filtered queryset so the same code serves chemical, product, and
commodity pages. Aggregates run live over PesticideUse (see the spec's
Performance section); if that gets slow, this module is the seam where a
summary table gets swapped in.
"""
from datetime import timedelta
from types import SimpleNamespace

from django.core.cache import cache
from django.db.models import Count, Max, Min, Sum
from django.utils import timezone

from camp.apps.pesticides.models import Chemical, Commodity, PesticideNotice, PesticideUse

LATEST_YEAR_KEY = 'pesticides:latest-year'
LANDING_KEY = 'pesticides:landing-stats'
LATEST_YEAR_TTL = 60 * 60
LANDING_TTL = 60 * 60 * 24
SJV_COUNTY_COUNT = 8
_MISSING = object()


def latest_year():
    value = cache.get(LATEST_YEAR_KEY, _MISSING)
    if value is _MISSING:
        value = PesticideUse.objects.aggregate(year=Max('year'))['year']
        cache.set(LATEST_YEAR_KEY, value, LATEST_YEAR_TTL)
    return value


def years_loaded():
    data = PesticideUse.objects.aggregate(first=Min('year'), last=Max('year'))
    if data['first'] is None:
        return None
    return (data['first'], data['last'])


def _totals(lbs_field):
    return {
        'lbs': Sum(lbs_field),
        'acres': Sum('acres_treated'),
        'applications': Count('id'),
    }


def by_year(uses, lbs_field='lbs_chemical'):
    return list(
        uses.values('year')
        .annotate(**_totals(lbs_field))
        .order_by('-year')
    )


def by_county(uses, year, lbs_field='lbs_chemical'):
    rows = (
        uses.filter(year=year)
        .values('county_id', 'county__name', 'county__slug')
        .annotate(**_totals(lbs_field))
        .order_by('-lbs')
    )
    return [
        {
            'county_id': row['county_id'],
            'county_name': row['county__name'],
            'county_slug': row['county__slug'],
            'lbs': row['lbs'],
            'acres': row['acres'],
            'applications': row['applications'],
        }
        for row in rows
    ]


def year_totals(uses, year, lbs_field='lbs_chemical'):
    data = uses.filter(year=year).aggregate(
        lbs=Sum(lbs_field),
        applications=Count('id'),
        counties=Count('county', distinct=True),
    )
    return {
        'lbs': data['lbs'] or 0,
        'applications': data['applications'] or 0,
        'counties': data['counties'] or 0,
    }


def top_related(uses, year, field, lbs_field='lbs_chemical', limit=10):
    """
    Rank the related objects on `field` ('chemical' | 'product' | 'commodity')
    by pounds in `year`. Returns SimpleNamespace(obj=<instance>, lbs=<float>).
    Two queries: the group-by, then in_bulk for the instances (needed because
    sqid is not a DB column and templates need get_absolute_url()).
    """
    if year is None:
        return []
    rows = list(
        uses.filter(year=year, **{f'{field}__isnull': False})
        .values(field)
        .annotate(lbs=Sum(lbs_field))
        .order_by('-lbs')[:limit]
    )
    model = PesticideUse._meta.get_field(field).related_model
    objects = model.objects.in_bulk([row[field] for row in rows])
    return [
        SimpleNamespace(obj=objects[row[field]], lbs=row['lbs'] or 0)
        for row in rows if row[field] in objects
    ]


def recent_uses(uses, limit=10):
    return (
        uses.select_related('county', 'product', 'chemical', 'commodity')
        .order_by('-application_date', '-pk')[:limit]
    )


def _upcoming(notices):
    return notices.filter(scheduled_application__gte=timezone.now())


def upcoming_notices(notices, limit=10):
    return (
        _upcoming(notices)
        .select_related('county')
        .prefetch_related('chemicals', 'products')
        .order_by('scheduled_application')[:limit]
    )


def upcoming_count(notices):
    return _upcoming(notices).count()


def upcoming_by_county(notices):
    rows = (
        _upcoming(notices)
        .values('county__name')
        .annotate(count=Count('id'))
        .order_by('-count', 'county__name')
    )
    return [{'county_name': row['county__name'], 'count': row['count']} for row in rows]


def notice_window():
    data = PesticideNotice.objects.aggregate(
        count=Count('id'),
        first=Min('scheduled_application'),
        last=Max('scheduled_application'),
    )
    if not data['count']:
        return None
    return data


def _top_chemicals_of_concern(year, limit=10):
    # is_of_concern is derived in Python, so over-fetch then filter; fall back
    # to a category/IARC-restricted query if the first pass comes up short.
    rows = [r for r in top_related(PesticideUse.objects.all(), year, 'chemical', limit=limit * 5) if r.obj.is_of_concern]
    if len(rows) < limit:
        concern = PesticideUse.objects.filter(chemical__in=Chemical.objects.filter(
            models_q_of_concern()
        ))
        rows = top_related(concern, year, 'chemical', limit=limit)
    return rows[:limit]


def models_q_of_concern():
    from django.db.models import Q
    return (
        Q(categories__overlap=list(Chemical.PROP65_CATEGORIES | {Chemical.Category.TOXIC_AIR_CONTAMINANT}))
        | Q(iarc_group__in=list(Chemical.IARC_CONCERN_GROUPS))
    )


def _build_landing_stats():
    year = latest_year()
    uses = PesticideUse.objects.all()
    now = timezone.now()
    return {
        'latest_year': year,
        'years': years_loaded(),
        'chemical_count': Chemical.objects.count(),
        'product_count': __import__('camp.apps.pesticides.models', fromlist=['Product']).Product.objects.count(),
        'commodity_count': Commodity.objects.count(),
        'total_lbs': (uses.filter(year=year).aggregate(lbs=Sum('lbs_chemical'))['lbs'] or 0) if year else 0,
        'upcoming_week': PesticideNotice.objects.filter(
            scheduled_application__gte=now,
            scheduled_application__lt=now + timedelta(days=7),
        ).count(),
        'top_chemicals': top_related(uses, year, 'chemical'),
        'top_chemicals_of_concern': _top_chemicals_of_concern(year),
        'top_commodities': top_related(uses, year, 'commodity'),
        'by_county': by_county(uses, year) if year else [],
    }


def landing_stats():
    data = cache.get(LANDING_KEY)
    if data is None:
        data = _build_landing_stats()
        cache.set(LANDING_KEY, data, LANDING_TTL)
    return data
```

Clean-ups to make while implementing (the sketch above is deliberately literal): import `Product` at the top alongside `Chemical`/`Commodity` instead of the `__import__` hack, and move the `Q` import to the top. `top_related` must return `[]` when `year is None` so empty databases never run the group-by.

- [ ] **Step 4: Run tests**

Run: `docker compose run --rm test pytest camp/apps/pesticides/tests/test_stats.py -q`
Expected: 17 passed. `landing_stats` caches a dict containing model instances; the locmem cache pickles them, which works for these models.

- [ ] **Step 5: Commit**

```bash
git add camp/apps/pesticides/stats.py camp/apps/pesticides/tests/test_stats.py
git commit -m "feat(pesticides): add aggregate helpers for the explorer"
```

---

### Task 5: URLs, template tags, base template, and the chemical list

**Files:**
- Create: `camp/apps/pesticides/urls.py`, `camp/apps/pesticides/forms.py`, `camp/apps/pesticides/views.py`
- Create: `camp/apps/pesticides/templatetags/__init__.py`, `camp/apps/pesticides/templatetags/pesticides_explorer.py`
- Create: `camp/templates/pesticides/base.html`, `camp/templates/pesticides/includes/filter-form.html`, `camp/templates/pesticides/includes/pagination.html`, `camp/templates/pesticides/includes/classification-badges.html`, `camp/templates/pesticides/chemical-list.html`
- Modify: `camp/urls.py` (mount above the catch-all)
- Test: `camp/apps/pesticides/tests/test_views.py` (chemical list section)

**Interfaces:**
- Produces `ExplorerListMixin` (used by Task 6):
  - class attrs: `form_class`, `paginate_by = 50`, `sort_fields: dict[str, str]` (param key → annotation/field), `default_sort: str` (e.g. `'-lbs'`), `related_filters: dict[str, callable]` (param → function(queryset, obj) returning filtered queryset), `related_models: dict[str, Model]`.
  - methods: `get_search_query() -> str`, `apply_filters(queryset, cleaned_data) -> queryset` (per-view override), `annotate_queryset(queryset, year) -> queryset` (per-view override), `get_sort() -> tuple[str|None, str|None, bool]` `(param, field, desc)`, `get_summary_sentence(count) -> str`.
  - context: `form`, `query`, `sort`, `latest_year`, `result_count`, `summary_sentence`, `related` (dict param→object for active related filters), `page_obj`, `paginator`, `is_paginated`, `object_list`, `section` (`'chemicals'|'products'|'commodities'`).
- Produces template tags (`{% load pesticides_explorer %}`): `{% qs_replace page=2 %}` (returns `?`-prefixed query string with the given keys replaced, `None`/empty removes a key), `{% sort_link 'lbs' 'Pounds applied' %}` (renders a `<a>` with direction icon; toggles direction; drops `page`), `{{ value|lbs }}` (whole-number pounds with commas, `—` for None).
- Produces URL names: `pesticides:home`, `pesticides:chemical-list`, `pesticides:chemical-detail`, `pesticides:chemical-redirect`, and the product/commodity equivalents (Task 6/7 implement the views; the URL conf is complete here with placeholder views that Tasks 6–9 replace).
- Produces `pesticides/base.html` blocks: `title`, `body-class`, `explorer-header` (h1 + lede), `breadcrumb-list`, `explorer-content`. Sub-nav highlights via `section` context.

- [ ] **Step 1: Write failing tests for the chemical list**

Create `camp/apps/pesticides/tests/test_views.py`:

```python
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.pesticides.models import Chemical, Commodity, Product


class ChemicalListTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.url = reverse('pesticides:chemical-list')

    def names(self, response):
        return [c.name for c in response.context['object_list']]

    def test_renders(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        self.assertTemplateUsed(response, 'pesticides/chemical-list.html')
        assert response.context['result_count'] == 3
        assert response.context['latest_year'] == 2023

    def test_default_sort_is_lbs_desc(self):
        response = self.client.get(self.url)
        assert self.names(response) == ['SULFUR', 'GLYPHOSATE', 'CHLORPYRIFOS']
        lbs = [c.lbs_applied for c in response.context['object_list']]
        assert lbs == [500.0, 180.0, 60.0]

    def test_sort_by_name(self):
        response = self.client.get(self.url, {'sort': 'name'})
        assert self.names(response) == ['CHLORPYRIFOS', 'GLYPHOSATE', 'SULFUR']
        response = self.client.get(self.url, {'sort': '-name'})
        assert self.names(response) == ['SULFUR', 'GLYPHOSATE', 'CHLORPYRIFOS']

    def test_unknown_sort_falls_back(self):
        response = self.client.get(self.url, {'sort': 'evil'})
        assert self.names(response) == ['SULFUR', 'GLYPHOSATE', 'CHLORPYRIFOS']

    def test_search_orders_by_rank(self):
        response = self.client.get(self.url, {'q': 'chlor'})
        assert self.names(response) == ['CHLORPYRIFOS']
        assert 'matching' in response.context['summary_sentence']

    def test_category_filter_is_or(self):
        response = self.client.get(self.url, {'category': ['carcinogen', 'toxic_air_contaminant']})
        assert set(self.names(response)) == {'GLYPHOSATE', 'CHLORPYRIFOS'}

    def test_iarc_filter(self):
        response = self.client.get(self.url, {'iarc_group': '2A'})
        assert self.names(response) == ['GLYPHOSATE']

    def test_invalid_iarc_ignored(self):
        response = self.client.get(self.url, {'iarc_group': '9Z'})
        assert response.status_code == 200
        assert response.context['result_count'] == 3

    def test_product_count_annotation(self):
        response = self.client.get(self.url, {'sort': 'name'})
        assert [c.product_count for c in response.context['object_list']] == [1, 1, 1]

    def test_related_filter_by_product(self):
        product = Product.objects.get(pk=2)
        response = self.client.get(self.url, {'product': product.sqid})
        assert self.names(response) == ['CHLORPYRIFOS']
        assert response.context['related']['product'] == product

    def test_related_filter_by_commodity(self):
        commodity = Commodity.objects.get(pk=1)
        response = self.client.get(self.url, {'commodity': commodity.sqid})
        assert set(self.names(response)) == {'GLYPHOSATE', 'CHLORPYRIFOS'}

    def test_unknown_related_sqid_is_empty(self):
        response = self.client.get(self.url, {'product': 'nope'})
        assert response.context['result_count'] == 0

    def test_pagination_links_keep_filters(self):
        for i in range(60):
            Chemical.objects.create(chem_code=10000 + i, name=f'TEST {i}', categories=['oil'])
        response = self.client.get(self.url, {'category': 'oil', 'sort': 'name'})
        assert response.context['is_paginated'] is True
        assert 'category=oil' in response.content.decode()
        assert 'page=2' in response.content.decode()

    def test_rows_link_to_detail(self):
        response = self.client.get(self.url)
        assert Chemical.objects.get(pk=1).get_absolute_url() in response.content.decode()

    def test_empty_database(self):
        Chemical.objects.all().delete()
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.context['result_count'] == 0
```

- [ ] **Step 2: Run to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/pesticides/tests/test_views.py -q`
Expected: FAIL with `NoReverseMatch: 'pesticides' is not a registered namespace`.

- [ ] **Step 3: Template tags**

Create `camp/apps/pesticides/templatetags/__init__.py` (empty) and `camp/apps/pesticides/templatetags/pesticides_explorer.py`:

```python
from django import template
from django.contrib.humanize.templatetags.humanize import intcomma
from django.utils.html import format_html

register = template.Library()


@register.simple_tag(takes_context=True)
def qs_replace(context, **kwargs):
    """
    Current query string with the given keys replaced. A value of None or ''
    removes the key. Returns '' when nothing remains, otherwise '?a=b&c=d'.
    """
    params = context['request'].GET.copy()
    for key, value in kwargs.items():
        if value is None or value == '':
            params.pop(key, None)
        else:
            params[key] = value
    encoded = params.urlencode()
    return f'?{encoded}' if encoded else '?'


@register.simple_tag(takes_context=True)
def sort_link(context, key, label):
    """
    Column header link. Clicking the active column flips direction; clicking
    another column sorts descending for numeric-style keys ('lbs', counts) and
    ascending for 'name'. Always resets `page`.
    """
    current = context.get('sort') or ''
    active = current.lstrip('-') == key
    descending = current.startswith('-')
    if active:
        target = key if descending else f'-{key}'
        icon = 'fa-arrow-down-wide-short' if descending else 'fa-arrow-up-short-wide'
    else:
        target = 'name' if key == 'name' else f'-{key}'
        icon = 'fa-arrow-up-arrow-down'
    href = qs_replace(context, sort=target, page=None)
    css = 'sort-link is-active' if active else 'sort-link'
    return format_html(
        '<a class="{}" href="{}">{} <span class="icon is-small"><span class="fa-regular {}"></span></span></a>',
        css, href, label, icon,
    )


@register.filter
def lbs(value):
    if value is None:
        return '—'
    return intcomma(int(round(value)))
```

- [ ] **Step 4: Forms**

Create `camp/apps/pesticides/forms.py`:

```python
from django import forms
from django.utils.translation import gettext_lazy as _

from camp.apps.pesticides.models import Chemical

BOOL_CHOICES = [('', _('Any')), ('true', _('Yes')), ('false', _('No'))]


class SearchForm(forms.Form):
    q = forms.CharField(label=_('Search'), required=False, max_length=128)

    def bool_value(self, name):
        value = self.cleaned_data.get(name)
        return {'true': True, 'false': False}.get(value)


class ChemicalFilterForm(SearchForm):
    category = forms.MultipleChoiceField(
        label=_('Category'),
        required=False,
        choices=Chemical.Category.choices,
        widget=forms.CheckboxSelectMultiple,
    )
    iarc_group = forms.ChoiceField(
        label=_('IARC group'),
        required=False,
        choices=[('', _('Any'))] + list(Chemical.IARCGroup.choices),
    )


class ProductFilterForm(SearchForm):
    fumigant = forms.ChoiceField(label=_('Fumigant'), required=False, choices=BOOL_CHOICES)
    california_restricted = forms.ChoiceField(label=_('California restricted'), required=False, choices=BOOL_CHOICES)


class CommodityFilterForm(SearchForm):
    pass
```

Note: the spec said to reuse the v2 `FilterSet`s; the forms above replace that because the chemical `category` filter is multi-valued here and single-valued in the API, and the boolean product filters are one line each. This is a deliberate simplification; the API filters are untouched.

- [ ] **Step 5: Views (mixin + chemical list + placeholders)**

Create `camp/apps/pesticides/views.py`:

```python
from django.db.models import Count, F, FloatField, OuterRef, Subquery, Sum
from django.http import Http404
from django.shortcuts import redirect

import vanilla

from camp.apps.pesticides import stats
from camp.apps.pesticides.forms import ChemicalFilterForm, CommodityFilterForm, ProductFilterForm
from camp.apps.pesticides.models import Chemical, Commodity, PesticideNotice, PesticideUse, Product


def lbs_subquery(field, year, lbs_field='lbs_chemical'):
    """Sum of pounds in `year` for the outer row, via `PesticideUse.<field>`."""
    return Subquery(
        PesticideUse.objects
        .filter(**{field: OuterRef('pk')}, year=year)
        .values(field)
        .annotate(total=Sum(lbs_field))
        .values('total'),
        output_field=FloatField(),
    )


def related_pks(field, obj, target):
    """PKs of `target` (a PesticideUse FK name) that share a use record with obj."""
    return PesticideUse.objects.filter(**{field: obj}).values(target)


class ExplorerListMixin:
    paginate_by = 50
    form_class = None
    section = None
    sort_fields = {}
    default_sort = 'name'
    related_models = {}

    def dispatch(self, request, *args, **kwargs):
        self.form = self.form_class(request.GET)
        self.form.is_valid()
        self.latest_year = stats.latest_year()
        self.related = self.get_related_objects()
        return super().dispatch(request, *args, **kwargs)

    def get_search_query(self):
        return (self.form.cleaned_data.get('q') or '').strip()

    def get_related_objects(self):
        related = {}
        for param, model in self.related_models.items():
            value = self.request.GET.get(param)
            if value:
                related[param] = model.objects.filter(sqid=value).first() or Http404
        return related

    def apply_related(self, queryset):
        for param, obj in self.related.items():
            if obj is Http404:
                return queryset.none()
            queryset = self.filter_related(queryset, param, obj)
        return queryset

    def filter_related(self, queryset, param, obj):
        raise NotImplementedError

    def apply_filters(self, queryset, data):
        return queryset

    def annotate_queryset(self, queryset, year):
        return queryset

    def get_sort(self):
        param = self.request.GET.get('sort') or ''
        key = param.lstrip('-')
        if key not in self.sort_fields:
            if self.get_search_query():
                return None, None, False
            param = self.default_sort
            key = param.lstrip('-')
        return param, self.sort_fields[key], param.startswith('-')

    def get_queryset(self):
        queryset = self.model.objects.all()
        query = self.get_search_query()
        if query:
            queryset = queryset.search(query)
        queryset = self.apply_related(queryset)
        queryset = self.apply_filters(queryset, self.form.cleaned_data)
        queryset = self.annotate_queryset(queryset, self.latest_year)
        self.sort, field, desc = self.get_sort()
        if field:
            expr = F(field).desc(nulls_last=True) if desc else F(field).asc(nulls_last=True)
            queryset = queryset.order_by(expr, 'name')
        return queryset

    def get_summary_sentence(self, count):
        noun = self.section if count != 1 else self.section[:-1]
        if self.section == 'commodities' and count == 1:
            noun = 'commodity'
        parts = [f'{count:,} {noun}']
        query = self.get_search_query()
        if query:
            parts.append(f'matching “{query}”')
        parts.extend(self.describe_filters(self.form.cleaned_data))
        for param, obj in self.related.items():
            if obj is not Http404:
                parts.append(f'linked to {obj.name}')
        return ' '.join(parts)

    def describe_filters(self, data):
        return []

    def get_context_data(self, **kwargs):
        count = kwargs['paginator'].count if kwargs.get('paginator') else len(kwargs.get('object_list', []))
        return super().get_context_data(
            form=self.form,
            query=self.get_search_query(),
            sort=self.sort,
            latest_year=self.latest_year,
            result_count=count,
            summary_sentence=self.get_summary_sentence(count),
            related={k: v for k, v in self.related.items() if v is not Http404},
            section=self.section,
            **kwargs,
        )


class ChemicalList(ExplorerListMixin, vanilla.ListView):
    model = Chemical
    form_class = ChemicalFilterForm
    template_name = 'pesticides/chemical-list.html'
    section = 'chemicals'
    sort_fields = {'name': 'name', 'lbs': 'lbs_applied', 'products': 'product_count', 'iarc': 'iarc_group'}
    default_sort = '-lbs'
    related_models = {'product': Product, 'commodity': Commodity}

    def filter_related(self, queryset, param, obj):
        if param == 'product':
            return queryset.filter(product_chemicals__product=obj)
        return queryset.filter(pk__in=related_pks('commodity', obj, 'chemical'))

    def apply_filters(self, queryset, data):
        if data.get('category'):
            queryset = queryset.filter(categories__overlap=data['category'])
        if data.get('iarc_group'):
            queryset = queryset.filter(iarc_group=data['iarc_group'])
        return queryset

    def annotate_queryset(self, queryset, year):
        queryset = queryset.annotate(product_count=Count('product_chemicals', distinct=True))
        if year:
            queryset = queryset.annotate(lbs_applied=lbs_subquery('chemical', year))
        else:
            queryset = queryset.annotate(lbs_applied=F('chem_code') * 0.0)
        return queryset

    def describe_filters(self, data):
        parts = []
        if data.get('category'):
            labels = dict(Chemical.Category.choices)
            parts.append('in ' + ' or '.join(str(labels[c]) for c in data['category']))
        if data.get('iarc_group'):
            parts.append(f'in IARC Group {data["iarc_group"]}')
        return parts
```

Then, still in `views.py`, add the redirect view and *temporary* placeholders so the URL conf resolves (Tasks 6–9 replace them):

```python
class ExplorerRedirect(vanilla.GenericView):
    model = None

    def get(self, request, sqid):
        obj = self.model.objects.filter(sqid=sqid).first()
        if obj is None:
            raise Http404
        return redirect(obj.get_absolute_url(), permanent=True)


class Home(vanilla.TemplateView):
    template_name = 'pesticides/home.html'


class ProductList(vanilla.TemplateView):
    template_name = 'pesticides/product-list.html'


class CommodityList(vanilla.TemplateView):
    template_name = 'pesticides/commodity-list.html'


class ChemicalDetail(vanilla.TemplateView):
    template_name = 'pesticides/chemical-detail.html'


class ProductDetail(vanilla.TemplateView):
    template_name = 'pesticides/product-detail.html'


class CommodityDetail(vanilla.TemplateView):
    template_name = 'pesticides/commodity-detail.html'
```

- [ ] **Step 6: URL conf and mount**

Create `camp/apps/pesticides/urls.py`:

```python
from django.urls import path

from camp.apps.pesticides import views
from camp.apps.pesticides.models import Chemical, Commodity, Product

urlpatterns = [
    path('', views.Home.as_view(), name='home'),

    path('chemicals/', views.ChemicalList.as_view(), name='chemical-list'),
    path('chemicals/<str:sqid>/', views.ExplorerRedirect.as_view(model=Chemical), name='chemical-redirect'),
    path('chemicals/<str:sqid>/<slug:slug>/', views.ChemicalDetail.as_view(), name='chemical-detail'),

    path('products/', views.ProductList.as_view(), name='product-list'),
    path('products/<str:sqid>/', views.ExplorerRedirect.as_view(model=Product), name='product-redirect'),
    path('products/<str:sqid>/<slug:slug>/', views.ProductDetail.as_view(), name='product-detail'),

    path('commodities/', views.CommodityList.as_view(), name='commodity-list'),
    path('commodities/<str:sqid>/', views.ExplorerRedirect.as_view(model=Commodity), name='commodity-redirect'),
    path('commodities/<str:sqid>/<slug:slug>/', views.CommodityDetail.as_view(), name='commodity-detail'),
]
```

In `camp/urls.py`, add after the `support/` line:

```python
    path('tools/pesticides/', include(('camp.apps.pesticides.urls', 'pesticides'), namespace='pesticides')),
```

- [ ] **Step 7: Templates**

`camp/templates/pesticides/base.html`:

```django
{% extends 'page.html' %}
{% load static %}

{% block title %}Pesticides Explorer | {{ block.super }}{% endblock %}
{% block body-class %}pesticides{% endblock %}

{% block extra-head %}
<link rel="stylesheet" href="{% static 'js/admin/leaflet/leaflet.css' %}">
<link rel="stylesheet" href="{% static 'js/admin/leaflet-maps.css' %}">
{% endblock %}

{% block javascripts %}
<script src="{% static 'js/admin/leaflet/leaflet.js' %}"></script>
<script src="{% static 'js/admin/leaflet-maps.js' %}"></script>
{% endblock %}

{% block main %}
<section class="section is-small hook">
    <div class="container">
        {% block explorer-header %}
        <div class="content">
            <h1 class="is-size-2 mb-1"><a href="{% url 'pesticides:home' %}">Pesticides Explorer</a></h1>
            <p class="lede">Which pesticides are applied in the San Joaquin Valley, where, and on what.</p>
        </div>
        {% endblock %}
        <div class="tabs is-boxed explorer-nav">
            <ul>
                <li class="{% if section == 'chemicals' %}is-active{% endif %}"><a href="{% url 'pesticides:chemical-list' %}">Chemicals</a></li>
                <li class="{% if section == 'products' %}is-active{% endif %}"><a href="{% url 'pesticides:product-list' %}">Products</a></li>
                <li class="{% if section == 'commodities' %}is-active{% endif %}"><a href="{% url 'pesticides:commodity-list' %}">Commodities</a></li>
            </ul>
        </div>
    </div>
</section>

<section class="breadcrumbs">
    <div class="container">
        <nav class="breadcrumb" aria-label="breadcrumbs">
            <ul>
                <li><a href="{% url 'pesticides:home' %}">Pesticides Explorer</a></li>
                {% block breadcrumb-list %}{% endblock %}
            </ul>
        </nav>
    </div>
</section>

<section class="section">
    <div class="container">
        {% block explorer-content %}{% endblock %}
    </div>
</section>
{% endblock %}
```

`camp/templates/pesticides/includes/filter-form.html` (expects `form`, `related`):

```django
<form method="GET" class="explorer-filters box">
    {% for param, obj in related.items %}
        <input type="hidden" name="{{ param }}" value="{{ obj.sqid }}">
    {% endfor %}
    <div class="field">
        <label class="label" for="id_q">Search</label>
        <div class="control has-icons-left">
            <input id="id_q" class="input" type="search" name="q" value="{{ form.q.value|default:'' }}" placeholder="Name or ID">
            <span class="icon is-small is-left"><span class="fas fa-search"></span></span>
        </div>
    </div>
    {% for field in form %}
        {% if field.name != 'q' %}
        <div class="field">
            <label class="label">{{ field.label }}</label>
            <div class="control">
                {% if field.field.widget.input_type == 'select' %}
                    <div class="select is-fullwidth">{{ field }}</div>
                {% else %}
                    {{ field }}
                {% endif %}
            </div>
        </div>
        {% endif %}
    {% endfor %}
    <div class="field is-grouped">
        <div class="control"><button class="button is-link" type="submit">Apply</button></div>
        <div class="control"><a class="button is-light" href="{{ request.path }}">Clear</a></div>
    </div>
</form>
```

`camp/templates/pesticides/includes/pagination.html` (expects `page_obj`, `is_paginated`):

```django
{% load pesticides_explorer %}
{% if is_paginated %}
<nav class="pagination is-centered mt-5" role="navigation" aria-label="pagination">
    {% if page_obj.has_previous %}
        <a class="pagination-previous" href="{% qs_replace page=page_obj.previous_page_number %}">Previous</a>
    {% else %}
        <a class="pagination-previous" disabled>Previous</a>
    {% endif %}
    {% if page_obj.has_next %}
        <a class="pagination-next" href="{% qs_replace page=page_obj.next_page_number %}">Next</a>
    {% else %}
        <a class="pagination-next" disabled>Next</a>
    {% endif %}
    <ul class="pagination-list">
        <li><span class="pagination-ellipsis">Page {{ page_obj.number }} of {{ page_obj.paginator.num_pages }}</span></li>
    </ul>
</nav>
{% endif %}
```

`camp/templates/pesticides/includes/classification-badges.html` (expects `chemical`; used for chemical rows and headers):

```django
{% if chemical.is_prop65 %}
    <a class="tag is-danger is-light" href="{% url 'pesticides:home' %}#prop65" title="Listed under California's Proposition 65 as a carcinogen, reproductive toxin, or developmental toxin">Prop 65</a>
{% endif %}
{% if chemical.is_tac %}
    <a class="tag is-warning is-light" href="{% url 'pesticides:home' %}#tac" title="Designated a Toxic Air Contaminant by the California Air Resources Board">CARB TAC</a>
{% endif %}
{% if chemical.iarc_group %}
    <a class="tag {% if chemical.is_iarc_concern %}is-danger{% else %}is-light{% endif %}" href="{% url 'pesticides:home' %}#iarc" title="{{ chemical.get_iarc_group_display }}">IARC {{ chemical.iarc_group }}</a>
{% endif %}
```

`camp/templates/pesticides/chemical-list.html`:

```django
{% extends 'pesticides/base.html' %}
{% load pesticides_explorer %}

{% block title %}Chemicals | {{ block.super }}{% endblock %}
{% block body-class %}{{ block.super }} chemical-list{% endblock %}
{% block breadcrumb-list %}<li class="is-active"><a aria-current="page">Chemicals</a></li>{% endblock %}

{% block explorer-content %}
<div class="columns">
    <div class="column is-3-desktop">
        {% include 'pesticides/includes/filter-form.html' %}
    </div>
    <div class="column">
        <p class="summary-sentence mb-3">
            {{ summary_sentence }}
            {% for param, obj in related.items %}
                <a class="tag is-info is-light ml-2" href="{% qs_replace page=None product=None commodity=None %}">clear ×</a>
            {% endfor %}
        </p>
        <div class="table-container">
            <table class="table is-fullwidth is-striped is-hoverable data-table">
                <thead>
                    <tr>
                        <th>{% sort_link 'name' 'Chemical' %}</th>
                        <th>Categories</th>
                        <th>{% sort_link 'iarc' 'IARC' %}</th>
                        <th class="has-text-right">{% sort_link 'products' 'Products' %}</th>
                        <th class="has-text-right">{% sort_link 'lbs' 'Lbs applied' %}{% if latest_year %} <small>({{ latest_year }})</small>{% endif %}</th>
                    </tr>
                </thead>
                <tbody>
                    {% for chemical in object_list %}
                    <tr>
                        <td><a href="{{ chemical.get_absolute_url }}">{{ chemical.name }}</a></td>
                        <td>
                            <div class="tags">
                                {% include 'pesticides/includes/classification-badges.html' %}
                                {% for category in chemical.categories %}
                                    <a class="tag" href="{% url 'pesticides:chemical-list' %}?category={{ category }}">{{ category|title|cut:'_' }}</a>
                                {% endfor %}
                            </div>
                        </td>
                        <td>{{ chemical.iarc_group|default:'—' }}</td>
                        <td class="has-text-right">{{ chemical.product_count }}</td>
                        <td class="has-text-right">{{ chemical.lbs_applied|lbs }}</td>
                    </tr>
                    {% empty %}
                    <tr><td colspan="5" class="has-text-centered has-text-grey">No chemicals match.</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% include 'pesticides/includes/pagination.html' %}
    </div>
</div>
{% endblock %}
```

Also create empty placeholder templates so the placeholder views don't 500 if hit: `camp/templates/pesticides/home.html`, `product-list.html`, `commodity-list.html`, `chemical-detail.html`, `product-detail.html`, `commodity-detail.html`, each containing only `{% extends 'pesticides/base.html' %}`. Tasks 6–9 overwrite them.

For the category tag label, the `{{ category|title|cut:'_' }}` hack renders "Toxic Air Contaminant" as "ToxicAirContaminant"; replace it with a proper label. Add to the template tag module:

```python
@register.filter
def category_label(value):
    from camp.apps.pesticides.models import Chemical
    return dict(Chemical.Category.choices).get(value, value)
```

and use `{{ category|category_label }}` in the row.

- [ ] **Step 8: Run the tests**

Run: `docker compose run --rm test pytest camp/apps/pesticides/tests/test_views.py camp/apps/pesticides/tests/test_models.py -q`
Expected: all `ChemicalListTests` and the `AbsoluteUrlTests` from Task 2 pass. If `test_default_sort_is_lbs_desc` fails with a `None` in the lbs list, the subquery is returning null for a chemical with no rows in the latest year; that's correct for real data but not for the fixture, so re-check the fixture years.

- [ ] **Step 9: Commit**

```bash
git add camp/apps/pesticides/urls.py camp/apps/pesticides/forms.py camp/apps/pesticides/views.py camp/apps/pesticides/templatetags/ camp/templates/pesticides/ camp/urls.py camp/apps/pesticides/tests/test_views.py
git commit -m "feat(pesticides): add explorer URLs, list mixin, and chemical list page"
```

---

### Task 6: Product and commodity lists

**Files:**
- Modify: `camp/apps/pesticides/views.py` (replace `ProductList`, `CommodityList` placeholders)
- Create: `camp/templates/pesticides/product-list.html`, `camp/templates/pesticides/commodity-list.html` (overwrite placeholders)
- Test: `camp/apps/pesticides/tests/test_views.py`

**Interfaces:**
- Consumes `ExplorerListMixin`, `lbs_subquery`, `related_pks` from Task 5.
- Produces annotations: Product rows have `chemical_count`, `lbs_applied` (from `lbs_product`); Commodity rows have `chemical_count` (distinct chemicals in latest year), `lbs_applied`.

- [ ] **Step 1: Write failing tests**

Append to `camp/apps/pesticides/tests/test_views.py`:

```python
class ProductListTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.url = reverse('pesticides:product-list')

    def names(self, response):
        return [p.name for p in response.context['object_list']]

    def test_renders_sorted_by_name(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert self.names(response) == ['LORSBAN 4E', 'ROUNDUP PRO', 'SULFUR DUST']

    def test_lbs_uses_lbs_product(self):
        response = self.client.get(self.url, {'sort': '-lbs'})
        rows = response.context['object_list']
        assert [(p.name, p.lbs_applied) for p in rows] == [('SULFUR DUST', 550.0), ('ROUNDUP PRO', 450.0), ('LORSBAN 4E', 135.0)]

    def test_fumigant_filter(self):
        assert self.names(self.client.get(self.url, {'fumigant': 'true'})) == ['LORSBAN 4E']
        assert self.names(self.client.get(self.url, {'fumigant': 'false'})) == ['ROUNDUP PRO', 'SULFUR DUST']

    def test_restricted_filter(self):
        assert self.names(self.client.get(self.url, {'california_restricted': 'true'})) == ['LORSBAN 4E']

    def test_search_by_reg_number(self):
        assert self.names(self.client.get(self.url, {'q': '524-475'})) == ['ROUNDUP PRO']

    def test_related_chemical(self):
        chem = Chemical.objects.get(pk=1)
        assert self.names(self.client.get(self.url, {'chemical': chem.sqid})) == ['ROUNDUP PRO']

    def test_related_commodity(self):
        commodity = Commodity.objects.get(pk=2)   # GRAPE: roundup + sulfur dust
        assert self.names(self.client.get(self.url, {'commodity': commodity.sqid})) == ['ROUNDUP PRO', 'SULFUR DUST']

    def test_chemical_count(self):
        response = self.client.get(self.url)
        assert [p.chemical_count for p in response.context['object_list']] == [1, 1, 1]


class CommodityListTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.url = reverse('pesticides:commodity-list')

    def names(self, response):
        return [c.name for c in response.context['object_list']]

    def test_default_sort_lbs(self):
        response = self.client.get(self.url)
        assert self.names(response) == ['GRAPE', 'ALMOND', 'COTTON']
        assert [c.lbs_applied for c in response.context['object_list']] == [550.0, 150.0, 40.0]

    def test_chemical_count_latest_year(self):
        response = self.client.get(self.url)
        assert [(c.name, c.chemical_count) for c in response.context['object_list']] == [('GRAPE', 2), ('ALMOND', 2), ('COTTON', 1)]

    def test_search_site_code(self):
        assert self.names(self.client.get(self.url, {'q': '2500'})) == ['COTTON']

    def test_related_chemical(self):
        chem = Chemical.objects.get(pk=2)
        assert set(self.names(self.client.get(self.url, {'chemical': chem.sqid}))) == {'ALMOND', 'COTTON'}

    def test_related_product(self):
        product = Product.objects.get(pk=3)
        assert self.names(self.client.get(self.url, {'product': product.sqid})) == ['GRAPE']
```

- [ ] **Step 2: Run to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/pesticides/tests/test_views.py -k "ProductList or CommodityList" -q`
Expected: FAIL (placeholder views have no `object_list`, KeyError on context).

- [ ] **Step 3: Implement the views**

Replace the `ProductList` and `CommodityList` placeholders in `views.py`:

```python
class ProductList(ExplorerListMixin, vanilla.ListView):
    model = Product
    form_class = ProductFilterForm
    template_name = 'pesticides/product-list.html'
    section = 'products'
    sort_fields = {'name': 'name', 'lbs': 'lbs_applied', 'chemicals': 'chemical_count', 'reg': 'reg_number'}
    default_sort = 'name'
    related_models = {'chemical': Chemical, 'commodity': Commodity}

    def filter_related(self, queryset, param, obj):
        if param == 'chemical':
            return queryset.filter(product_chemicals__chemical=obj)
        return queryset.filter(pk__in=related_pks('commodity', obj, 'product'))

    def apply_filters(self, queryset, data):
        for name in ('fumigant', 'california_restricted'):
            value = self.form.bool_value(name)
            if value is not None:
                queryset = queryset.filter(**{name: value})
        return queryset

    def annotate_queryset(self, queryset, year):
        queryset = queryset.annotate(chemical_count=Count('product_chemicals', distinct=True))
        if year:
            queryset = queryset.annotate(lbs_applied=lbs_subquery('product', year, lbs_field='lbs_product'))
        else:
            queryset = queryset.annotate(lbs_applied=F('prodno') * 0.0)
        return queryset

    def describe_filters(self, data):
        parts = []
        if self.form.bool_value('fumigant') is True:
            parts.append('that are fumigants')
        if self.form.bool_value('fumigant') is False:
            parts.append('that are not fumigants')
        if self.form.bool_value('california_restricted') is True:
            parts.append('restricted in California')
        if self.form.bool_value('california_restricted') is False:
            parts.append('not restricted in California')
        return parts


class CommodityList(ExplorerListMixin, vanilla.ListView):
    model = Commodity
    form_class = CommodityFilterForm
    template_name = 'pesticides/commodity-list.html'
    section = 'commodities'
    sort_fields = {'name': 'name', 'lbs': 'lbs_applied', 'chemicals': 'chemical_count', 'site': 'site_code'}
    default_sort = '-lbs'
    related_models = {'chemical': Chemical, 'product': Product}

    def filter_related(self, queryset, param, obj):
        return queryset.filter(pk__in=related_pks(param, obj, 'commodity'))

    def annotate_queryset(self, queryset, year):
        if not year:
            return queryset.annotate(lbs_applied=F('pk') * 0.0, chemical_count=F('pk') * 0)
        chemical_count = Subquery(
            PesticideUse.objects
            .filter(commodity=OuterRef('pk'), year=year)
            .values('commodity')
            .annotate(n=Count('chemical', distinct=True))
            .values('n'),
        )
        return queryset.annotate(
            lbs_applied=lbs_subquery('commodity', year),
            chemical_count=chemical_count,
        )
```

Note `F('pk') * 0` for the empty-DB case keeps the annotation names present so templates and sorts never break; the value is always 0.

- [ ] **Step 4: Templates**

`camp/templates/pesticides/product-list.html`:

```django
{% extends 'pesticides/base.html' %}
{% load pesticides_explorer %}

{% block title %}Products | {{ block.super }}{% endblock %}
{% block body-class %}{{ block.super }} product-list{% endblock %}
{% block breadcrumb-list %}<li class="is-active"><a aria-current="page">Products</a></li>{% endblock %}

{% block explorer-content %}
<div class="columns">
    <div class="column is-3-desktop">
        {% include 'pesticides/includes/filter-form.html' %}
    </div>
    <div class="column">
        <p class="summary-sentence mb-3">
            {{ summary_sentence }}
            {% if related %}<a class="tag is-info is-light ml-2" href="{% qs_replace page=None chemical=None commodity=None %}">clear ×</a>{% endif %}
        </p>
        <div class="table-container">
            <table class="table is-fullwidth is-striped is-hoverable data-table">
                <thead>
                    <tr>
                        <th>{% sort_link 'name' 'Product' %}</th>
                        <th>{% sort_link 'reg' 'Reg. number' %}</th>
                        <th>Flags</th>
                        <th class="has-text-right">{% sort_link 'chemicals' 'Active ingredients' %}</th>
                        <th class="has-text-right">{% sort_link 'lbs' 'Lbs applied' %}{% if latest_year %} <small>({{ latest_year }})</small>{% endif %}</th>
                    </tr>
                </thead>
                <tbody>
                    {% for product in object_list %}
                    <tr>
                        <td><a href="{{ product.get_absolute_url }}">{{ product.name }}</a></td>
                        <td><a href="{{ product.get_absolute_url }}">{{ product.reg_number }}</a></td>
                        <td>
                            <div class="tags">
                                {% if product.fumigant %}<a class="tag is-warning is-light" href="{% url 'pesticides:product-list' %}?fumigant=true">Fumigant</a>{% endif %}
                                {% if product.california_restricted %}<a class="tag is-danger is-light" href="{% url 'pesticides:product-list' %}?california_restricted=true">CA restricted</a>{% endif %}
                            </div>
                        </td>
                        <td class="has-text-right">{{ product.chemical_count }}</td>
                        <td class="has-text-right">{{ product.lbs_applied|lbs }}</td>
                    </tr>
                    {% empty %}
                    <tr><td colspan="5" class="has-text-centered has-text-grey">No products match.</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% include 'pesticides/includes/pagination.html' %}
    </div>
</div>
{% endblock %}
```

`camp/templates/pesticides/commodity-list.html`:

```django
{% extends 'pesticides/base.html' %}
{% load pesticides_explorer %}

{% block title %}Commodities | {{ block.super }}{% endblock %}
{% block body-class %}{{ block.super }} commodity-list{% endblock %}
{% block breadcrumb-list %}<li class="is-active"><a aria-current="page">Commodities</a></li>{% endblock %}

{% block explorer-content %}
<div class="columns">
    <div class="column is-3-desktop">
        {% include 'pesticides/includes/filter-form.html' %}
    </div>
    <div class="column">
        <p class="summary-sentence mb-3">
            {{ summary_sentence }}
            {% if related %}<a class="tag is-info is-light ml-2" href="{% qs_replace page=None chemical=None product=None %}">clear ×</a>{% endif %}
        </p>
        <div class="table-container">
            <table class="table is-fullwidth is-striped is-hoverable data-table">
                <thead>
                    <tr>
                        <th>{% sort_link 'name' 'Commodity' %}</th>
                        <th>{% sort_link 'site' 'Site code' %}</th>
                        <th class="has-text-right">{% sort_link 'chemicals' 'Chemicals' %}{% if latest_year %} <small>({{ latest_year }})</small>{% endif %}</th>
                        <th class="has-text-right">{% sort_link 'lbs' 'Lbs applied' %}{% if latest_year %} <small>({{ latest_year }})</small>{% endif %}</th>
                    </tr>
                </thead>
                <tbody>
                    {% for commodity in object_list %}
                    <tr>
                        <td><a href="{{ commodity.get_absolute_url }}">{{ commodity.name }}</a></td>
                        <td>{{ commodity.site_code }}</td>
                        <td class="has-text-right">{{ commodity.chemical_count|default:0 }}</td>
                        <td class="has-text-right">{{ commodity.lbs_applied|lbs }}</td>
                    </tr>
                    {% empty %}
                    <tr><td colspan="4" class="has-text-centered has-text-grey">No commodities match.</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% include 'pesticides/includes/pagination.html' %}
    </div>
</div>
{% endblock %}
```

- [ ] **Step 5: Run tests**

Run: `docker compose run --rm test pytest camp/apps/pesticides/tests/test_views.py -q`
Expected: all list tests pass.

- [ ] **Step 6: Commit**

```bash
git add camp/apps/pesticides/views.py camp/templates/pesticides/product-list.html camp/templates/pesticides/commodity-list.html camp/apps/pesticides/tests/test_views.py
git commit -m "feat(pesticides): add product and commodity list pages"
```

---

### Task 7: Detail views and templates

**Files:**
- Modify: `camp/apps/pesticides/views.py` (replace the three detail placeholders)
- Create/overwrite: `camp/templates/pesticides/detail-base.html`, `chemical-detail.html`, `product-detail.html`, `commodity-detail.html`, `includes/stat-row.html`, `includes/related-card.html`, `includes/by-year-table.html`, `includes/by-county-table.html`, `includes/recent-uses.html`, `includes/upcoming-notices.html`
- Test: `camp/apps/pesticides/tests/test_views.py`

**Interfaces:**
- Consumes everything from `stats.py` (Task 4) and the URL names from Task 5.
- Produces `ExplorerDetailMixin` context keys: `object`, `latest_year`, `years`, `totals` (`year_totals` dict), `county_total` (8), `by_year`, `by_county`, `related_a`, `related_b` (each a dict `{title, rows, show_all_url, kind}`), `recent_uses`, `upcoming`, `upcoming_by_county`, `upcoming_count`, `notice_window`, `summary_sentence`, `api_uses_url`, `api_notices_url`, `section`, `has_notices` (bool; False for commodities).

- [ ] **Step 1: Write failing tests**

Append to `camp/apps/pesticides/tests/test_views.py`:

```python
class ChemicalDetailTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.chemical = Chemical.objects.get(pk=1)

    def test_renders_with_slug(self):
        response = self.client.get(self.chemical.get_absolute_url())
        assert response.status_code == 200
        self.assertTemplateUsed(response, 'pesticides/chemical-detail.html')
        assert response.context['object'] == self.chemical

    def test_wrong_slug_still_resolves(self):
        url = reverse('pesticides:chemical-detail', kwargs={'sqid': self.chemical.sqid, 'slug': 'whatever'})
        assert self.client.get(url).status_code == 200

    def test_bare_sqid_redirects(self):
        response = self.client.get(reverse('pesticides:chemical-redirect', kwargs={'sqid': self.chemical.sqid}))
        assert response.status_code == 301
        assert response['Location'] == self.chemical.get_absolute_url()

    def test_bad_sqid_404(self):
        assert self.client.get('/tools/pesticides/chemicals/nope/x/').status_code == 404
        assert self.client.get('/tools/pesticides/chemicals/nope/').status_code == 404

    def test_totals_and_tables(self):
        ctx = self.client.get(self.chemical.get_absolute_url()).context
        assert ctx['totals'] == {'lbs': 180.0, 'applications': 3, 'counties': 2}
        assert [r['year'] for r in ctx['by_year']] == [2023, 2022]
        assert [r['county_name'] for r in ctx['by_county']] == ['Fresno County', 'Kern County']
        assert ctx['years'] == (2022, 2023)

    def test_related(self):
        ctx = self.client.get(self.chemical.get_absolute_url()).context
        assert ctx['related_a']['kind'] == 'products'
        assert [(r.obj.name, r.pct_active) for r in ctx['related_a']['rows']] == [('ROUNDUP PRO', 41.0)]
        assert [r.obj.name for r in ctx['related_b']['rows']] == ['ALMOND', 'GRAPE']
        assert ctx['related_b']['show_all_url'] == reverse('pesticides:commodity-list') + f'?chemical={self.chemical.sqid}'

    def test_notices_split(self):
        ctx = self.client.get(Chemical.objects.get(pk=2).get_absolute_url()).context
        assert [n.pk for n in ctx['upcoming']] == [2, 3]
        assert ctx['upcoming_count'] == 2
        assert ctx['upcoming_by_county'][0]['county_name'] == 'Fresno County'

    def test_summary_sentence(self):
        ctx = self.client.get(self.chemical.get_absolute_url()).context
        assert ctx['summary_sentence'] == 'Applied in 2 of 8 SJV counties in 2023, mostly on Almond and Grape.'

    def test_badges_and_links_render(self):
        html = self.client.get(self.chemical.get_absolute_url()).content.decode()
        assert 'Prop 65' in html
        assert 'IARC 2A' in html
        assert 'comptox.epa.gov' in html
        assert '/api/2.0/pesticides/use/?chemical=1855' in html
        assert Product.objects.get(pk=1).get_absolute_url() in html

    def test_query_ceiling(self):
        with self.assertNumQueries(20):
            self.client.get(self.chemical.get_absolute_url())

    def test_no_uses_renders_empty_state(self):
        chem = Chemical.objects.create(chem_code=4242, name='NOTHING')
        response = self.client.get(chem.get_absolute_url())
        assert response.status_code == 200
        assert response.context['totals']['applications'] == 0
        assert 'No confirmed applications' in response.content.decode()


class ProductDetailTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.product = Product.objects.get(pk=2)

    def test_renders_with_ingredients(self):
        ctx = self.client.get(self.product.get_absolute_url()).context
        assert ctx['related_a']['kind'] == 'chemicals'
        assert [(r.obj.name, r.pct_active) for r in ctx['related_a']['rows']] == [('CHLORPYRIFOS', 44.9)]
        assert [r.obj.name for r in ctx['related_b']['rows']] == ['COTTON', 'ALMOND']

    def test_totals_use_lbs_product(self):
        ctx = self.client.get(self.product.get_absolute_url()).context
        assert ctx['totals']['lbs'] == 135.0

    def test_inherited_badges(self):
        html = self.client.get(self.product.get_absolute_url()).content.decode()
        assert 'CARB TAC' in html
        assert 'Fumigant' in html
        assert 'CA restricted' in html

    def test_bare_sqid_redirects(self):
        response = self.client.get(reverse('pesticides:product-redirect', kwargs={'sqid': self.product.sqid}))
        assert response.status_code == 301


class CommodityDetailTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.commodity = Commodity.objects.get(pk=2)

    def test_renders(self):
        ctx = self.client.get(self.commodity.get_absolute_url()).context
        assert ctx['totals'] == {'lbs': 550.0, 'applications': 2, 'counties': 1}
        assert [r.obj.name for r in ctx['related_a']['rows']] == ['SULFUR', 'GLYPHOSATE']
        assert [r.obj.name for r in ctx['related_b']['rows']] == ['SULFUR DUST', 'ROUNDUP PRO']
        assert ctx['has_notices'] is False

    def test_summary_sentence_uses_chemicals(self):
        ctx = self.client.get(self.commodity.get_absolute_url()).context
        assert ctx['summary_sentence'] == 'Applied in 1 of 8 SJV counties in 2023, mostly Sulfur and Glyphosate.'

    def test_no_notice_section(self):
        html = self.client.get(self.commodity.get_absolute_url()).content.decode()
        assert 'do not include the crop' in html
```

- [ ] **Step 2: Run to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/pesticides/tests/test_views.py -k "Detail" -q`
Expected: FAIL (placeholder `TemplateView` has no `object`).

- [ ] **Step 3: Implement the views**

Replace the three detail placeholders in `views.py`. Add `from django.urls import reverse` and `from types import SimpleNamespace` at the top.

```python
class ExplorerDetailMixin:
    lookup_field = 'sqid'
    lookup_url_kwarg = 'sqid'
    section = None
    lbs_field = 'lbs_chemical'
    use_field = None          # PesticideUse FK name for this entity
    api_param = None          # v2 API query param name
    has_notices = True

    def get_uses(self):
        return PesticideUse.objects.filter(**{self.use_field: self.object})

    def get_notices(self):
        return PesticideNotice.objects.none()

    def api_value(self):
        raise NotImplementedError

    def get_related(self, year):
        """Return (related_a, related_b) dicts. Each: {title, kind, rows, show_all_url}."""
        raise NotImplementedError

    def related_card(self, title, kind, rows, list_url_name, param):
        return {
            'title': title,
            'kind': kind,
            'rows': rows,
            'show_all_url': reverse(list_url_name) + f'?{param}={self.object.sqid}',
        }

    def get_summary_sentence(self, totals, year, top, verb='on'):
        if not totals['applications'] or year is None:
            return ''
        sentence = f'Applied in {totals["counties"]} of {stats.SJV_COUNTY_COUNT} SJV counties in {year}'
        names = [r.obj.name.title() for r in top[:2]]
        if names:
            joined = ' and '.join(names)
            sentence += f', mostly {verb} {joined}' if verb else f', mostly {joined}'
        return sentence + '.'

    def get_context_data(self, **kwargs):
        year = stats.latest_year()
        uses = self.get_uses()
        notices = self.get_notices()
        totals = stats.year_totals(uses, year, self.lbs_field) if year else {'lbs': 0, 'applications': 0, 'counties': 0}
        related_a, related_b = self.get_related(year)
        context = super().get_context_data(
            section=self.section,
            latest_year=year,
            years=stats.years_loaded(),
            county_total=stats.SJV_COUNTY_COUNT,
            totals=totals,
            by_year=stats.by_year(uses, self.lbs_field),
            by_county=stats.by_county(uses, year, self.lbs_field) if year else [],
            related_a=related_a,
            related_b=related_b,
            recent_uses=stats.recent_uses(uses),
            has_notices=self.has_notices,
            upcoming=stats.upcoming_notices(notices) if self.has_notices else [],
            upcoming_by_county=stats.upcoming_by_county(notices) if self.has_notices else [],
            upcoming_count=stats.upcoming_count(notices) if self.has_notices else 0,
            notice_window=stats.notice_window(),
            api_uses_url=f'/api/2.0/pesticides/use/?{self.api_param}={self.api_value()}',
            api_notices_url=f'/api/2.0/pesticides/notice/?{self.api_param}={self.api_value()}',
            **kwargs,
        )
        context['summary_sentence'] = self.get_summary_sentence(totals, year, self.summary_top(context))
        return context

    def summary_top(self, context):
        return context['related_b']['rows']


def with_pct_active(rows, pct_by_pk):
    for row in rows:
        row.pct_active = pct_by_pk.get(row.obj.pk)
    return rows


class ChemicalDetail(ExplorerDetailMixin, vanilla.DetailView):
    model = Chemical
    template_name = 'pesticides/chemical-detail.html'
    section = 'chemicals'
    use_field = 'chemical'
    api_param = 'chemical'

    def api_value(self):
        return self.object.chem_code

    def get_notices(self):
        return PesticideNotice.objects.filter(chemicals=self.object)

    def get_related(self, year):
        uses = self.get_uses()
        pct = dict(self.object.product_chemicals.values_list('product_id', 'pct_active'))
        products = with_pct_active(stats.top_related(uses, year, 'product', self.lbs_field), pct)
        commodities = stats.top_related(uses, year, 'commodity', self.lbs_field)
        return (
            self.related_card('Products containing this chemical', 'products', products, 'pesticides:product-list', 'chemical'),
            self.related_card('Applied to', 'commodities', commodities, 'pesticides:commodity-list', 'chemical'),
        )


class ProductDetail(ExplorerDetailMixin, vanilla.DetailView):
    model = Product
    template_name = 'pesticides/product-detail.html'
    section = 'products'
    use_field = 'product'
    lbs_field = 'lbs_product'
    api_param = 'product'

    def get_queryset(self):
        return Product.objects.prefetch_related('chemicals')

    def api_value(self):
        return self.object.prodno

    def get_notices(self):
        return PesticideNotice.objects.filter(products=self.object)

    def get_related(self, year):
        uses = self.get_uses()
        pct = dict(self.object.product_chemicals.values_list('chemical_id', 'pct_active'))
        # Active ingredients are a property of the product, not of use records,
        # so list all of them (ranked by pct_active) rather than by pounds.
        chemicals = [
            SimpleNamespace(obj=c, lbs=None, pct_active=pct.get(c.pk))
            for c in sorted(self.object.chemicals.all(), key=lambda c: -(pct.get(c.pk) or 0))
        ]
        commodities = stats.top_related(uses, year, 'commodity', self.lbs_field)
        return (
            self.related_card('Active ingredients', 'chemicals', chemicals, 'pesticides:chemical-list', 'product'),
            self.related_card('Applied to', 'commodities', commodities, 'pesticides:commodity-list', 'product'),
        )


class CommodityDetail(ExplorerDetailMixin, vanilla.DetailView):
    model = Commodity
    template_name = 'pesticides/commodity-detail.html'
    section = 'commodities'
    use_field = 'commodity'
    api_param = 'commodity'
    has_notices = False

    def api_value(self):
        return self.object.site_code

    def get_related(self, year):
        uses = self.get_uses()
        return (
            self.related_card('Chemicals applied', 'chemicals', stats.top_related(uses, year, 'chemical'), 'pesticides:chemical-list', 'commodity'),
            self.related_card('Products applied', 'products', stats.top_related(uses, year, 'product', 'lbs_product'), 'pesticides:product-list', 'commodity'),
        )

    def summary_top(self, context):
        return context['related_a']['rows']

    def get_summary_sentence(self, totals, year, top, verb=None):
        return super().get_summary_sentence(totals, year, top, verb=None)
```

Note for `ProductDetail.test_renders_with_ingredients`: `related_b` for LORSBAN is commodities ranked by `lbs_product` in 2023: COTTON 90, ALMOND 45. Good.

- [ ] **Step 4: Templates**

`camp/templates/pesticides/includes/stat-row.html` (expects `totals`, `latest_year`, `county_total`, `upcoming_count`, `has_notices`):

```django
{% load pesticides_explorer %}
<div class="level stat-row box">
    <div class="level-item has-text-centered">
        <div><p class="heading">Lbs applied{% if latest_year %} in {{ latest_year }}{% endif %}</p><p class="title">{{ totals.lbs|lbs }}</p></div>
    </div>
    <div class="level-item has-text-centered">
        <div><p class="heading">Applications{% if latest_year %} in {{ latest_year }}{% endif %}</p><p class="title">{{ totals.applications|lbs }}</p></div>
    </div>
    <div class="level-item has-text-centered">
        <div><p class="heading">Counties</p><p class="title">{{ totals.counties }} <span class="is-size-5 has-text-grey">of {{ county_total }}</span></p></div>
    </div>
    {% if has_notices %}
    <div class="level-item has-text-centered">
        <div><p class="heading">Upcoming notices</p><p class="title">{{ upcoming_count }}</p></div>
    </div>
    {% endif %}
</div>
```

`camp/templates/pesticides/includes/related-card.html` (expects `card`, `latest_year`):

```django
{% load pesticides_explorer %}
<div class="card related-card">
    <header class="card-header"><p class="card-header-title">{{ card.title }}</p></header>
    <div class="card-content">
        {% if card.rows %}
        <table class="table is-fullwidth is-narrow">
            <thead><tr>
                <th>Name</th>
                {% if card.kind == 'chemicals' or card.kind == 'products' %}<th class="has-text-right">% active</th>{% endif %}
                <th class="has-text-right">Lbs{% if latest_year %} ({{ latest_year }}){% endif %}</th>
            </tr></thead>
            <tbody>
            {% for row in card.rows %}
                <tr>
                    <td>
                        <a href="{{ row.obj.get_absolute_url }}">{{ row.obj.name }}</a>
                        {% if card.kind == 'chemicals' %}<span class="tags is-inline ml-1">{% include 'pesticides/includes/classification-badges.html' with chemical=row.obj %}</span>{% endif %}
                    </td>
                    {% if card.kind == 'chemicals' or card.kind == 'products' %}<td class="has-text-right">{% if row.pct_active is not None %}{{ row.pct_active|floatformat:1 }}%{% else %}—{% endif %}</td>{% endif %}
                    <td class="has-text-right">{{ row.lbs|lbs }}</td>
                </tr>
            {% endfor %}
            </tbody>
        </table>
        {% else %}
        <p class="has-text-grey">None{% if latest_year %} in {{ latest_year }}{% endif %}.</p>
        {% endif %}
    </div>
    <footer class="card-footer"><a class="card-footer-item" href="{{ card.show_all_url }}">Show all</a></footer>
</div>
```

`camp/templates/pesticides/includes/by-year-table.html` (expects `by_year`):

```django
{% load pesticides_explorer %}
<table class="table is-fullwidth is-narrow is-striped">
    <thead><tr><th>Year</th><th class="has-text-right">Lbs</th><th class="has-text-right">Acres treated</th><th class="has-text-right">Applications</th></tr></thead>
    <tbody>
    {% for row in by_year %}
        <tr><td>{{ row.year }}</td><td class="has-text-right">{{ row.lbs|lbs }}</td><td class="has-text-right">{{ row.acres|lbs }}</td><td class="has-text-right">{{ row.applications|lbs }}</td></tr>
    {% endfor %}
    </tbody>
</table>
```

`camp/templates/pesticides/includes/by-county-table.html` (expects `by_county`, `latest_year`):

```django
{% load pesticides_explorer %}
<table class="table is-fullwidth is-narrow is-striped">
    <thead><tr><th>County ({{ latest_year }})</th><th class="has-text-right">Lbs</th><th class="has-text-right">Acres treated</th><th class="has-text-right">Applications</th></tr></thead>
    <tbody>
    {% for row in by_county %}
        <tr><td>{{ row.county_name }}</td><td class="has-text-right">{{ row.lbs|lbs }}</td><td class="has-text-right">{{ row.acres|lbs }}</td><td class="has-text-right">{{ row.applications|lbs }}</td></tr>
    {% endfor %}
    </tbody>
</table>
```

`camp/templates/pesticides/includes/recent-uses.html` (expects `recent_uses`, `section`):

```django
{% load pesticides_explorer %}
<table class="table is-fullwidth is-narrow is-striped">
    <thead><tr>
        <th>Date</th><th>County</th>
        {% if section != 'commodities' %}<th>Commodity</th>{% endif %}
        {% if section != 'products' %}<th>Product</th>{% endif %}
        {% if section != 'chemicals' %}<th>Chemical</th>{% endif %}
        <th class="has-text-right">Lbs</th><th>Method</th>
    </tr></thead>
    <tbody>
    {% for use in recent_uses %}
        <tr>
            <td>{{ use.application_date|date:'M j, Y'|default:'—' }}</td>
            <td>{{ use.county.name }}</td>
            {% if section != 'commodities' %}<td>{% if use.commodity %}<a href="{{ use.commodity.get_absolute_url }}">{{ use.commodity.name }}</a>{% else %}—{% endif %}</td>{% endif %}
            {% if section != 'products' %}<td>{% if use.product %}<a href="{{ use.product.get_absolute_url }}">{{ use.product.name }}</a>{% else %}—{% endif %}</td>{% endif %}
            {% if section != 'chemicals' %}<td>{% if use.chemical %}<a href="{{ use.chemical.get_absolute_url }}">{{ use.chemical.name }}</a>{% else %}—{% endif %}</td>{% endif %}
            <td class="has-text-right">{% if section == 'products' %}{{ use.lbs_product|lbs }}{% else %}{{ use.lbs_chemical|lbs }}{% endif %}</td>
            <td>{{ use.get_aerial_ground_display|default:'—' }}</td>
        </tr>
    {% endfor %}
    </tbody>
</table>
```

`camp/templates/pesticides/includes/upcoming-notices.html` (expects `upcoming`, `upcoming_by_county`, `object`):

```django
{% if upcoming_by_county %}
<div class="tags mb-3">
    {% for row in upcoming_by_county %}<span class="tag is-medium">{{ row.county_name }} <strong class="ml-1">{{ row.count }}</strong></span>{% endfor %}
</div>
{% endif %}
<table class="table is-fullwidth is-narrow is-striped">
    <thead><tr><th>Scheduled</th><th>County</th><th>Method</th><th class="has-text-right">Treated</th><th>Also on this notice</th></tr></thead>
    <tbody>
    {% for notice in upcoming %}
        <tr>
            <td>{{ notice.scheduled_application|date:'M j, Y' }}</td>
            <td>{{ notice.county.name|default:'—' }}</td>
            <td>{{ notice.application_method|default:'—' }}</td>
            <td class="has-text-right">{% if notice.treated_amount %}{{ notice.treated_amount|floatformat:1 }} {{ notice.treated_units|lower }}{% else %}—{% endif %}</td>
            <td>
                {% for chem in notice.chemicals.all %}{% if chem != object %}<a class="tag" href="{{ chem.get_absolute_url }}">{{ chem.name }}</a> {% endif %}{% endfor %}
                {% for product in notice.products.all %}{% if product != object %}<a class="tag is-light" href="{{ product.get_absolute_url }}">{{ product.name }}</a> {% endif %}{% endfor %}
            </td>
        </tr>
    {% endfor %}
    </tbody>
</table>
```

`camp/templates/pesticides/detail-base.html`:

```django
{% extends 'pesticides/base.html' %}
{% load pesticides_explorer %}

{% block title %}{{ object.name }} | {{ block.super }}{% endblock %}
{% block body-class %}{{ block.super }} detail{% endblock %}

{% block explorer-content %}
<div class="content detail-header">
    <h1 class="mb-1">{{ object.name }}</h1>
    <p class="identifiers has-text-grey">{% block identifiers %}{% endblock %}</p>
    <div class="tags are-medium">{% block badges %}{% endblock %}</div>
</div>

{% include 'pesticides/includes/stat-row.html' %}
{% if summary_sentence %}<p class="summary-sentence is-size-5 mb-5">{{ summary_sentence }}</p>{% endif %}

<div class="columns">
    <div class="column">{% include 'pesticides/includes/related-card.html' with card=related_a %}</div>
    <div class="column">{% include 'pesticides/includes/related-card.html' with card=related_b %}</div>
</div>

<section class="applications mt-6">
    <h2 class="title is-4">Confirmed applications <small class="has-text-grey is-size-6">Pesticide Use Reporting (PUR)</small></h2>
    {% if by_year %}
        <div class="columns">
            <div class="column">{% include 'pesticides/includes/by-year-table.html' %}</div>
            <div class="column">{% if by_county %}{% include 'pesticides/includes/by-county-table.html' %}{% endif %}</div>
        </div>
        <h3 class="title is-5 mt-5">Most recent records</h3>
        {% include 'pesticides/includes/recent-uses.html' %}
        <p><a href="{{ api_uses_url }}">View all records in the API</a></p>
    {% else %}
        <p class="has-text-grey">No confirmed applications on record{% if years %} for {{ years.0 }}–{{ years.1 }}{% endif %}.</p>
    {% endif %}
</section>

<section class="notices mt-6">
    <h2 class="title is-4">Planned applications <small class="has-text-grey is-size-6">SprayDays notices of intent</small></h2>
    {% if not has_notices %}
        <p class="has-text-grey">SprayDays notices do not include the crop, so planned applications can't be listed by commodity. See the chemical or product pages instead.</p>
    {% elif upcoming %}
        {% include 'pesticides/includes/upcoming-notices.html' %}
        <p><a href="{{ api_notices_url }}">View all notices in the API</a></p>
    {% else %}
        <p class="has-text-grey">No upcoming notices.</p>
    {% endif %}
</section>

<footer class="sources mt-6 has-text-grey is-size-7">
    <p>
        Confirmed applications: CDPR Pesticide Use Reporting{% if years %}, {{ years.0 }}–{{ years.1 }}{% endif %}.
        {% if notice_window %}Planned applications: SprayDays, {{ notice_window.count }} notices from {{ notice_window.first|date:'M j, Y' }} to {{ notice_window.last|date:'M j, Y' }}.{% endif %}
        <a href="{% url 'pesticides:home' %}#about">About this data</a>.
    </p>
</footer>
{% endblock %}
```

`camp/templates/pesticides/chemical-detail.html`:

```django
{% extends 'pesticides/detail-base.html' %}
{% block breadcrumb-list %}
    <li><a href="{% url 'pesticides:chemical-list' %}">Chemicals</a></li>
    <li class="is-active"><a aria-current="page">{{ object.name }}</a></li>
{% endblock %}
{% block identifiers %}
    Chemical code {{ object.chem_code }}{% if object.cas_number %} · CAS {{ object.cas_number }}{% endif %}{% if object.comptox_url %} · <a href="{{ object.comptox_url }}" target="_blank" rel="noopener">CompTox {{ object.dtxsid }}</a>{% endif %}
{% endblock %}
{% block badges %}
    {% include 'pesticides/includes/classification-badges.html' with chemical=object %}
    {% for category in object.categories %}<a class="tag" href="{% url 'pesticides:chemical-list' %}?category={{ category }}">{{ category|category_label }}</a>{% endfor %}
{% endblock %}
```

`camp/templates/pesticides/product-detail.html`:

```django
{% extends 'pesticides/detail-base.html' %}
{% block breadcrumb-list %}
    <li><a href="{% url 'pesticides:product-list' %}">Products</a></li>
    <li class="is-active"><a aria-current="page">{{ object.name }}</a></li>
{% endblock %}
{% block identifiers %}Registration {{ object.reg_number }} · Product no. {{ object.prodno }}{% endblock %}
{% block badges %}
    {% if object.fumigant %}<a class="tag is-warning is-light" href="{% url 'pesticides:product-list' %}?fumigant=true">Fumigant</a>{% endif %}
    {% if object.california_restricted %}<a class="tag is-danger is-light" href="{% url 'pesticides:product-list' %}?california_restricted=true">CA restricted</a>{% endif %}
    {% if object.contains_prop65 %}<a class="tag is-danger is-light" href="{% url 'pesticides:home' %}#prop65" title="Contains a Proposition 65 listed chemical">Prop 65</a>{% endif %}
    {% if object.contains_tac %}<a class="tag is-warning is-light" href="{% url 'pesticides:home' %}#tac" title="Contains a CARB Toxic Air Contaminant">CARB TAC</a>{% endif %}
    {% if object.contains_iarc %}<a class="tag is-danger" href="{% url 'pesticides:home' %}#iarc" title="Contains an IARC Group 1, 2A, or 2B chemical">IARC</a>{% endif %}
{% endblock %}
```

`camp/templates/pesticides/commodity-detail.html`:

```django
{% extends 'pesticides/detail-base.html' %}
{% block breadcrumb-list %}
    <li><a href="{% url 'pesticides:commodity-list' %}">Commodities</a></li>
    <li class="is-active"><a aria-current="page">{{ object.name }}</a></li>
{% endblock %}
{% block identifiers %}Site code {{ object.site_code }}{% endblock %}
{% block badges %}{% endblock %}
```

- [ ] **Step 5: Run tests**

Run: `docker compose run --rm test pytest camp/apps/pesticides/tests/test_views.py -q`
Expected: all pass. If `test_query_ceiling` fails, print the queries with `--capture=no` and `django.db.connection.queries`; look for a per-row query in `related-card.html` (`row.obj.get_absolute_url` is pure Python, but `classification-badges` on `row.obj` must not hit the DB) or in `upcoming-notices.html` (`notice.chemicals.all` must come from the prefetch). Fix the missing `select_related`/`prefetch_related` rather than raising the ceiling.

- [ ] **Step 6: Commit**

```bash
git add camp/apps/pesticides/views.py camp/templates/pesticides/ camp/apps/pesticides/tests/test_views.py
git commit -m "feat(pesticides): add chemical, product, and commodity detail pages"
```

---

### Task 8: County map module

**Files:**
- Create: `camp/apps/pesticides/maps.py`
- Create: `camp/templates/pesticides/includes/county-map.html`
- Modify: `camp/apps/pesticides/views.py` (`ExplorerDetailMixin.get_context_data` adds `county_map`)
- Modify: `camp/templates/pesticides/detail-base.html` (map beside the by-county table)
- Note: `assets/sass/sjvair/pages/pesticides.sass` is created in Task 10 and carries the fluid-width rule for the map container
- Test: `camp/apps/pesticides/tests/test_maps.py`, plus two tests added to `ChemicalDetailTests`

**Interfaces:**
- Consumes `camp.utils.leaflet.LeafletMap` / `Area` (already on main) and `stats.by_county()` rows (`county_id`, `county_name`, `lbs`).
- Produces:

```python
COUNTY_GEOJSON_KEY = 'pesticides:county-geometries'
COUNTY_GEOJSON_TTL = 60 * 60 * 24
SIMPLIFY_TOLERANCE = 0.005
RAMP = ['#deebf7', '#9ecae1', '#6baed6', '#3182bd', '#08519c']
NO_DATA = '#f0f0f0'

def county_geometries() -> dict[int, str]          # region pk -> simplified GeoJSON string, cached
def ramp_color(value, maximum) -> str
def county_map(by_county, year=None, width=600, height=420) -> str | None
    # HTML from LeafletMap.render(), or None when no county has a boundary
```

- [ ] **Step 1: Write failing tests**

Create `camp/apps/pesticides/tests/test_maps.py`:

```python
from django.core.cache import cache
from django.test import TestCase

from camp.apps.pesticides import maps
from camp.apps.regions.models import Region


class CountyGeometryTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()

    def test_returns_geojson_per_county(self):
        data = maps.county_geometries()
        assert set(data) == {9001, 9002}
        assert data[9001].startswith('{')
        assert 'MultiPolygon' in data[9001]

    def test_cached(self):
        maps.county_geometries()
        Region.objects.filter(pk=9002).update(boundary=None)
        assert set(maps.county_geometries()) == {9001, 9002}
        cache.clear()
        assert set(maps.county_geometries()) == {9001}

    def test_skips_counties_without_boundary(self):
        Region.objects.filter(pk=9002).update(boundary=None)
        assert set(maps.county_geometries()) == {9001}


class CountyMapTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.rows = [
            {'county_id': 9001, 'county_name': 'Fresno County', 'county_slug': 'fresno', 'lbs': 150.0, 'acres': 15, 'applications': 2},
        ]

    def test_renders_all_counties(self):
        html = maps.county_map(self.rows, year=2023)
        assert 'admin-leaflet-map' in html
        assert 'Fresno County' in html
        assert 'Kern County' in html      # drawn even with no rows

    def test_shading(self):
        html = maps.county_map(self.rows)
        assert maps.RAMP[-1] in html      # the max county gets the darkest step
        assert maps.NO_DATA in html       # a county with no rows is grey

    def test_ramp_steps(self):
        assert maps.ramp_color(0, 100) == maps.NO_DATA
        assert maps.ramp_color(1, 100) == maps.RAMP[0]
        assert maps.ramp_color(50, 100) == maps.RAMP[2]
        assert maps.ramp_color(100, 100) == maps.RAMP[-1]

    def test_none_without_geometries(self):
        Region.objects.filter(type='county').update(boundary=None)
        assert maps.county_map(self.rows) is None

    def test_labels_include_pounds(self):
        html = maps.county_map(self.rows)
        assert 'Fresno County: 150 lbs' in html
        assert 'Kern County: no data' in html
```

- [ ] **Step 2: Run to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/pesticides/tests/test_maps.py -q`
Expected: FAIL with `ImportError: cannot import name 'maps'`.

- [ ] **Step 3: Implement**

Create `camp/apps/pesticides/maps.py`:

```python
"""
County choropleth for the pesticides explorer, built on camp.utils.leaflet.
County boundaries are simplified and cached because the raw multipolygons
run to thousands of points each; simplified, all eight fit in ~33 KB.
"""
import math

from django.contrib.gis.geos import GEOSGeometry
from django.core.cache import cache

from camp.apps.regions.models import Region
from camp.utils import leaflet

COUNTY_GEOJSON_KEY = 'pesticides:county-geometries'
COUNTY_GEOJSON_TTL = 60 * 60 * 24
SIMPLIFY_TOLERANCE = 0.005
RAMP = ['#deebf7', '#9ecae1', '#6baed6', '#3182bd', '#08519c']
NO_DATA = '#f0f0f0'


def _build_county_geometries():
    data = {}
    regions = Region.objects.filter(type=Region.Type.COUNTY, boundary__isnull=False).select_related('boundary')
    for region in regions:
        geometry = region.boundary.geometry
        if geometry.srid and geometry.srid != 4326:
            geometry = geometry.transform(4326, clone=True)
        data[region.pk] = geometry.simplify(SIMPLIFY_TOLERANCE, preserve_topology=True).geojson
    return data


def county_geometries():
    data = cache.get(COUNTY_GEOJSON_KEY)
    if data is None:
        data = _build_county_geometries()
        cache.set(COUNTY_GEOJSON_KEY, data, COUNTY_GEOJSON_TTL)
    return data


def ramp_color(value, maximum):
    if not value or not maximum:
        return NO_DATA
    step = math.ceil(value / maximum * len(RAMP)) - 1
    return RAMP[max(0, min(step, len(RAMP) - 1))]


def county_map(by_county, year=None, width=600, height=420):
    geometries = county_geometries()
    if not geometries:
        return None
    names = dict(Region.objects.filter(pk__in=geometries).values_list('pk', 'name'))
    lbs_by_pk = {row['county_id']: (row['lbs'] or 0) for row in by_county}
    maximum = max(lbs_by_pk.values(), default=0)

    lmap = leaflet.LeafletMap(width=width, height=height, padding=10)
    for pk, geojson in geometries.items():
        lbs = lbs_by_pk.get(pk)
        label = f'{names[pk]}: {int(round(lbs)):,} lbs' if lbs else f'{names[pk]}: no data'
        lmap.add(leaflet.Area(
            geometry=GEOSGeometry(geojson, srid=4326),
            fill_color=ramp_color(lbs, maximum),
            fill_opacity=0.75,
            border_color='#555',
            border_width=1,
            label=label,
        ))
    return lmap.render()
```

Note `ramp_color(50, 100)`: `ceil(0.5 * 5) - 1 = 2` → `RAMP[2]`. `ramp_color(1, 100)`: `ceil(0.05) - 1 = 0`. `ramp_color(100, 100)`: `ceil(5) - 1 = 4`.

The `names` query is one extra query per map; that's fine (it's eight rows).

- [ ] **Step 4: Wire into the detail pages**

In `views.py`, add `from camp.apps.pesticides import maps` and in `ExplorerDetailMixin.get_context_data`, after `context` is built, add:

```python
        context['county_map'] = maps.county_map(context['by_county'], year) if context['by_county'] else None
```

Create `camp/templates/pesticides/includes/county-map.html` (expects `county_map`, `latest_year`):

```django
{% if county_map %}
<figure class="county-map">
    {{ county_map }}
    <figcaption class="is-size-7 has-text-grey">Pounds applied by county{% if latest_year %}, {{ latest_year }}{% endif %}. Darker is more.</figcaption>
</figure>
{% endif %}
```

In `detail-base.html`, replace the by-county column with:

```django
            <div class="column">
                {% if by_county %}
                    {% include 'pesticides/includes/county-map.html' %}
                    {% include 'pesticides/includes/by-county-table.html' %}
                {% endif %}
            </div>
```

Add to `ChemicalDetailTests`:

```python
    def test_county_map_rendered(self):
        html = self.client.get(self.chemical.get_absolute_url()).content.decode()
        assert 'admin-leaflet-map' in html
        assert 'Fresno County: 150 lbs' in html

    def test_no_map_without_uses(self):
        chem = Chemical.objects.create(chem_code=4243, name='NOTHING2')
        assert self.client.get(chem.get_absolute_url()).context['county_map'] is None
```

Then raise the `assertNumQueries` ceiling in `test_query_ceiling` from 20 to 22: on a cold cache the geometry build is one query and the `names` lookup is another.

- [ ] **Step 5: Run tests**

Run: `docker compose run --rm test pytest camp/apps/pesticides/tests/test_maps.py camp/apps/pesticides/tests/test_views.py -q`
Expected: all pass. `LeafletMap.render()` reads `settings.MAPTILER_API_KEY`; the test settings get it from `.env.test` (it may be empty, which only affects the tile URL string).

- [ ] **Step 6: Commit**

```bash
git add camp/apps/pesticides/maps.py camp/apps/pesticides/tests/test_maps.py camp/apps/pesticides/views.py camp/templates/pesticides/includes/county-map.html camp/templates/pesticides/detail-base.html camp/apps/pesticides/tests/test_views.py
git commit -m "feat(pesticides): add county choropleth to detail pages"
```


---

### Task 9: Landing page

**Files:**
- Modify: `camp/apps/pesticides/views.py` (replace `Home` placeholder)
- Overwrite: `camp/templates/pesticides/home.html`
- Create: `camp/templates/pesticides/includes/leaderboard.html`
- Test: `camp/apps/pesticides/tests/test_views.py`

**Interfaces:**
- Consumes `stats.landing_stats()` (Task 4) and `maps.county_map()` (Task 8).
- Produces context: every key of `landing_stats()` plus `section=None` and `county_map` (HTML or None).

- [ ] **Step 1: Write failing tests**

Append to `test_views.py`:

```python
class HomeTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.url = reverse('pesticides:home')

    def test_renders(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        self.assertTemplateUsed(response, 'pesticides/home.html')
        assert response.context['latest_year'] == 2023
        assert response.context['total_lbs'] == 740.0

    def test_leaderboards_link_to_details(self):
        html = self.client.get(self.url).content.decode()
        assert Chemical.objects.get(pk=3).get_absolute_url() in html
        assert Commodity.objects.get(pk=2).get_absolute_url() in html

    def test_county_map(self):
        html = self.client.get(self.url).content.decode()
        assert 'Fresno County: 670 lbs' in html
        assert 'Kern County: 70 lbs' in html

    def test_explainer_anchors(self):
        html = self.client.get(self.url).content.decode()
        for anchor in ('id="pur"', 'id="spraydays"', 'id="categories"', 'id="prop65"', 'id="iarc"', 'id="tac"', 'id="about"'):
            assert anchor in html

    def test_empty_database(self):
        from camp.apps.pesticides.models import PesticideNotice, PesticideUse
        PesticideNotice.objects.all().delete()
        PesticideUse.objects.all().delete()
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert 'No use data loaded' in response.content.decode()

    def test_navbar_has_data_tools(self):
        html = self.client.get(self.url).content.decode()
        assert 'Data Tools' in html
        assert 'Pesticides Explorer' in html
```

(`test_navbar_has_data_tools` stays red until Task 10.)

- [ ] **Step 2: Run to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/pesticides/tests/test_views.py -k Home -q`
Expected: FAIL on missing context keys.

- [ ] **Step 3: Implement**

Replace `Home` in `views.py`:

```python
class Home(vanilla.TemplateView):
    template_name = 'pesticides/home.html'

    def get_context_data(self, **kwargs):
        data = stats.landing_stats()
        county_map = maps.county_map(data['by_county'], data['latest_year']) if data['by_county'] else None
        return super().get_context_data(section=None, county_map=county_map, **data, **kwargs)
```

`camp/templates/pesticides/includes/leaderboard.html` (expects `title`, `rows`, `latest_year`, `kind`):

```django
{% load pesticides_explorer %}
<div class="card leaderboard">
    <header class="card-header"><p class="card-header-title">{{ title }}{% if latest_year %} · {{ latest_year }}{% endif %}</p></header>
    <div class="card-content">
        {% if rows %}
        <ol class="leaderboard-list">
            {% for row in rows %}
            <li>
                <a href="{{ row.obj.get_absolute_url }}">{{ row.obj.name }}</a>
                {% if kind == 'chemicals' %}<span class="tags is-inline ml-1">{% include 'pesticides/includes/classification-badges.html' with chemical=row.obj %}</span>{% endif %}
                <span class="lbs is-pulled-right">{{ row.lbs|lbs }} lbs</span>
            </li>
            {% endfor %}
        </ol>
        {% else %}
        <p class="has-text-grey">No use data loaded.</p>
        {% endif %}
    </div>
</div>
```

`camp/templates/pesticides/home.html`:

```django
{% extends 'pesticides/base.html' %}
{% load pesticides_explorer %}

{% block body-class %}{{ block.super }} home{% endblock %}
{% block breadcrumb-list %}{% endblock %}

{% block explorer-content %}
<div class="content intro">
    <p class="is-size-5">
        Browse the pesticides applied across the eight San Joaquin Valley counties: which chemicals, in which products,
        on which crops, and where. Confirmed applications come from the California Department of Pesticide Regulation's
        <a href="#pur">Pesticide Use Reporting</a> program. Planned applications come from <a href="#spraydays">SprayDays</a>
        notices of intent.
    </p>
</div>

<div class="level stat-row box">
    <div class="level-item has-text-centered"><div><p class="heading">PUR years loaded</p><p class="title">{% if years %}{{ years.0 }}–{{ years.1 }}{% else %}—{% endif %}</p></div></div>
    <div class="level-item has-text-centered"><div><p class="heading">Chemicals</p><p class="title">{{ chemical_count|lbs }}</p></div></div>
    <div class="level-item has-text-centered"><div><p class="heading">Products</p><p class="title">{{ product_count|lbs }}</p></div></div>
    <div class="level-item has-text-centered"><div><p class="heading">Commodities</p><p class="title">{{ commodity_count|lbs }}</p></div></div>
    <div class="level-item has-text-centered"><div><p class="heading">Lbs applied{% if latest_year %} in {{ latest_year }}{% endif %}</p><p class="title">{{ total_lbs|lbs }}</p></div></div>
    <div class="level-item has-text-centered"><div><p class="heading">Notices next 7 days</p><p class="title">{{ upcoming_week }}</p></div></div>
</div>

{% if county_map %}
<div class="columns is-centered">
    <div class="column is-8">{% include 'pesticides/includes/county-map.html' %}</div>
</div>
{% endif %}

<div class="columns section-cards">
    <div class="column">
        <a class="box section-card" href="{% url 'pesticides:chemical-list' %}">
            <h3 class="title is-5">Chemicals</h3>
            <p>Active ingredients, with Prop 65, IARC, and CARB classifications.</p>
            <p class="is-size-7 has-text-grey">Try: <em>glyphosate</em></p>
        </a>
    </div>
    <div class="column">
        <a class="box section-card" href="{% url 'pesticides:product-list' %}">
            <h3 class="title is-5">Products</h3>
            <p>Registered formulations, flagged when fumigant or California-restricted.</p>
            <p class="is-size-7 has-text-grey">Try: <em>roundup</em></p>
        </a>
    </div>
    <div class="column">
        <a class="box section-card" href="{% url 'pesticides:commodity-list' %}">
            <h3 class="title is-5">Commodities</h3>
            <p>Crops and sites pesticides are applied to.</p>
            <p class="is-size-7 has-text-grey">Try: <em>almond</em></p>
        </a>
    </div>
</div>

<div class="columns leaderboards">
    <div class="column">{% include 'pesticides/includes/leaderboard.html' with title='Most applied chemicals' rows=top_chemicals kind='chemicals' %}</div>
    <div class="column">{% include 'pesticides/includes/leaderboard.html' with title='Most applied chemicals of concern' rows=top_chemicals_of_concern kind='chemicals' %}</div>
    <div class="column">{% include 'pesticides/includes/leaderboard.html' with title='Most treated commodities' rows=top_commodities kind='commodities' %}</div>
</div>

<div class="content explainer mt-6" id="about">
    <h2>About this data</h2>

    <h3 id="pur">Pesticide Use Reporting (PUR)</h3>
    <p>California requires agricultural pesticide applications to be reported to the county agricultural commissioner, who forwards them to the Department of Pesticide Regulation (DPR). DPR publishes the records about a year after the fact. Each record gives the product, active ingredient, crop, county, one-square-mile section, date, and amount. This explorer loads the records for Fresno, Kern, Kings, Madera, Merced, San Joaquin, Stanislaus, and Tulare counties{% if years %} for {{ years.0 }}–{{ years.1 }}{% endif %}.</p>

    <h3 id="spraydays">SprayDays notices of intent</h3>
    <p>Growers must file a notice of intent before applying a California-restricted material. DPR's SprayDays system publishes those notices, usually a day or more ahead of the scheduled application. Notices cover only restricted materials, list the product and chemical but not the crop, and are not confirmation that the application happened.</p>

    <h3 id="categories">DPR chemical categories</h3>
    <p>DPR tags active ingredients with regulatory categories: biopesticide, carcinogen, cholinesterase inhibitor, developmental toxin, fumigant, groundwater contaminant, oil, reproductive toxin, and toxic air contaminant. A chemical can carry several.</p>

    <h3 id="prop65">Proposition 65</h3>
    <p>California's Safe Drinking Water and Toxic Enforcement Act of 1986 maintains a list of chemicals known to the state to cause cancer, birth defects, or other reproductive harm. Here, a chemical shows a <span class="tag is-danger is-light">Prop 65</span> badge when DPR categorizes it as a carcinogen, reproductive toxin, or developmental toxin.</p>

    <h3 id="iarc">IARC groups</h3>
    <p>The International Agency for Research on Cancer classifies agents by the strength of evidence that they cause cancer in humans: <strong>Group 1</strong> carcinogenic, <strong>Group 2A</strong> probably carcinogenic, <strong>Group 2B</strong> possibly carcinogenic, <strong>Group 3</strong> not classifiable. Most chemicals have not been evaluated by IARC at all, which is not the same as being found safe.</p>

    <h3 id="tac">CARB Toxic Air Contaminants</h3>
    <p>The California Air Resources Board designates air pollutants that may cause serious illness or death as Toxic Air Contaminants. Pesticides on that list are shown with a <span class="tag is-warning is-light">CARB TAC</span> badge.</p>

    <h3>Caveats</h3>
    <ul>
        <li>PUR data lags roughly a year; the most recent full year loaded is {% if latest_year %}{{ latest_year }}{% else %}not yet available{% endif %}.</li>
        <li>Location is shown at the county level in this version.</li>
        <li>Pounds are pounds of active ingredient for chemicals and commodities, and pounds of product for products.</li>
        <li>Developers can pull the underlying records from the <a href="/api/2.0/pesticides/use/">pesticides API</a>.</li>
    </ul>
</div>
{% endblock %}
```

- [ ] **Step 4: Run tests**

Run: `docker compose run --rm test pytest camp/apps/pesticides/tests/test_views.py -k Home -q`
Expected: 5 pass, `test_navbar_has_data_tools` still fails.

- [ ] **Step 5: Commit**

```bash
git add camp/apps/pesticides/views.py camp/templates/pesticides/home.html camp/templates/pesticides/includes/leaderboard.html camp/apps/pesticides/tests/test_views.py
git commit -m "feat(pesticides): add explorer landing page"
```

---

### Task 10: Navigation and styles

**Files:**
- Modify: `camp/templates/page.html` (navbar around line 27, footer Resources list around line 184)
- Create: `assets/sass/sjvair/pages/pesticides.sass`
- Modify: `assets/sass/style.sass` (add import after `pages/map`)
- Test: `HomeTests.test_navbar_has_data_tools` (already written)

- [ ] **Step 1: Navbar**

In `camp/templates/page.html`, after the `Get the App!` navbar item (line 27) insert:

```django
                <div class="navbar-item has-dropdown is-hoverable">
                    <a class="navbar-link">Data Tools</a>
                    <div class="navbar-dropdown">
                        <a class="navbar-item" href="{% url 'pesticides:home' %}">
                            <span class="icon"><span class="fa-regular fa-fw fa-flask"></span></span>
                            <span>Pesticides Explorer</span>
                        </a>
                    </div>
                </div>
```

In the footer Resources `<ul class="fa-ul">` (line ~184), add before the closing `</ul>`:

```django
                    <li>
                        <span class="fa-li">
                            <span class="fa-regular fa-fw fa-flask"></span>
                        </span>
                        <a href="{% url 'pesticides:home' %}">Pesticides Explorer</a>
                    </li>
```

- [ ] **Step 2: Styles**

Create `assets/sass/sjvair/pages/pesticides.sass`:

```sass
body.pesticides
    .hook
        .lede
            @extend .has-text-grey
            margin-bottom: 0
        .explorer-nav
            margin-top: $size-6
            margin-bottom: 0

    .breadcrumbs
        background-color: $grey-lightest
        padding: $size-6 0px

    .explorer-filters
        .label
            @extend .is-size-7
            text-transform: uppercase
            letter-spacing: 0.04em
        ul
            list-style: none
            margin-left: 0
            li
                display: block
                margin-bottom: 0.25em

    .summary-sentence
        @extend .has-text-grey-dark

    .data-table
        th .sort-link
            @extend .has-text-grey-dark
            white-space: nowrap
            .icon
                @extend .has-text-grey-light
            &.is-active
                @extend .has-text-link
                .icon
                    @extend .has-text-link

    .stat-row
        .heading
            @extend .has-text-grey
        .title
            @extend .has-text-weight-semibold

    .detail-header
        .identifiers
            margin-bottom: $size-7
        .tags
            margin-bottom: 0

    .related-card, .leaderboard
        height: 100%
        .tags.is-inline
            display: inline-flex
            vertical-align: middle

    .leaderboard-list
        margin: 0
        padding-left: 1.5em
        li
            padding: 0.25em 0
            border-bottom: 1px solid $grey-lightest
            .lbs
                @extend .has-text-grey

    .county-map
        .admin-leaflet-map
            width: 100% !important
            border-color: $grey-lighter
        figcaption
            margin-top: $size-7

    .section-card
        display: block
        height: 100%
        color: inherit
        &:hover
            box-shadow: 0 0.5em 1em -0.125em rgba($black, 0.15)
```

Add to `assets/sass/style.sass` after `@import "sjvair/pages/map"`:

```sass
@import "sjvair/pages/pesticides"
```

Then rebuild CSS. Check `tasks.py` for the task name (the sass compile is in the function that writes `dist/css/style.css`, around line 52; it is invoked with `invoke <name>`). Run it via `docker compose run --rm web invoke <name>` and confirm `dist/css/style.css` contains `.pesticides`. If the build task isn't runnable in the container, note that in the PR and leave the sass source in place; it compiles on Heroku via `heroku-postbuild`.

- [ ] **Step 3: Run the nav test and the whole explorer suite**

Run: `docker compose run --rm test pytest camp/apps/pesticides/ -q`
Expected: all pass, including `test_navbar_has_data_tools`.

- [ ] **Step 4: Commit**

```bash
git add camp/templates/page.html assets/sass/sjvair/pages/pesticides.sass assets/sass/style.sass
git commit -m "feat(pesticides): add Data Tools navigation and explorer styles"
```

---

### Task 11: Design pass and browser check against real data

**Files:**
- Modify: any `camp/templates/pesticides/*.html` and `assets/sass/sjvair/pages/pesticides.sass`

This task is visual and uses the `frontend-design` skill. The local DB has 4 years of real PUR data, so the pages can be judged with real names and numbers.

- [ ] **Step 1: Start the dev server**

Run: `docker compose --profile web up -d` and open `http://localhost:8000/tools/pesticides/` (check `docker compose ps` for the mapped port if different).

- [ ] **Step 2: Walk the pages**

Visit, in order, and note anything broken or ugly: the landing page; `/tools/pesticides/chemicals/` (default sort, then `?q=chlor`, then `?category=carcinogen&category=toxic_air_contaminant`, then page 2); a chemical detail for a heavily used chemical (top of the default list); `/tools/pesticides/products/?sort=-lbs`; a product detail; `/tools/pesticides/commodities/`; a commodity detail; a bare-sqid URL; a bad sqid. Check each page at phone width (Bulma's `table-container` should scroll horizontally, the filter column should stack above the table, and the county map should shrink to the column width). Confirm the county map draws tiles (needs `MAPTILER_API_KEY` in `.env`) and that the labels don't overlap badly at the default size.

- [ ] **Step 3: Time the list pages**

Run against the real data: `time curl -s -o /dev/null http://localhost:8000/tools/pesticides/products/?sort=-lbs` and the same for chemicals and commodities. Record the timings in the PR description. Anything over ~2s is the documented performance risk; do not add caching or a summary table in this PR, just record it.

- [ ] **Step 4: Apply the frontend-design skill**

Invoke `frontend-design` with the explorer templates and sass as the target and the landing page as the priority. Constraints: Bulma 0.9 only, existing `page.html` chrome, no new JS, keep every test green. Commit the resulting tweaks as one commit:

```bash
git add camp/templates/pesticides/ assets/sass/sjvair/pages/pesticides.sass
git commit -m "style(pesticides): design pass on explorer templates"
```

- [ ] **Step 5: Full test run**

Run: `docker compose run --rm test pytest camp/apps/pesticides/ camp/api/v2/pesticides/ -q` then `docker compose run --rm test pytest -q` (whole suite; CI runs the whole tree). If the full suite has failures unrelated to pesticides, re-run once before investigating (shared DB contention across worktrees).

- [ ] **Step 6: Stop the dev server**

Run: `docker compose --profile web down`

---

### Task 12: Finish the branch

- [ ] **Step 1: Review the diff against the spec**

Run: `git log --oneline main..HEAD` and `git diff main --stat`. Confirm every spec section maps to committed code: routing, search, classification, list pages with related-entity filters, detail pages, landing page with caching, navigation, tests.

- [ ] **Step 2: Hand off**

Invoke `superpowers:finishing-a-development-branch`. The PR description should include: what the explorer is, the URL map, the three deliberate deviations from the spec (forms instead of API FilterSets; product "active ingredients" listed by percent active rather than pounds; query ceiling set at 22 instead of the spec's 15 target), the recorded list-page timings from Task 11, and the note that CSS must be rebuilt on deploy (already handled by `heroku-postbuild`).
