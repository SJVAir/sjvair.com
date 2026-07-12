# CalEnviroScreen 5.0 Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add CalEnviroScreen 5.0 (CES5) support alongside the existing CES4 implementation — model, importer, and API — and restructure CES4's API so both versions share a consistent URL shape.

**Architecture:** `CES5` is a new concrete model in the existing `camp/apps/ces/` app, subclassing the existing abstract `CESRecord` unchanged. Unlike CES4 (native 2010, crosswalked to 2020), CES5 is natively 2020-tract data, so its importer needs no crosswalk step. CES4's API drops its `<year>` URL segment in favor of an optional `?year=` query param (defaulting to `2020`) so CES4 and CES5 expose the same `calenviroscreen/{version}/` shape.

**Tech Stack:** Django, PostGIS, `geopandas`/`esri2gpd` (via `camp.utils.geodata`), `resticus` (API), pytest via `docker compose run --rm test`.

## Global Constraints

- All commands run inside Docker: `docker compose run --rm test pytest ...`, `docker compose run --rm web python manage.py ...`.
- Tests use plain `assert` statements, not `self.assertFoo()`.
- Verbose names use `_()` as the first positional arg: `FloatField(_('Label'), null=True)`.
- Do not align `=` signs in field definitions.
- Never `git add -A` — always list files explicitly. No co-authored-by lines in commits.
- Fixtures live in `/fixtures/*.yaml`; this work extends `fixtures/calenviroscreen.yaml`.
- Full spec: `docs/superpowers/specs/2026-07-11-calenviroscreen5-design.md`.

---

## Work in a worktree

Before starting Task 1, set up an isolated git worktree for this feature (per the user's request to work this way going forward). Use the `superpowers:using-git-worktrees` skill to create it (e.g. branch `feature/calenviroscreen5` off `main`). All tasks below assume you're working inside that worktree.

---

### Task 1: Generalize the `DACCategory.PRIOR_DAC` label

The `DACCategory` enum is shared between CES4 and CES5. Its `PRIOR_DAC` label currently says "Designated under 2017 DAC list," which is CES4-specific lineage — CES5's equivalent carry-over category comes from CES4/2022, not the 2017 list. Generalize the label so it reads correctly for both. This only changes a translated string; the integer value and all logic are unchanged.

**Files:**
- Modify: `camp/apps/ces/models.py:11` (the `DACCategory.PRIOR_DAC` line)
- Test: `camp/apps/ces/tests.py` (regression — existing `CES4ModelTests` must still pass)

**Interfaces:**
- Produces: `DACCategory.PRIOR_DAC` (value `3`) — unchanged value, new label text. Later tasks (CES5's `DAC_CATEGORY_MAP`) will map `'CES 4.0 Carry-Over DAC'` to this same enum member.

- [ ] **Step 1: Run the existing CES test suite to confirm current green baseline**

Run: `docker compose run --rm test pytest camp/apps/ces/tests.py -v`
Expected: All tests PASS (this is a baseline check before touching the file).

- [ ] **Step 2: Update the label**

In `camp/apps/ces/models.py`, change:

```python
    PRIOR_DAC = 3, _('Designated under 2017 DAC list')
```

to:

```python
    PRIOR_DAC = 3, _('Carried over from prior DAC designation')
```

- [ ] **Step 3: Generate the migration**

Run: `docker compose run --rm web python manage.py makemigrations ces`
Expected: Creates `camp/apps/ces/migrations/0002_alter_ces4_dac_category.py` (exact name may vary slightly) containing an `AlterField` for `CES4.dac_category` with the updated `choices` list. No other changes.

- [ ] **Step 4: Run the existing CES test suite again**

Run: `docker compose run --rm test pytest camp/apps/ces/tests.py camp/api/v2/ces/tests.py -v`
Expected: All tests still PASS — `test_dac_category_choices` compares the integer value (`DACCategory.TOP_CES_SCORE`), not the label text, so it's unaffected.

- [ ] **Step 5: Commit**

```bash
git add camp/apps/ces/models.py camp/apps/ces/migrations/0002_alter_ces4_dac_category.py
git commit -m "refactor(ces): generalize DACCategory.PRIOR_DAC label for CES5"
```

---

### Task 1.5: Retrofit `CES4` with a `sqid` field

This project's convention (`CLAUDE.md` Key Conventions) is that all new models get a `sqid = SqidsField(alphabet=shuffle_alphabet('app.ModelName'))` for their external identifier, following `camp/apps/ceidars/models.py`. CES5 (Task 2) already gets one. Since nothing downstream depends on CES4 data yet, CES4 is retrofitted with the same convention here, before Task 2 adds CES5 — so both models pick up the pattern independently and consistently.

**Important:** declare `sqid` separately on `CES4` and `CES5` (Task 2), each with its own seed string — do NOT hoist a single `sqid` field onto the shared `CESRecord` abstract base. `shuffle_alphabet(seed)` computes a fixed shuffled-alphabet string once, at field-declaration time; Django's abstract-field inheritance clones that already-built field object into every concrete subclass rather than re-running `shuffle_alphabet` per subclass. A `sqid` declared once on `CESRecord` would give CES4 and CES5 the *identical* alphabet, so e.g. `CES4` row `id=7` and `CES5` row `id=7` would encode to the exact same sqid string — defeating the purpose of a unique-per-model opaque identifier. `camp/apps/ceidars/models.py` avoids this by seeding per concrete model (`'ceidars.Facility'`, `'ceidars.EmissionsRecord'`); CES4/CES5 follow that precedent.

`SqidsField` is a derived/virtual field computed from the real `id` PK at read time by `django_sqids` — it adds **no migration column** (confirmed: zero `sqid` references anywhere in `camp/apps/ceidars/migrations/`, despite `Facility`/`EmissionsRecord` declaring the field) and needs **no fixture value or data backfill**. Existing CES4 rows get valid sqids for free the moment the field is declared.

This task does NOT change CES4's URL/lookup design — detail lookups stay tract-GEOID-based (`camp/api/v2/ces/endpoints.py`, unchanged by this task). `sqid` is exposed in the API purely as an `id` field, for consistency with how other newer apps' serializers already do it (`('id', lambda f: f.sqid)` in `camp/api/v2/ceidars/serializers.py`).

**Files:**
- Modify: `camp/apps/ces/models.py` (add `sqid` to `CES4`)
- Modify: `camp/api/v2/ces/serializers.py` (add `id` to `CES4Serializer`)
- Modify: `camp/apps/ces/tests.py` (add a `sqid` test to `CES4ModelTests`)
- Modify: `camp/api/v2/ces/tests.py` (add an `id`-field assertion to `CES4EndpointTests`)

**Interfaces:**
- Consumes: `CES4` model, `CES4Serializer` (from before this task — Task 1's label change, unrelated to this).
- Produces: `CES4.sqid` (a `SqidsField`, virtual — no DB column). `CES4Serializer` now includes `('id', lambda r: r.sqid)` as its first field. Task 2's `CES5` model and Task 6's `CES5Serializer` follow this exact same pattern with their own `'ces.CES5'` seed — this task's diff is the reference implementation for that.

- [ ] **Step 1: Write the failing tests first**

In `camp/apps/ces/tests.py`, add a test to `CES4ModelTests` (after `test_str`, or anywhere in the class):

```python
    def test_sqid_is_a_nonempty_string(self):
        record = self.get_tract('06019000101', '2020')
        assert isinstance(record.sqid, str)
        assert record.sqid
```

In `camp/api/v2/ces/tests.py`, add an assertion to the existing `test_list_records_have_expected_fields` method on `CES4EndpointTests` — find this exact method and add one line at the top of its body:

```python
    def test_list_records_have_expected_fields(self):
        request = self.factory.get('/')
        response = ces4_list(request, year='2020')
        data = get_response_data(response)

        record = data['data'][0]
        assert 'id' in record
        assert 'tract' in record
        assert 'census_year' in record
        assert 'ci_score' in record
        assert 'ci_score_p' in record
        assert 'dac_sb535' in record
        assert 'pollution_p' in record
        assert 'popchar_p' in record
```

(Only the `assert 'id' in record` line is new — the rest of this method is unchanged from its current form. Task 5, later, will change the `ces4_list(request, year='2020')` call signature as part of a separate refactor; that's expected and not this task's concern.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/ces/tests.py::CES4ModelTests::test_sqid_is_a_nonempty_string camp/api/v2/ces/tests.py::CES4EndpointTests::test_list_records_have_expected_fields -v`
Expected: Both FAIL — `AttributeError: 'CES4' object has no attribute 'sqid'` for the first, `KeyError`/`AssertionError` (no `'id'` key) for the second.

- [ ] **Step 3: Add the `sqid` field to `CES4`**

In `camp/apps/ces/models.py`, add this import alongside the existing ones (`from django.db import models`, `from django.utils.translation import gettext_lazy as _`, `from camp.apps.ces.querysets import CESManager`):

```python
from django_sqids import SqidsField, shuffle_alphabet
```

Then, inside the `CES4` class, add `sqid` as the first field (right after the class's opening, before `pollution`):

```python
class CES4(CESRecord):
    """
    CalEnviroScreen 4.0 (2021), keyed to both 2010 and 2020 census tract
    boundaries. 2010-vintage records use original CES4 scores; 2020-vintage
    records are area-weighted crosswalks from 2010 tracts.

    Percentiles are California-wide as published by OEHHA.
    """

    # New models in this project use sqids for their external identifier
    # (see CLAUDE.md Key Conventions).
    sqid = SqidsField(alphabet=shuffle_alphabet('ces.CES4'))

    # --- Pollution Burden ---
    pollution = models.FloatField(_('Pollution Burden Score'), null=True)
    ...
```

(The docstring and everything from `# --- Pollution Burden ---` onward already exists in the file, unchanged — only the `sqid` field is new.)

- [ ] **Step 4: Add `id` to `CES4Serializer`**

In `camp/api/v2/ces/serializers.py`, add one line at the top of `CES4Serializer.fields`:

```python
class CES4Serializer(serializers.Serializer):
    fields = (
        ('id', lambda r: r.sqid),
        ('tract', lambda r: r.tract),
        ('census_year', lambda r: r.census_year),
        'population',
        ...
```

(Only the `('id', lambda r: r.sqid)` line is new — everything else in this serializer already exists, unchanged.)

- [ ] **Step 5: Generate the migration and confirm it's a no-op for `sqid`**

Run: `docker compose run --rm web python manage.py makemigrations ces`
Expected: Django reports "No changes detected" — `SqidsField` contributes no concrete column (`column = None`, `concrete = False` per `django_sqids.field.SqidsField.contribute_to_class`), so there is nothing for the migration autodetector to pick up. If a migration DOES get generated, stop and report BLOCKED — that would mean this field is behaving differently than the ceidars precedent, and needs investigation before proceeding.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `docker compose run --rm test pytest camp/apps/ces/tests.py camp/api/v2/ces/tests.py -v`
Expected: All tests PASS, including the two new ones from Step 1.

- [ ] **Step 7: Commit**

```bash
git add camp/apps/ces/models.py camp/api/v2/ces/serializers.py camp/apps/ces/tests.py camp/api/v2/ces/tests.py
git commit -m "feat(ces): retrofit CES4 with a sqid field"
```

---

### Task 2: Add the `CES5` model, migration, and fixture data

**Files:**
- Modify: `camp/apps/ces/models.py` (append `CES5` class)
- Modify: `fixtures/calenviroscreen.yaml` (append CES5 fixture records)
- Modify: `camp/apps/ces/tests.py` (append `CES5ModelTests`)
- Create: `camp/apps/ces/migrations/0003_ces5.py` (generated, not hand-written)

**Interfaces:**
- Consumes: `CESRecord` abstract base and `DACCategory` enum from `camp/apps/ces/models.py` (unchanged from Task 1). `CESManager`/`CESQuerySet` from `camp/apps/ces/querysets.py` (unchanged — reused as-is). The `from django_sqids import SqidsField, shuffle_alphabet` import added to `camp/apps/ces/models.py` by Task 1.5.
- Produces: `CES5` model with fields `boundary`, `population`, `ci_score`, `ci_score_p`, `dac_sb535`, `dac_category` (inherited from `CESRecord`), plus `sqid`, `zipcode`, `approx_loc`, `county`, `region_name`, and all `pol_*`, `char_*`, `pop_*_pct`, `pollution*`, `popchar*` fields listed below. `record.tract`, `record.census_year`, `record.region` properties (inherited, unchanged behavior). Later tasks (admin, importer, API) depend on these exact field names.

`sqid` note: same convention Task 1.5 applied to `CES4` — `sqid = SqidsField(alphabet=shuffle_alphabet('ces.CES5'))`, its own seed (not `CESRecord`, not CES4's seed — see Task 1.5 for why sharing a seed across models would cause id collisions). `SqidsField` is virtual — no migration column, no fixture value needed. This does NOT change CES5's URL/lookup design (still tract-GEOID-based, per the approved spec) — `sqid` is exposed in the API purely as an `('id', ...)` field, same as CES4 now does (Task 6).

- [ ] **Step 1: Write the failing test — fixture data first**

Append to `fixtures/calenviroscreen.yaml` (after the existing CES4 records, i.e. after line 324). This reuses the *same* 2020-vintage boundaries (`1003`, `1004`) already defined earlier in the fixture — CES5 has no 2010 records, so no new `Boundary` rows are needed:

```yaml
# CES5 records — 2020 vintage only (CES5 is natively 2020, no crosswalk)
- model: ces.ces5
  pk: 1
  fields:
    boundary: 1003  # tract 1.01, 2020
    zipcode: 93650
    approx_loc: Fresno
    county: Fresno
    region_name: San Joaquin Valley
    population: 4650
    ci_score: 76.1
    ci_score_p: 89.2
    dac_sb535: true
    dac_category: 1
    pollution: 6.2
    pollution_s: 0.75
    pollution_p: 83.0
    pol_ozone: 0.063
    pol_ozone_p: 72.0
    pol_pm: 12.6
    pol_pm_p: 80.0
    pol_diesel: 8.4
    pol_diesel_p: 66.0
    pol_pest: null
    pol_pest_p: null
    pol_rsei_haz: null
    pol_rsei_haz_p: null
    pol_traffic: 525.0
    pol_traffic_p: 56.0
    pol_drink: null
    pol_drink_p: null
    pol_lead: null
    pol_lead_p: null
    pol_cleanups: null
    pol_cleanups_p: null
    pol_gwthreats: null
    pol_gwthreats_p: null
    pol_haz: null
    pol_haz_p: null
    pol_iwb: null
    pol_iwb_p: null
    pol_small_ats: 2.1
    pol_small_ats_p: 68.0
    pol_swis: null
    pol_swis_p: null
    popchar: 7.9
    popchar_s: 0.70
    popchar_p: 92.0
    char_asthma: null
    char_asthma_p: null
    char_cvd: null
    char_cvd_p: null
    char_diabetes: 11.4
    char_diabetes_p: 77.0
    char_lbw: null
    char_lbw_p: null
    char_edu: null
    char_edu_p: null
    char_ling: null
    char_ling_p: null
    char_pov: 28.9
    char_pov_p: 86.0
    char_unemp: 14.5
    char_unemp_p: 81.0
    char_housingb: null
    char_housingb_p: null
    pop_under_10_pct: 12.9
    pop_10_64_pct: 68.8
    pop_65_plus_pct: 15.1
    pop_hispanic_pct: 60.2
    pop_white_pct: 19.4
    pop_black_pct: 4.3
    pop_native_pct: 1.1
    pop_asian_pct: 5.8
    pop_pacisl_pct: 0.4
    pop_other_pct: 5.6

- model: ces.ces5
  pk: 2
  fields:
    boundary: 1004  # tract 1.02, 2020
    zipcode: 93650
    approx_loc: Fresno
    county: Fresno
    region_name: San Joaquin Valley
    population: 3350
    ci_score: 42.0
    ci_score_p: 51.0
    dac_sb535: false
    dac_category: null
    pollution: 3.9
    pollution_s: 0.47
    pollution_p: 49.0
    pol_ozone: 0.056
    pol_ozone_p: 53.0
    pol_pm: 8.2
    pol_pm_p: 45.0
    pol_diesel: 4.2
    pol_diesel_p: 39.0
    pol_pest: null
    pol_pest_p: null
    pol_rsei_haz: null
    pol_rsei_haz_p: null
    pol_traffic: 212.0
    pol_traffic_p: 31.0
    pol_drink: null
    pol_drink_p: null
    pol_lead: null
    pol_lead_p: null
    pol_cleanups: null
    pol_cleanups_p: null
    pol_gwthreats: null
    pol_gwthreats_p: null
    pol_haz: null
    pol_haz_p: null
    pol_iwb: null
    pol_iwb_p: null
    pol_small_ats: 0.3
    pol_small_ats_p: 22.0
    pol_swis: null
    pol_swis_p: null
    popchar: 5.2
    popchar_s: null
    popchar_p: 61.0
    char_asthma: null
    char_asthma_p: null
    char_cvd: null
    char_cvd_p: null
    char_diabetes: 8.9
    char_diabetes_p: 49.0
    char_lbw: null
    char_lbw_p: null
    char_edu: null
    char_edu_p: null
    char_ling: null
    char_ling_p: null
    char_pov: 18.4
    char_pov_p: 56.0
    char_unemp: 9.4
    char_unemp_p: 49.0
    char_housingb: null
    char_housingb_p: null
    pop_under_10_pct: 11.2
    pop_10_64_pct: 70.1
    pop_65_plus_pct: 18.7
    pop_hispanic_pct: 42.5
    pop_white_pct: 33.3
    pop_black_pct: 4.9
    pop_native_pct: 0.8
    pop_asian_pct: 12.1
    pop_pacisl_pct: 0.3
    pop_other_pct: 6.1
```

Append to `camp/apps/ces/tests.py` (this references the `CES5` model, which doesn't exist yet — it will fail to import):

```python
from camp.apps.ces.models import CES5


class CES5ModelTests(TestCase):
    fixtures = ['calenviroscreen']

    def get_tract(self, geoid):
        return CES5.objects.get(boundary__region__external_id=geoid)

    def test_tract_property(self):
        record = self.get_tract('06019000101')
        assert record.tract == '06019000101'

    def test_census_year_property(self):
        record = self.get_tract('06019000101')
        assert record.census_year == '2020'

    def test_region_property(self):
        record = self.get_tract('06019000101')
        assert record.region.name == 'Census Tract 1.01'

    def test_region_name_field(self):
        record = self.get_tract('06019000101')
        assert record.region_name == 'San Joaquin Valley'

    def test_str(self):
        record = self.get_tract('06019000101')
        assert 'CES5' in str(record)
        assert '06019000101' in str(record)
        assert '2020' in str(record)

    def test_dac_category_choices(self):
        record = self.get_tract('06019000101')
        assert record.dac_sb535 is True
        assert record.dac_category == DACCategory.TOP_CES_SCORE

    def test_non_dac_record(self):
        record = self.get_tract('06019000102')
        assert record.dac_sb535 is False
        assert record.dac_category is None

    def test_only_one_vintage_exists(self):
        assert CES5.objects.for_tract('06019000101').count() == 1

    def test_new_indicators_present(self):
        record = self.get_tract('06019000101')
        assert record.pol_small_ats_p == 68.0
        assert record.char_diabetes_p == 77.0

    def test_demographic_percentages(self):
        record = self.get_tract('06019000101')
        assert record.pop_hispanic_pct == 60.2
        assert record.pop_asian_pct == 5.8
        assert record.pop_pacisl_pct == 0.4

    def test_sqid_is_a_nonempty_string(self):
        record = self.get_tract('06019000101')
        assert isinstance(record.sqid, str)
        assert record.sqid
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `docker compose run --rm test pytest camp/apps/ces/tests.py::CES5ModelTests -v`
Expected: FAIL with `ImportError: cannot import name 'CES5'` (or similar) since the model doesn't exist yet.

- [ ] **Step 3: Add the `CES5` model**

Task 1.5 already added `from django_sqids import SqidsField, shuffle_alphabet` to the top of `camp/apps/ces/models.py` (for `CES4`'s `sqid` field) — confirm it's there; you don't need to add it again.

Append to `camp/apps/ces/models.py`, after the existing `CES4` class:

```python
class CES5(CESRecord):
    """
    CalEnviroScreen 5.0 (2026), keyed to 2020 census tract boundaries only.
    Unlike CES4, CES5 is natively 2020-vintage — no crosswalk is needed.

    Percentiles are California-wide as published by OEHHA. Demographic
    fields are percentages (unlike CES4's raw population counts), suffixed
    `_pct` to make that distinction impossible to miss.
    """

    # New models in this project use sqids for their external identifier
    # (see CLAUDE.md Key Conventions). CES4 predates this convention.
    sqid = SqidsField(alphabet=shuffle_alphabet('ces.CES5'))

    # --- Tract metadata (new in CES5) ---
    zipcode = models.IntegerField(_('ZIP Code'), null=True)
    approx_loc = models.CharField(_('Approximate Location'), max_length=100, null=True, blank=True)
    county = models.CharField(_('County'), max_length=100, null=True, blank=True)
    region_name = models.CharField(_('CalEnviroScreen Region'), max_length=100, null=True, blank=True)

    # --- Pollution Burden ---
    pollution = models.FloatField(_('Pollution Burden Score'), null=True)
    pollution_s = models.FloatField(_('Pollution Burden Score (scaled)'), null=True)
    pollution_p = models.FloatField(_('Pollution Burden Percentile'), null=True)

    pol_ozone = models.FloatField(_('Ozone'), null=True)
    pol_ozone_p = models.FloatField(_('Ozone Percentile'), null=True)
    pol_pm = models.FloatField(_('PM2.5'), null=True)
    pol_pm_p = models.FloatField(_('PM2.5 Percentile'), null=True)
    pol_diesel = models.FloatField(_('Diesel PM'), null=True)
    pol_diesel_p = models.FloatField(_('Diesel PM Percentile'), null=True)
    pol_pest = models.FloatField(_('Pesticides'), null=True)
    pol_pest_p = models.FloatField(_('Pesticides Percentile'), null=True)
    pol_rsei_haz = models.FloatField(_('Toxic Releases (RSEI)'), null=True)
    pol_rsei_haz_p = models.FloatField(_('Toxic Releases Percentile'), null=True)
    pol_traffic = models.FloatField(_('Traffic'), null=True)
    pol_traffic_p = models.FloatField(_('Traffic Percentile'), null=True)
    pol_drink = models.FloatField(_('Drinking Water Contaminants'), null=True)
    pol_drink_p = models.FloatField(_('Drinking Water Contaminants Percentile'), null=True)
    pol_lead = models.FloatField(_("Child's Lead Risk from Housing"), null=True)
    pol_lead_p = models.FloatField(_("Child's Lead Risk from Housing Percentile"), null=True)
    pol_cleanups = models.FloatField(_('Cleanup Sites'), null=True)
    pol_cleanups_p = models.FloatField(_('Cleanup Sites Percentile'), null=True)
    pol_gwthreats = models.FloatField(_('Groundwater Threats'), null=True)
    pol_gwthreats_p = models.FloatField(_('Groundwater Threats Percentile'), null=True)
    pol_haz = models.FloatField(_('Hazardous Waste'), null=True)
    pol_haz_p = models.FloatField(_('Hazardous Waste Percentile'), null=True)
    pol_iwb = models.FloatField(_('Impaired Water Bodies'), null=True)
    pol_iwb_p = models.FloatField(_('Impaired Water Bodies Percentile'), null=True)
    pol_small_ats = models.FloatField(_('Small Air Toxic Sites'), null=True)
    pol_small_ats_p = models.FloatField(_('Small Air Toxic Sites Percentile'), null=True)
    pol_swis = models.FloatField(_('Solid Waste Sites'), null=True)
    pol_swis_p = models.FloatField(_('Solid Waste Sites Percentile'), null=True)

    # --- Population Characteristics ---
    popchar = models.FloatField(_('Population Characteristics Score'), null=True)
    popchar_s = models.FloatField(_('Population Characteristics Score (scaled)'), null=True)
    popchar_p = models.FloatField(_('Population Characteristics Percentile'), null=True)

    char_asthma = models.FloatField(_('Asthma'), null=True)
    char_asthma_p = models.FloatField(_('Asthma Percentile'), null=True)
    char_cvd = models.FloatField(_('Cardiovascular Disease'), null=True)
    char_cvd_p = models.FloatField(_('Cardiovascular Disease Percentile'), null=True)
    char_diabetes = models.FloatField(_('Diabetes Prevalence'), null=True)
    char_diabetes_p = models.FloatField(_('Diabetes Prevalence Percentile'), null=True)
    char_lbw = models.FloatField(_('Low Birth Weight'), null=True)
    char_lbw_p = models.FloatField(_('Low Birth Weight Percentile'), null=True)
    char_edu = models.FloatField(_('Educational Attainment'), null=True)
    char_edu_p = models.FloatField(_('Educational Attainment Percentile'), null=True)
    char_ling = models.FloatField(_('Linguistic Isolation'), null=True)
    char_ling_p = models.FloatField(_('Linguistic Isolation Percentile'), null=True)
    char_pov = models.FloatField(_('Poverty'), null=True)
    char_pov_p = models.FloatField(_('Poverty Percentile'), null=True)
    char_unemp = models.FloatField(_('Unemployment'), null=True)
    char_unemp_p = models.FloatField(_('Unemployment Percentile'), null=True)
    char_housingb = models.FloatField(_('Housing Burden'), null=True)
    char_housingb_p = models.FloatField(_('Housing Burden Percentile'), null=True)

    # --- Demographics (percentages, unlike CES4's raw counts) ---
    pop_under_10_pct = models.FloatField(_('Population Under 10 (%)'), null=True)
    pop_10_64_pct = models.FloatField(_('Population 10–64 (%)'), null=True)
    pop_65_plus_pct = models.FloatField(_('Population 65+ (%)'), null=True)
    pop_hispanic_pct = models.FloatField(_('Hispanic/Latino Population (%)'), null=True)
    pop_white_pct = models.FloatField(_('White Population (%)'), null=True)
    pop_black_pct = models.FloatField(_('Black or African American Population (%)'), null=True)
    pop_native_pct = models.FloatField(_('American Indian and Alaska Native Population (%)'), null=True)
    pop_asian_pct = models.FloatField(_('Asian Population (%)'), null=True)
    pop_pacisl_pct = models.FloatField(_('Pacific Islander Population (%)'), null=True)
    pop_other_pct = models.FloatField(_('Other or Multiple Races Population (%)'), null=True)

    class Meta(CESRecord.Meta):
        verbose_name = _('CalEnviroScreen 5.0')
        verbose_name_plural = _('CalEnviroScreen 5.0 Records')
        ordering = ['boundary__region__external_id']
```

- [ ] **Step 4: Generate the migration**

Run: `docker compose run --rm web python manage.py makemigrations ces`
Expected: Creates `camp/apps/ces/migrations/0003_ces5.py` with a single `CreateModel` for `CES5`. The `CreateModel`'s field list will NOT include `sqid` — `SqidsField` is a derived/virtual field computed from `id` at read time, not a real column, so Django's migration autodetector doesn't emit one for it (confirm by checking `camp/apps/ceidars/migrations/*.py`, which likewise has zero `sqid` references despite `Facility`/`EmissionsRecord` declaring the field). This is expected, not a bug.

- [ ] **Step 5: Run the test to verify it passes**

Run: `docker compose run --rm test pytest camp/apps/ces/tests.py -v`
Expected: All tests PASS, including the new `CES5ModelTests` and the pre-existing `CES4ModelTests`.

- [ ] **Step 6: Commit**

```bash
git add camp/apps/ces/models.py camp/apps/ces/tests.py fixtures/calenviroscreen.yaml camp/apps/ces/migrations/0003_ces5.py
git commit -m "feat(ces): add CES5 model"
```

---

### Task 3: Register `CES5` in the admin

**Files:**
- Modify: `camp/apps/ces/admin.py`

**Interfaces:**
- Consumes: `CES5` model from Task 2. `CESRecordAdmin` base class (unchanged).
- Produces: `CES5Admin` registered for the `CES5` model — no other task depends on this.

- [ ] **Step 1: Add the import and registration**

In `camp/apps/ces/admin.py`, change the import line:

```python
from camp.apps.ces.models import CES4
```

to:

```python
from camp.apps.ces.models import CES4, CES5
```

Then append, after the `CES4Admin` class:

```python
@admin.register(CES5)
class CES5Admin(CESRecordAdmin):
    fieldsets = [
        (None, {
            'fields': [
                'tract', 'census_year', 'region', 'zipcode', 'approx_loc',
                'county', 'region_name', 'population', 'ci_score', 'ci_score_p',
            ],
        }),
        (_('SB535 Disadvantaged Community'), {
            'fields': ['dac_sb535', 'dac_category'],
        }),
        (_('Pollution Burden'), {
            'fields': [
                'pollution', 'pollution_s', 'pollution_p',
                'pol_ozone', 'pol_ozone_p',
                'pol_pm', 'pol_pm_p',
                'pol_diesel', 'pol_diesel_p',
                'pol_pest', 'pol_pest_p',
                'pol_rsei_haz', 'pol_rsei_haz_p',
                'pol_traffic', 'pol_traffic_p',
                'pol_drink', 'pol_drink_p',
                'pol_lead', 'pol_lead_p',
                'pol_cleanups', 'pol_cleanups_p',
                'pol_gwthreats', 'pol_gwthreats_p',
                'pol_haz', 'pol_haz_p',
                'pol_iwb', 'pol_iwb_p',
                'pol_small_ats', 'pol_small_ats_p',
                'pol_swis', 'pol_swis_p',
            ],
            'classes': ['collapse'],
        }),
        (_('Population Characteristics'), {
            'fields': [
                'popchar', 'popchar_s', 'popchar_p',
                'char_asthma', 'char_asthma_p',
                'char_cvd', 'char_cvd_p',
                'char_diabetes', 'char_diabetes_p',
                'char_lbw', 'char_lbw_p',
                'char_edu', 'char_edu_p',
                'char_ling', 'char_ling_p',
                'char_pov', 'char_pov_p',
                'char_unemp', 'char_unemp_p',
                'char_housingb', 'char_housingb_p',
            ],
            'classes': ['collapse'],
        }),
        (_('Demographics'), {
            'fields': [
                'pop_under_10_pct', 'pop_10_64_pct', 'pop_65_plus_pct',
                'pop_hispanic_pct', 'pop_white_pct', 'pop_black_pct',
                'pop_native_pct', 'pop_asian_pct', 'pop_pacisl_pct', 'pop_other_pct',
            ],
            'classes': ['collapse'],
        }),
    ]
```

Note `CES5Admin`'s `readonly_fields` (`['tract', 'census_year', 'region']`) is inherited from `CESRecordAdmin` and doesn't include `zipcode`/`approx_loc`/`county`/`region_name` — those are real editable model fields, not properties, so they don't need to be listed there.

- [ ] **Step 2: Verify the admin loads without error**

Run: `docker compose run --rm test pytest camp/apps/ces/tests.py -v`
Expected: All tests still PASS (this doesn't directly test the admin, but confirms `admin.py` has no import/syntax errors that would break Django's app registry — Django loads all `admin.py` files at startup).

Then manually spot-check: `docker compose run --rm web python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 3: Commit**

```bash
git add camp/apps/ces/admin.py
git commit -m "feat(ces): register CES5 admin"
```

---

### Task 3.5: Fix the shared zip-shapefile loader for nested-directory zips

**Discovered mid-plan, verified against the live resource:** OEHHA's live CalEnviroScreen 5.0 shapefile zip (`calenviroscreen50results_f_070126.shp.zip`, the resource Task 4 downloads) nests its `.shp`/`.dbf`/`.shx` files inside a subdirectory whose own name ends in `.shp`:

```
calenviroscreen50results_F_070126.shp/
calenviroscreen50results_F_070126.shp/CES5_final_shapefile.dbf
calenviroscreen50results_F_070126.shp/CES5_final_shapefile.shp
calenviroscreen50results_F_070126.shp/CES5_final_shapefile.shx
...
```

`camp/utils/geodata.py:stream_filtered_gdf` opens shapefile zips with a bare `fiona.open(f'zip://{path}')`, relying on GDAL's zip-root shapefile auto-detection. That returns zero layers for this packaging (confirmed: `fiona.listlayers('zip://{path}')` → `[]`), while `fiona.listlayers('zip://{path}!/calenviroscreen50results_F_070126.shp')` → `['CES5_final_shapefile']`. This function backs `import_ces4` too (and any future CKAN-shapefile importer) — it's a shared-utility bug, not something to work around inside `import_ces5.py`.

**Files:**
- Modify: `camp/utils/geodata.py`

**Interfaces:**
- Consumes: `fiona`, `zipfile` (already imported in this file).
- Produces: `stream_filtered_gdf` now resolves nested-directory zip shapefiles automatically. Task 4's `import_ces5.py` (which calls `geodata.gdf_from_ckan` → `iter_from_url` → `iter_from_zip` → `stream_filtered_gdf`) depends on this fix to load CES5's shapefile at all.

**Backward-compatibility constraint:** the fix must be a no-op for any zip that already works today (CES4's included) — it only activates when the existing root-level `zip://` open would already yield zero layers.

- [ ] **Step 1: Confirm the precondition against CES4's real shapefile (regression safety check, not a unit test — this file has no existing test suite)**

Run: `docker compose run --rm web python manage.py shell -c "
from camp.utils import geodata
from camp.utils.geodata import GEODATA_CACHE_DIR
import fiona
paths = list(GEODATA_CACHE_DIR.glob('*.zip'))
print([p.name for p in paths])
for p in paths:
    print(p, fiona.listlayers(f'zip://{p}'))
"`

If CES4's shapefile zip isn't already cached locally (no output, or empty list), run `docker compose run --rm web python manage.py import_ces4 --print-columns` first to populate the cache (it downloads the CES4 shapefile and exits before touching the DB), then re-run the shell check above.

Expected: at least one cached zip reports a non-empty layer list at the bare `zip://{path}` form — this is CES4's shapefile, and it confirms the guard condition (`if not fiona.listlayers(fiona_path)`) will evaluate `False` for it, so the new code path added in Step 2 never executes for CES4. This is the evidence that the fix cannot regress CES4.

- [ ] **Step 2: Add the fix**

In `camp/utils/geodata.py`, add this helper function near `stream_filtered_gdf` (right above it is fine):

```python
def _resolve_nested_zip_shapefile(path, fiona_path):
    """
    Some zips (e.g. OEHHA's CalEnviroScreen 5.0 shapefile) nest the actual
    .shp/.dbf/.shx inside a subdirectory whose own name happens to end in
    `.shp`, which breaks GDAL's root-level shapefile auto-detection for a
    zip. Probe each top-level entry for a nested layer before giving up.
    """
    with zipfile.ZipFile(str(path)) as z:
        top_level_entries = {
            name.split('/', 1)[0]
            for name in z.namelist()
            if '/' in name
        }
    for entry in sorted(top_level_entries):
        candidate = f'{fiona_path}!/{entry}'
        if fiona.listlayers(candidate):
            return candidate
    return fiona_path
```

Then, in `stream_filtered_gdf`, change:

```python
    try:
        zipfile.ZipFile(str(path)).close()
        fiona_path = f'zip://{path}'
    except zipfile.BadZipFile:
        fiona_path = str(path)
```

to:

```python
    try:
        zipfile.ZipFile(str(path)).close()
        fiona_path = f'zip://{path}'
        if not fiona.listlayers(fiona_path):
            fiona_path = _resolve_nested_zip_shapefile(path, fiona_path)
    except zipfile.BadZipFile:
        fiona_path = str(path)
```

Everything else in `stream_filtered_gdf` (the `with fiona.open(fiona_path, ...)` block onward) is unchanged.

- [ ] **Step 3: Verify against CES5's real shapefile**

Run: `docker compose run --rm web python manage.py import_ces5 --print-columns`
Expected: this now gets past the shapefile-loading step (which is as far as this task needs to verify — full column-mapping correctness is Task 4's job, not this task's). If it still fails with `ValueError: Null layer` or similar, the fix isn't resolving the right entry — check that `top_level_entries` actually contains `calenviroscreen50results_F_070126.shp` (the directory name), not something else (e.g. verify `zipfile.ZipFile(path).namelist()` directly if needed).

- [ ] **Step 4: Re-run the Step 1 regression check to confirm no change for CES4**

Re-run the same shell snippet from Step 1 against CES4's cached zip. Expected: identical output to Step 1 — same non-empty layer list at the bare `zip://{path}` form, proving the new code path still doesn't activate for CES4's zip.

- [ ] **Step 5: Commit**

```bash
git add camp/utils/geodata.py
git commit -m "fix(geodata): resolve shapefiles nested in a zip subdirectory"
```

---

### Task 4: `import_ces5` management command

This command has no automated tests — matching the existing project convention for network-dependent data importers (`import_ces4`, `import_pur`, `import_comptox`, `import_carbtac` are all untested directly; they're verified by running against real data). Verification here is manual, via `--print-columns` and a real run against a dev database.

**Files:**
- Create: `camp/apps/ces/management/commands/import_ces5.py`

**Interfaces:**
- Consumes: `CES5`, `DACCategory` from `camp/apps/ces/models.py` (Task 2). `Boundary`, `Region` from `camp/apps/regions/models.py` (unchanged). `camp.utils.geodata.gdf_from_ckan`, `camp.utils.geodata.load_region_geometry` (unchanged, existing utility). `esri2gpd.get` (existing third-party dependency already used by `import_ces4`).
- Produces: `python manage.py import_ces5` — no other task depends on this programmatically; it populates the `CES5` table that the API (Task 5) reads from.

- [ ] **Step 1: Write the command**

Create `camp/apps/ces/management/commands/import_ces5.py`:

```python
import esri2gpd
import pandas as pd

from django.core.management.base import BaseCommand

from camp.apps.ces.models import CES5, DACCategory
from camp.apps.regions.models import Boundary, Region
from camp.utils import geodata
from camp.utils.geodata import load_region_geometry

# https://data.ca.gov/dataset/calenviroscreen-5-0
CES5_DATASET_ID = 'calenviroscreen-5-0'
CES5_RESOURCE_NAME = 'CalEnviroScreen 5.0 Shapefile'

# DRAFT 2026 SB535 DAC designation, based on CalEnviroScreen 5.0.
# CalEPA's public comment period runs through Aug 14, 2026 — this command
# is idempotent, so re-run it once the designation is finalized.
# https://calepa.ca.gov/programs/dac2026/
DRAFT_DAC_2026_URL = 'https://services1.arcgis.com/PCHfdHz4GlDNAhBb/arcgis/rest/services/DRAFT_SB535_Disadvantaged_Communities_2026/FeatureServer/0'

# Maps the draft layer's dac_type strings to DACCategory integer choices
DAC_CATEGORY_MAP = {
    'CES 5.0 Top 25%': DACCategory.TOP_CES_SCORE,
    'CES 5.0 High Pollution/Low Population': DACCategory.TOP_POLLUTION,
    'CES 4.0 Carry-Over DAC': DACCategory.PRIOR_DAC,
}

# Explicit mapping from CES5 shapefile columns to CES5 model fields.
# California-wide percentiles are preserved as published by OEHHA.
FIELD_MAP = {
    'zipcode':    'zipcode',
    'approx_loc': 'approx_loc',
    'county':     'county',
    'region':     'region_name',
    'ACS2024Pop': 'population',
    'CIscore':    'ci_score',
    'CIscoreP':   'ci_score_p',
    # Pollution burden
    'ozone':      'pol_ozone',
    'ozoneP':     'pol_ozone_p',
    'pm':         'pol_pm',
    'pmP':        'pol_pm_p',
    'diesel':     'pol_diesel',
    'dieselP':    'pol_diesel_p',
    'pest':       'pol_pest',
    'pestP':      'pol_pest_p',
    'RSEIhaz':    'pol_rsei_haz',
    'RSEIhazP':   'pol_rsei_haz_p',
    'traffic':    'pol_traffic',
    'trafficP':   'pol_traffic_p',
    'drink':      'pol_drink',
    'drinkP':     'pol_drink_p',
    'lead':       'pol_lead',
    'leadP':      'pol_lead_p',
    'cleanups':   'pol_cleanups',
    'cleanupsP':  'pol_cleanups_p',
    'gwthreats':  'pol_gwthreats',
    'gwthreatsP': 'pol_gwthreats_p',
    'haz':        'pol_haz',
    'hazP':       'pol_haz_p',
    'iwb':        'pol_iwb',
    'iwbP':       'pol_iwb_p',
    'SmATS':      'pol_small_ats',
    'SmATSP':     'pol_small_ats_p',
    'swis':       'pol_swis',
    'swisP':      'pol_swis_p',
    'Pollution':  'pollution',
    'PollutionS': 'pollution_s',
    'PollutionP': 'pollution_p',
    # Population characteristics
    'asthma':     'char_asthma',
    'asthmaP':    'char_asthma_p',
    'cvd':        'char_cvd',
    'cvdP':       'char_cvd_p',
    'diabetes':   'char_diabetes',
    'diabetesP':  'char_diabetes_p',
    'lbw':        'char_lbw',
    'lbwP':       'char_lbw_p',
    'edu':        'char_edu',
    'eduP':       'char_edu_p',
    'ling':       'char_ling',
    'lingP':      'char_ling_p',
    'pov':        'char_pov',
    'povP':       'char_pov_p',
    'unemp':      'char_unemp',
    'unempP':     'char_unemp_p',
    'housingB':   'char_housingb',
    'housingBP':  'char_housingb_p',
    'PopChar':    'popchar',
    'PopCharSco': 'popchar_s',
    'PopCharP':   'popchar_p',
    # Demographics (percentages)
    'pop_und10':  'pop_under_10_pct',
    'pop_10_64':  'pop_10_64_pct',
    'pop_ov64':   'pop_65_plus_pct',
    'hisp':       'pop_hispanic_pct',
    'white':      'pop_white_pct',
    'black':      'pop_black_pct',
    'amind':      'pop_native_pct',
    'asian':      'pop_asian_pct',
    'pacisl':     'pop_pacisl_pct',
    'othmult':    'pop_other_pct',
}


def _clean_value(v):
    """Convert NaN to None and snap float drift near -999 to exactly -999."""
    if pd.isna(v):
        return None
    if abs(v - (-999)) <= 1:
        return -999
    return v


class Command(BaseCommand):
    help = 'Import CalEnviroScreen 5.0 (2020 census tracts only — CES5 is natively 2020-vintage).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--print-columns',
            action='store_true',
            help='Print shapefile columns and their FIELD_MAP mapping, then exit.',
        )

    def handle(self, *args, **options):
        ces5 = self.get_ces5()

        if options['print_columns']:
            self.print_columns(ces5)
            return

        self.apply_dac_designation(ces5)

        self.stdout.write('\nSaving records...')
        self.save_records(ces5)
        self.stdout.write(self.style.SUCCESS('\n✓ Done'))

    def get_ces5(self):
        """Download and filter the CES5 shapefile to the SJV region."""
        gdf = geodata.gdf_from_ckan(
            dataset_id=CES5_DATASET_ID,
            resource_name=CES5_RESOURCE_NAME,
            string_fields=['tract'],
            limit_to_region=True,
            threshold=0.25,
        )
        gdf['tract'] = gdf['tract'].astype(str).str.zfill(11)
        self.stdout.write(f'Loaded {len(gdf):,} CES5 tracts')
        return gdf

    def apply_dac_designation(self, gdf):
        """
        Join the draft 2026 SB535 DAC designation onto `gdf` by tract GEOID,
        mutating it in place with `dac_sb535`/`dac_category` columns.

        This layer is a DRAFT (public comment through Aug 14, 2026). If it
        can't be fetched, warn and leave dac_sb535/dac_category null rather
        than failing the whole import — the indicator data is still valid.
        """
        try:
            counties_union = load_region_geometry()
            dac = esri2gpd.get(DRAFT_DAC_2026_URL)
        except Exception as exc:
            self.stdout.write(self.style.WARNING(
                f'⚠ Could not fetch draft DAC 2026 layer ({exc}); '
                'dac_sb535/dac_category will be left null for all tracts.'
            ))
            gdf['dac_sb535'] = None
            gdf['dac_category'] = None
            return

        dac = dac[
            dac.geometry.apply(
                lambda g: (not g.is_empty and g.area > 0
                           and g.intersects(counties_union)
                           and g.intersection(counties_union).area / g.area >= 0.50)
            )
        ]
        dac['tract'] = dac['tract'].astype(str).str.zfill(11)

        dac_lookup = dac.set_index('tract')['dac_type']
        gdf['dac_sb535'] = gdf['tract'].isin(dac_lookup.index)
        gdf['dac_category'] = (
            gdf['tract']
            .map(dac_lookup)
            .map(DAC_CATEGORY_MAP)
            .where(gdf['tract'].isin(dac_lookup.index), other=None)
        )

        missing = set(gdf['tract']) - set(dac_lookup.index)
        if missing:
            self.stdout.write(self.style.WARNING(
                f'⚠ {len(missing)} CES5 tracts not in the draft DAC 2026 layer '
                '(dac_sb535/dac_category left null for those tracts)'
            ))
        else:
            self.stdout.write('✓ All CES5 tracts present in the draft DAC 2026 layer')

    def save_records(self, gdf):
        """Upsert CES5 records for the 2020 vintage."""
        boundary_map = {
            b.region.external_id: b
            for b in (Boundary.objects
                .filter(region__type=Region.Type.TRACT, version='2020')
                .select_related('region')
            )
        }

        created_count = updated_count = skipped_count = 0

        for _, row in gdf.iterrows():
            geoid = str(row['tract']).zfill(11)
            boundary = boundary_map.get(geoid)

            if boundary is None:
                skipped_count += 1
                continue

            fields = {
                model_field: _clean_value(row.get(shp_col))
                for shp_col, model_field in FIELD_MAP.items()
                if shp_col in row.index
            }
            dac_sb535 = row.get('dac_sb535')
            fields['dac_sb535'] = None if pd.isna(dac_sb535) else bool(dac_sb535)
            dac_cat = row.get('dac_category')
            fields['dac_category'] = None if pd.isna(dac_cat) else int(dac_cat)

            _, created = CES5.objects.update_or_create(
                boundary=boundary,
                defaults=fields,
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            f'  2020: {created_count} created, '
            f'{updated_count} updated, {skipped_count} skipped'
        )

    def print_columns(self, gdf):
        """Print shapefile columns alongside their FIELD_MAP target for verification."""
        self.stdout.write('CES5 shapefile columns:')
        for col in sorted(gdf.columns):
            mapped = FIELD_MAP.get(col, '—')
            self.stdout.write(f'  {col:30s} → {mapped}')

        unmapped = [
            c for c in gdf.columns
            if c not in FIELD_MAP and c not in ('tract', 'geometry')
        ]
        if unmapped:
            self.stdout.write(self.style.WARNING(f'\n⚠ {len(unmapped)} unmapped columns: {unmapped}'))
```

- [ ] **Step 2: Verify column mapping against the live dataset**

Run: `docker compose run --rm web python manage.py import_ces5 --print-columns`
Expected: Every column prints with a `→ <model_field>` target and **zero** unmapped columns reported (the design spec already confirmed the full field list against the live shapefile — `tract` and `geometry` are the only columns intentionally excluded from `FIELD_MAP`, and they're excluded from the "unmapped" report). If this reports unmapped columns, OEHHA has changed the schema since this plan was written — cross-check against `docs/superpowers/specs/2026-07-11-calenviroscreen5-design.md`.

- [ ] **Step 3: Run a real import against your dev database**

Run: `docker compose run --rm web python manage.py import_ces5`
Expected: Output ending in `✓ Done`, with a `2020: N created, 0 updated, M skipped` summary line. `skipped` should be 0 or very small (tracts outside the SJV region boundary set).

- [ ] **Step 4: Spot-check a record in the admin or shell**

Run: `docker compose run --rm web python manage.py shell -c "from camp.apps.ces.models import CES5; r = CES5.objects.first(); print(r.tract, r.ci_score, r.pol_small_ats_p, r.char_diabetes_p, r.pop_hispanic_pct, r.dac_category)"`
Expected: Prints a real tract GEOID and populated indicator values (not all `None`).

- [ ] **Step 5: Commit**

```bash
git add camp/apps/ces/management/commands/import_ces5.py
git commit -m "feat(ces): add import_ces5 management command"
```

---

### Task 5: Restructure CES4's API — year as a query param

Moves CES4's `<year>` URL segment to an optional `?year=` query param (defaulting to `'2020'`), so CES4 and CES5 (Task 6) share the same URL shape.

This project has no static OpenAPI file to hand-edit — `resticus`'s
`SchemaGenerator` builds `/api/2.0/openapi.json` dynamically from each
endpoint's `filter_class` (query params), `serializer_class`/`model`
(response shape), and docstring (description). That means `year` must
become a **declared filter field**, not a value read only off
`request.GET`, or it silently disappears from the generated docs once it
moves off the URL path — this task adds it to `CES4Filter` for that reason,
not just for the query-param mechanics.

**Files:**
- Modify: `camp/api/v2/ces/urls.py`
- Modify: `camp/api/v2/ces/endpoints.py`
- Modify: `camp/api/v2/ces/filters.py`
- Modify: `camp/api/v2/ces/tests.py`
- Modify: `camp/api/v2/tests/test_openapi.py`

**Interfaces:**
- Consumes: `CES4`, `CES4Serializer` (unchanged).
- Produces: `CES4Filter` gains a declared `year` field. `filter_class = CES4Filter` moves from `CES4List` up to `CES4Mixin` (so it's documented on the Detail operation too — Detail's custom `get_object()` doesn't actually invoke the FilterSet; this is documentation-only, same as this codebase already treats `filter_class` elsewhere). `CES4Mixin.get_queryset()` now reads `year` from `self.request.GET` instead of `self.kwargs['year']`. URL names `ces4-list`/`ces4-detail` no longer take a `year` kwarg — only `tract` (for detail). Task 6's `CES5List`/`CES5Detail` follow the same `urls.py` file and reuse `generics.ListEndpoint`/`generics.DetailEndpoint` the same way.

- [ ] **Step 1: Update the failing tests first**

In `camp/api/v2/ces/tests.py`, replace the `year` kwarg usage. Change:

```python
    def test_list_2020_returns_two_records(self):
        url = reverse('api:v2:ces:ces4-list', kwargs={'year': '2020'})
        request = self.factory.get(url)
        response = ces4_list(request, year='2020')
        data = get_response_data(response)

        assert response.status_code == 200
        assert len(data['data']) == 2

    def test_list_2010_returns_two_records(self):
        url = reverse('api:v2:ces:ces4-list', kwargs={'year': '2010'})
        request = self.factory.get(url)
        response = ces4_list(request, year='2010')
        data = get_response_data(response)

        assert response.status_code == 200
        assert len(data['data']) == 2
```

to:

```python
    def test_list_2020_returns_two_records(self):
        url = reverse('api:v2:ces:ces4-list')
        request = self.factory.get(url, {'year': '2020'})
        response = ces4_list(request)
        data = get_response_data(response)

        assert response.status_code == 200
        assert len(data['data']) == 2

    def test_list_2010_returns_two_records(self):
        url = reverse('api:v2:ces:ces4-list')
        request = self.factory.get(url, {'year': '2010'})
        response = ces4_list(request)
        data = get_response_data(response)

        assert response.status_code == 200
        assert len(data['data']) == 2

    def test_list_defaults_to_2020_when_year_omitted(self):
        url = reverse('api:v2:ces:ces4-list')
        request = self.factory.get(url)
        response = ces4_list(request)
        data = get_response_data(response)

        assert response.status_code == 200
        assert len(data['data']) == 2
        assert all(r['census_year'] == '2020' for r in data['data'])
```

Change every remaining call site in the same file that passes `year=...` as a view kwarg to instead pass it via `self.factory.get('/', {'year': ...})` (or omit it to exercise the default). Specifically:

```python
    def test_list_records_have_expected_fields(self):
        request = self.factory.get('/')
        response = ces4_list(request)
        ...

    def test_list_census_year_matches_requested_year(self):
        request = self.factory.get('/')
        response = ces4_list(request)
        ...

    def test_detail_returns_correct_tract(self):
        tract = '06019000101'
        request = self.factory.get('/')
        response = ces4_detail(request, tract=tract)
        ...

    def test_detail_404_for_unknown_tract(self):
        request = self.factory.get('/')
        response = ces4_detail(request, tract='99999999999')

        assert response.status_code == 404

    def test_detail_404_for_wrong_year(self):
        # tract exists for 2020 but requesting 2030
        request = self.factory.get('/', {'year': '2030'})
        response = ces4_detail(request, tract='06019000101')

        assert response.status_code == 404

    def test_filter_by_dac_sb535(self):
        request = self.factory.get('/', {'dac_sb535': 'true'})
        response = ces4_list(request)
        ...

    def test_filter_by_ci_score_p_gte(self):
        request = self.factory.get('/', {'ci_score_p__gte': '80'})
        response = ces4_list(request)
        ...
```

And in `CES4RegionFilterTests`, every `reverse('api:v2:ces:ces4-list', kwargs={'year': '2020'})` becomes `reverse('api:v2:ces:ces4-list')` with `year=2020` merged into the existing query-param dict, e.g.:

```python
    def test_region_covering_both_tracts_returns_two(self):
        region = self._create_region(self.COVERS_BOTH)
        url = reverse('api:v2:ces:ces4-list')
        data = self.client.get(url, {'region_id': region.sqid, 'year': '2020'}).json()
        assert data['count'] == 2
```

(apply the same `year: '2020'` addition to `test_region_covering_one_tract_returns_one`, `test_region_outside_tracts_returns_empty`, `test_region_without_boundary_returns_empty`, and `test_invalid_region_id_returns_empty` — all currently pass `kwargs={'year': '2020'}` to `reverse()`.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose run --rm test pytest camp/api/v2/ces/tests.py -v`
Expected: FAIL — `reverse()` calls raise `NoReverseMatch` (URL still requires a `year` kwarg) or view calls raise `TypeError` (view still requires a `year` argument).

- [ ] **Step 3: Update the URL conf**

In `camp/api/v2/ces/urls.py`, change:

```python
urlpatterns = [
    path('4.0/<str:year>/', endpoints.CES4List.as_view(), name='ces4-list'),
    path('4.0/<str:year>/<str:tract>/', endpoints.CES4Detail.as_view(), name='ces4-detail'),
]
```

to:

```python
urlpatterns = [
    path('4.0/', endpoints.CES4List.as_view(), name='ces4-list'),
    path('4.0/<str:tract>/', endpoints.CES4Detail.as_view(), name='ces4-detail'),
]
```

- [ ] **Step 4: Add `year` as a declared filter field**

In `camp/api/v2/ces/filters.py`, add a `year` field to `CES4Filter` (right above the existing `region_id` field is fine):

```python
class CES4Filter(FilterSet):
    year = django_filters.CharFilter(field_name='boundary__version')
    region_id = django_filters.CharFilter(method='filter_region_id')
```

This doesn't change `CES4Filter`'s actual filtering behavior in a way that conflicts with Step 5 below — when `?year=` is provided, this filter and `CES4Mixin`'s own default-handling both resolve to the same value, so the `.filter(boundary__version=...)` call is redundant but not contradictory. Its purpose here is to make `year` show up in the generated OpenAPI schema (Step 7), which is the only mechanism this project's schema generator has for documenting GET query parameters.

- [ ] **Step 5: Update the endpoint**

In `camp/api/v2/ces/endpoints.py`, change:

```python
class CES4Mixin:
    model = CES4
    serializer_class = CES4Serializer
    paginate = True

    def get_queryset(self):
        return (
            super().get_queryset()
            .filter(boundary__version=self.kwargs['year'])
        )


class CES4List(CES4Mixin, generics.ListEndpoint):
    """List CalEnviroScreen 4.0 scores for all census tracts for a given year."""

    filter_class = CES4Filter


class CES4Detail(CES4Mixin, generics.DetailEndpoint):
    """Retrieve the CalEnviroScreen 4.0 score for a specific census tract."""
    def get_object(self):
        try:
            return self.get_queryset().get(
                boundary__region__external_id=self.kwargs['tract']
            )
        except CES4.DoesNotExist:
            raise Http404
```

to:

```python
class CES4Mixin:
    model = CES4
    serializer_class = CES4Serializer
    paginate = True
    filter_class = CES4Filter

    def get_queryset(self):
        year = self.request.GET.get('year') or '2020'
        return (
            super().get_queryset()
            .filter(boundary__version=year)
        )


class CES4List(CES4Mixin, generics.ListEndpoint):
    """List CalEnviroScreen 4.0 scores for all census tracts for a given year (default 2020)."""


class CES4Detail(CES4Mixin, generics.DetailEndpoint):
    """Retrieve the CalEnviroScreen 4.0 score for a specific census tract."""
    def get_object(self):
        try:
            return self.get_queryset().get(
                boundary__region__external_id=self.kwargs['tract']
            )
        except CES4.DoesNotExist:
            raise Http404
```

Moving `filter_class` up to `CES4Mixin` (instead of only on `CES4List`) means both the list and detail operations document `year`/`region_id`/etc. in the OpenAPI schema, not just list.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `docker compose run --rm test pytest camp/api/v2/ces/tests.py -v`
Expected: All tests PASS, including the new `test_list_defaults_to_2020_when_year_omitted`.

- [ ] **Step 7: Add and verify an OpenAPI schema assertion for `year`**

Append to `camp/api/v2/tests/test_openapi.py` (this file already has a `setUp` that loads `self.paths` from the live schema — see the existing tests in that file for the pattern):

```python
    def test_ces4_paths_are_documented(self):
        assert any(p.endswith('calenviroscreen/4.0/') for p in self.paths)
        assert any(p.endswith('calenviroscreen/4.0/{tract}/') for p in self.paths)

    def test_ces4_year_query_param_is_documented(self):
        list_params = self.paths['/calenviroscreen/4.0/']['get']['parameters']
        assert any(p['name'] == 'year' for p in list_params)
        detail_params = self.paths['/calenviroscreen/4.0/{tract}/']['get']['parameters']
        assert any(p['name'] == 'year' for p in detail_params)
```

Run: `docker compose run --rm test pytest camp/api/v2/tests/test_openapi.py -v`
Expected: All tests PASS, including the two new ones. If the exact path strings don't match (e.g. a leading/trailing slash differs from what `self.paths` actually contains), run `docker compose run --rm test pytest camp/api/v2/tests/test_openapi.py -v -s` and inspect `self.paths.keys()` by temporarily adding `print(list(self.paths))` in `setUp`, then fix the assertions to match — don't guess.

- [ ] **Step 8: Commit**

```bash
git add camp/api/v2/ces/urls.py camp/api/v2/ces/endpoints.py camp/api/v2/ces/filters.py camp/api/v2/ces/tests.py camp/api/v2/tests/test_openapi.py
git commit -m "refactor(api): move CES4's year from URL path to query param"
```

---

### Task 6: CES5 API — serializer, filter, endpoints, urls

**Files:**
- Modify: `camp/api/v2/ces/serializers.py` (append `CES5Serializer`)
- Modify: `camp/api/v2/ces/filters.py` (append `CES5Filter`)
- Modify: `camp/api/v2/ces/endpoints.py` (append `CES5Mixin`, `CES5List`, `CES5Detail`)
- Modify: `camp/api/v2/ces/urls.py` (append CES5 paths)
- Modify: `camp/api/v2/ces/tests.py` (append `CES5EndpointTests`, `CES5RegionFilterTests`)
- Modify: `camp/api/v2/tests/test_openapi.py` (append CES5 path assertions, alongside Task 5's CES4 assertions)

**Interfaces:**
- Consumes: `CES5` model (Task 2). `Region`, `Boundary` from `camp.apps.regions.models` (unchanged). `resticus.generics`, `resticus.serializers`, `resticus.filters.FilterSet`, `django_filters` (unchanged, same libraries CES4 already uses). Task 5's `filter_class`-on-`Mixin` pattern (this task follows the same convention for `CES5Mixin`).
- Produces: URL names `ces5-list`, `ces5-detail` under namespace `api:v2:ces`. No later task depends on this.

- [ ] **Step 1: Write the failing tests first**

Append to `camp/api/v2/ces/tests.py`:

```python
from camp.apps.ces.models import CES5

ces5_list = endpoints.CES5List.as_view()
ces5_detail = endpoints.CES5Detail.as_view()


class CES5EndpointTests(TestCase):
    fixtures = ['calenviroscreen']

    def setUp(self):
        self.factory = RequestFactory()

    def test_list_returns_two_records(self):
        request = self.factory.get('/')
        response = ces5_list(request)
        data = get_response_data(response)

        assert response.status_code == 200
        assert len(data['data']) == 2

    def test_list_records_have_expected_fields(self):
        request = self.factory.get('/')
        response = ces5_list(request)
        data = get_response_data(response)

        record = data['data'][0]
        assert 'id' in record
        assert 'tract' in record
        assert 'census_year' in record
        assert 'ci_score' in record
        assert 'dac_sb535' in record
        assert 'region_name' in record
        assert 'pol_small_ats_p' in record
        assert 'char_diabetes_p' in record
        assert 'pop_hispanic_pct' in record

    def test_detail_returns_correct_tract(self):
        tract = '06019000101'
        request = self.factory.get('/')
        response = ces5_detail(request, tract=tract)
        data = get_response_data(response)

        assert response.status_code == 200
        assert data['data']['tract'] == tract
        assert data['data']['census_year'] == '2020'

    def test_detail_404_for_unknown_tract(self):
        request = self.factory.get('/')
        response = ces5_detail(request, tract='99999999999')

        assert response.status_code == 404

    def test_filter_by_dac_sb535(self):
        request = self.factory.get('/', {'dac_sb535': 'true'})
        response = ces5_list(request)
        data = get_response_data(response)

        assert response.status_code == 200
        assert len(data['data']) == 1
        assert data['data'][0]['dac_sb535'] is True

    def test_filter_by_ci_score_p_gte(self):
        request = self.factory.get('/', {'ci_score_p__gte': '80'})
        response = ces5_list(request)
        data = get_response_data(response)

        assert response.status_code == 200
        assert all(r['ci_score_p'] >= 80 for r in data['data'])


class CES5RegionFilterTests(TestCase):
    # Same fixture tracts as CES4RegionFilterTests (2020 boundaries):
    #   Tract 1.01: lon -119.8 to -119.7, lat 36.7 to 36.8
    #   Tract 1.02: lon -119.7 to -119.6, lat 36.7 to 36.8
    fixtures = ['calenviroscreen']

    COVERS_BOTH = 'MULTIPOLYGON (((-119.9 36.6, -119.5 36.6, -119.5 36.9, -119.9 36.9, -119.9 36.6)))'
    COVERS_ONLY_1_01 = 'MULTIPOLYGON (((-119.9 36.6, -119.71 36.6, -119.71 36.9, -119.9 36.9, -119.9 36.6)))'

    def _create_region(self, geometry_wkt):
        region = Region.objects.create(
            name='Test City', slug='test-city-ces5', type=Region.Type.CITY, external_id='9998',
        )
        boundary = Boundary.objects.create(
            region=region, version='2020',
            geometry=GEOSGeometry(geometry_wkt, srid=4326),
        )
        region.boundary = boundary
        region.save()
        return region

    def test_region_covering_both_tracts_returns_two(self):
        region = self._create_region(self.COVERS_BOTH)
        url = reverse('api:v2:ces:ces5-list')
        data = self.client.get(url, {'region_id': region.sqid}).json()
        assert data['count'] == 2

    def test_region_covering_one_tract_returns_one(self):
        region = self._create_region(self.COVERS_ONLY_1_01)
        url = reverse('api:v2:ces:ces5-list')
        data = self.client.get(url, {'region_id': region.sqid}).json()
        assert data['count'] == 1
        assert data['data'][0]['tract'] == '06019000101'
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose run --rm test pytest camp/api/v2/ces/tests.py::CES5EndpointTests -v`
Expected: FAIL — `endpoints.CES5List` doesn't exist yet (`AttributeError`).

- [ ] **Step 3: Add the serializer**

Append to `camp/api/v2/ces/serializers.py`:

```python
class CES5Serializer(serializers.Serializer):
    fields = (
        ('id', lambda r: r.sqid),
        ('tract', lambda r: r.tract),
        ('census_year', lambda r: r.census_year),
        'zipcode',
        'approx_loc',
        'county',
        'region_name',
        'population',
        'ci_score',
        'ci_score_p',
        'dac_sb535',
        ('dac_category', lambda r: r.get_dac_category_display()),
        # Pollution burden
        'pollution',
        'pollution_s',
        'pollution_p',
        'pol_ozone',
        'pol_ozone_p',
        'pol_pm',
        'pol_pm_p',
        'pol_diesel',
        'pol_diesel_p',
        'pol_pest',
        'pol_pest_p',
        'pol_rsei_haz',
        'pol_rsei_haz_p',
        'pol_traffic',
        'pol_traffic_p',
        'pol_drink',
        'pol_drink_p',
        'pol_lead',
        'pol_lead_p',
        'pol_cleanups',
        'pol_cleanups_p',
        'pol_gwthreats',
        'pol_gwthreats_p',
        'pol_haz',
        'pol_haz_p',
        'pol_iwb',
        'pol_iwb_p',
        'pol_small_ats',
        'pol_small_ats_p',
        'pol_swis',
        'pol_swis_p',
        # Population characteristics
        'popchar',
        'popchar_s',
        'popchar_p',
        'char_asthma',
        'char_asthma_p',
        'char_cvd',
        'char_cvd_p',
        'char_diabetes',
        'char_diabetes_p',
        'char_lbw',
        'char_lbw_p',
        'char_edu',
        'char_edu_p',
        'char_ling',
        'char_ling_p',
        'char_pov',
        'char_pov_p',
        'char_unemp',
        'char_unemp_p',
        'char_housingb',
        'char_housingb_p',
        # Demographics
        'pop_under_10_pct',
        'pop_10_64_pct',
        'pop_65_plus_pct',
        'pop_hispanic_pct',
        'pop_white_pct',
        'pop_black_pct',
        'pop_native_pct',
        'pop_asian_pct',
        'pop_pacisl_pct',
        'pop_other_pct',
    )
```

- [ ] **Step 4: Add the filter**

Append to `camp/api/v2/ces/filters.py`. First update the import line:

```python
from camp.apps.ces.models import CES4
```

to:

```python
from camp.apps.ces.models import CES4, CES5
```

Then append:

```python
class CES5Filter(FilterSet):
    region_id = django_filters.CharFilter(method='filter_region_id')

    def filter_region_id(self, queryset, name, value):
        try:
            region = Region.objects.select_related('boundary').get(sqid=value)
        except Region.DoesNotExist:
            return queryset.none()
        try:
            geometry = region.boundary.geometry
        except AttributeError:
            return queryset.none()
        return queryset.filter(boundary__geometry__intersects=geometry)

    class Meta:
        model = CES5
        fields = {
            'dac_sb535': ['exact'],
            'dac_category': ['exact'],
            'ci_score': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'ci_score_p': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'pollution_p': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'popchar_p': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'pol_pm_p': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'pol_ozone_p': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'pol_diesel_p': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'pol_traffic_p': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'pol_small_ats_p': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'char_diabetes_p': ['exact', 'lt', 'lte', 'gt', 'gte'],
        }
```

- [ ] **Step 5: Add the endpoints**

Append to `camp/api/v2/ces/endpoints.py`. First update the import line:

```python
from camp.apps.ces.models import CES4
```

to:

```python
from camp.apps.ces.models import CES4, CES5
```

and:

```python
from .filters import CES4Filter
from .serializers import CES4Serializer
```

to:

```python
from .filters import CES4Filter, CES5Filter
from .serializers import CES4Serializer, CES5Serializer
```

Then append, after `CES4Detail`:

```python
class CES5Mixin:
    model = CES5
    serializer_class = CES5Serializer
    paginate = True
    filter_class = CES5Filter


class CES5List(CES5Mixin, generics.ListEndpoint):
    """List CalEnviroScreen 5.0 scores for all census tracts."""


class CES5Detail(CES5Mixin, generics.DetailEndpoint):
    """Retrieve the CalEnviroScreen 5.0 score for a specific census tract."""
    def get_object(self):
        try:
            return self.get_queryset().get(
                boundary__region__external_id=self.kwargs['tract']
            )
        except CES5.DoesNotExist:
            raise Http404
```

`filter_class` goes on `CES5Mixin` (shared by List and Detail), the same pattern as Task 5's `CES4Mixin` change — this documents CES5's query params (`region_id`, `dac_sb535`, `pol_small_ats_p`, etc.) on both operations in the OpenAPI schema, consistent with how `filter_class` is used purely as a schema-introspection surface elsewhere in this codebase.

- [ ] **Step 6: Add the URLs**

In `camp/api/v2/ces/urls.py`, append to `urlpatterns`:

```python
    path('5.0/', endpoints.CES5List.as_view(), name='ces5-list'),
    path('5.0/<str:tract>/', endpoints.CES5Detail.as_view(), name='ces5-detail'),
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `docker compose run --rm test pytest camp/api/v2/ces/tests.py -v`
Expected: All tests PASS, including `CES4EndpointTests`, `CES4RegionFilterTests`, `CES5EndpointTests`, and `CES5RegionFilterTests`.

- [ ] **Step 8: Add and verify OpenAPI schema assertions for the CES5 paths**

Append to `camp/api/v2/tests/test_openapi.py` (alongside the `test_ces4_*` tests added in Task 5):

```python
    def test_ces5_paths_are_documented(self):
        assert any(p.endswith('calenviroscreen/5.0/') for p in self.paths)
        assert any(p.endswith('calenviroscreen/5.0/{tract}/') for p in self.paths)

    def test_ces5_has_no_year_query_param(self):
        # CES5 has only one vintage, so unlike CES4 it should NOT document a year param.
        list_params = self.paths['/calenviroscreen/5.0/']['get']['parameters']
        assert not any(p['name'] == 'year' for p in list_params)
```

Run: `docker compose run --rm test pytest camp/api/v2/tests/test_openapi.py -v`
Expected: All tests PASS, including the two new ones and the two `test_ces4_*` tests added in Task 5 (run the whole file, not just the new tests, since this file has no per-task isolation).

- [ ] **Step 9: Run the full test suite as a final regression check**

Run: `docker compose run --rm test pytest camp/apps/ces/ camp/api/v2/ces/ camp/api/v2/tests/test_openapi.py -v`
Expected: All tests PASS.

- [ ] **Step 10: Commit**

```bash
git add camp/api/v2/ces/serializers.py camp/api/v2/ces/filters.py camp/api/v2/ces/endpoints.py camp/api/v2/ces/urls.py camp/api/v2/ces/tests.py camp/api/v2/tests/test_openapi.py
git commit -m "feat(api): add CES5 endpoints"
```

---

## Self-review notes

- **Spec coverage:** Model (Task 2), admin (Task 3), importer (Task 4), CES4 URL restructure (Task 5), CES5 API (Task 6), and the `DACCategory` label refinement (Task 1) all map directly to sections in the design spec. Fixtures/tests are folded into Tasks 2 and 6 per the spec's "Tests & fixtures" section.
- **Field name consistency:** `FIELD_MAP` in Task 4 was cross-checked field-by-field against the model definition in Task 2 and the serializer in Task 6 — every model field has exactly one `FIELD_MAP` source column (except the inherited `boundary`/`dac_sb535`/`dac_category`, which are set separately) and appears in `CES5Serializer.fields`.
- **No automated importer tests:** Called out explicitly in Task 4 rather than glossed over — this matches existing project convention for network-dependent importers, not an oversight.
- **OpenAPI schema coverage:** Added after discovering (mid-plan) that this project's schema is generated dynamically by `resticus.schemas.SchemaGenerator` from each endpoint's `filter_class`/`serializer_class`/docstring — there's no static file to update. This forced a design change: `year` had to become a declared `CES4Filter` field (Task 5) rather than a bare `request.GET` read, or it would silently vanish from the docs when it moved off the URL path. Both Tasks 5 and 6 now assert the generated schema directly via `camp/api/v2/tests/test_openapi.py`.
- **`sqid` convention:** Added after `CLAUDE.md`/memory were updated mid-session to require sqids on all new models, then extended (at the user's request) to retrofit CES4 too, since nothing downstream depends on CES4 data yet. New Task 1.5 gives `CES4` its own `sqid = SqidsField(alphabet=shuffle_alphabet('ces.CES4'))`; Task 2 gives `CES5` `shuffle_alphabet('ces.CES5')`. Each is declared independently on its own concrete model, deliberately NOT hoisted onto the shared `CESRecord` abstract base — `shuffle_alphabet` bakes in a fixed alphabet string at field-declaration time, and abstract-field inheritance clones that same field object into every subclass, so a single declaration on `CESRecord` would give CES4 and CES5 identical alphabets and colliding sqid strings for rows sharing the same integer `id`. Both are exposed as `id` in their respective serializers (Task 1.5, Task 6), matching `camp/apps/ceidars/`'s pattern. This doesn't change the tract-GEOID-based detail lookup already designed and approved for either version.
