# Pesticide place filters and metadata: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `pesticides/place/` takes our ids with `invalid`/`not_found` codes, plus `narrow`,
`product`, several categories and `aerial_ground=none`. A new `pesticides/meta/` serves the
labels. The catalog gains `applications` and the meta links. `search/` gains `more` and a
chemical `placeholder` flag.

**Architecture:** Everything lives in the API layer (`camp/api/v2/pesticides/`) and the
catalog. The explorer helpers (`stats.narrow_rows`, `stats.METHOD_LABELS`, `NARROW_CHOICES`,
`notes`, `forms.UNASSIGNED_CATEGORIES`, `places.monthly_use`) are read, never changed.

**Tech Stack:** Django 5.2, django-resticus, django_sqids, PostGIS.

**Spec:** `docs/superpowers/specs/2026-11-06-pesticide-place-filters-design.md`

## Global Constraints

- **Files that may change:** `camp/api/v2/pesticides/{endpoints,urls,serializers,tests}.py`,
  a new `camp/api/v2/pesticides/meta.py`, `camp/api/v2/meta/catalog.py`, its
  `tests/test_catalog.py` and `tests/catalog_snapshot.json`, and `CLAUDE.md`. Nothing in
  `camp/apps/pesticides/`, `sections.py`, `locations.py` or `filters.py`.
- **Errors on `place/`:** an invalid value is a 400 `{"errors": {field: [{"message", "code"}]}}`
  with `Cache-Control: no-cache`. Codes: `"invalid"` (undecodable or non-canonical sqid, unknown
  category/narrow/method), `"not_found"` (canonical sqid, no row).
- **Method keys:** `G A F O none`, labels Ground, Air, Field fumigation, Other, Not reported, in
  `stats.METHOD_ORDER`.
- **Narrow keys:** `concern restricted fumigant aerial`. One at a time.
- **Tests:** `django.test.TestCase`, pytest-style `assert`, fixture `pesticides-explorer` with
  `RollupTestMixin`.
- **Test runs:** on the database `sjvair_pestfilt`, using the scratchpad `run.sh` recipe
  (`DBNAME=sjvair_pestfilt …/scratchpad/run.sh <log> pytest …`). The script mounts the
  `fix-ids-smoke-index` worktree, so point a copy at this worktree first.
- No AI attribution. Never merge without the user's yes. Nothing touches production.

## Review Focus

1. **A sqid with surrounding spaces, or a non-canonical spelling** of a real id: spaces are
   stripped (form `CharField`) and the value then answers; a non-canonical spelling is
   `invalid`, never a silent match. Task 1: `test_id_spellings`.
2. **Mixed category forms** (`category=a,b&category=c`, blanks such as `a,,b`): one OR set,
   blanks ignored, and the same cache key in any order. Task 2: `test_category_forms_share_cache_key`.
3. **`narrow` with `chemical`:** the chemical scope's counting wins. Task 2: the counting-rule
   tests.
4. **`product` with `category`:** multi-chemical counting (category wins over once). Task 2:
   the counting-rule tests.
5. **A placeholder chemical id as `chemical`:** answers 200 with 0 lbs but counted applications,
   not an error. Task 3: `test_placeholder_chemical_scope`.

---

### Task 0: Baseline

- [ ] Point a copy of the scratchpad `run.sh` at this worktree (`run-pest.sh`). Run
  `DBNAME=sjvair_pestfilt run-pest.sh baseline pytest -n 4 --dist loadscope -q`.
  Expected: record the counts (develop was 4501 passed, 5 skipped).

### Task 1: Our ids on `place/`, with error codes

**Files:** Modify `camp/api/v2/pesticides/endpoints.py` (`PesticidePlaceForm`,
`PesticidePlace.get`). Test `camp/api/v2/pesticides/tests.py` (`PesticidePlaceTests`).

**Interfaces:**
- Produces: a `forms.CharField` subclass `SqidChoiceField(model)` whose
  `clean()` returns the model instance (or `None` when blank). It raises
  `ValidationError(..., code='invalid')` when `sqids_instance.decode(value)` is empty, has more
  than one number, or `sqids_instance.encode(decoded) != value`. It raises
  `ValidationError(..., code='not_found')` when the pk has no row. The decoder is
  `model._meta.get_field('sqid').sqids_instance`.
- Produces: the form fields `chemical`, `commodity` and `product` are `SqidChoiceField`s for
  Chemical, Commodity and Product. `build()` filters `chemical_id=`, `commodity_id=` and
  `product_id=`.

- [ ] **Step 1: Update and add tests**
  - Existing `test_filters`: `chemical=253` becomes
    `chemical=Chemical.objects.get(chem_code=253).sqid`. Same assertions.
  - Existing `test_bad_filter_values_are_400`: drop the numeric `chemical` cases (0, 2**31).
    Keep `'x'`.
  - Replace `test_odd_commodity_values_answer_200_with_safe_keys` with
    `test_odd_id_values_are_invalid`: each of `'a b'`, `'x'*300` and `'tab\there'` for
    `commodity` gives 400 with `errors['commodity'][0]['code'] == 'invalid'`.
  - `test_codes_are_refused`: `chemical=253` gives 400 `invalid` or `not_found` (a digit
    string may decode), never a 200 with data. `product=<a product's prodno>` gives the same.
  - `test_unknown_id_is_not_found`: encode `Chemical.objects.order_by('-pk')[0].pk + 1000`
    with the field's `sqids_instance`, and expect 400 with code `not_found`. Same for commodity
    and product.
  - `test_id_spellings`: `' <sqid> '` answers 200 and matches the plain sqid's data. The
    sqid's non-canonical spelling (decode → encode yields the canonical; build a
    non-canonical one with `sqids_instance.encode([pk])` plus the alphabet's first character
    appended when that still decodes, or skip with a comment if none exists) gives `invalid`.
  - `test_commodity_and_product_filter`: `commodity=<sqid>` gives the same data as filtering
    the rollup by that commodity. `product=<sqid>` gives the same for the product (compute the
    expected with `places.monthly_use` on `rollup_rows_for(place).filter(product=p)`, once
    rule).
- [ ] **Step 2:** `run-pest.sh t1-red pytest camp/api/v2/pesticides/tests.py -k PesticidePlace -q`.
  Expected: the new and updated tests fail (codes are still accepted, there's no product
  field, commodity answers 200).
- [ ] **Step 3:** Implement `SqidChoiceField` and the three fields. Filter by FK id.
- [ ] **Step 4:** Rerun. Expected: `PesticidePlaceTests` pass.
- [ ] **Step 5:** Commit `Pesticide place: filter by our ids, with invalid and not_found codes`.

### Task 2: `narrow`, several categories, `aerial_ground=none`, counting rule

**Files:** Modify `camp/api/v2/pesticides/endpoints.py`. Test `tests.py`.

**Interfaces:**
- Consumes: Task 1's form.
- Produces: `counting_mode(filters: dict) -> tuple[bool, bool]`, returning
  `(chemical_scoped, multi_chemical)` for `places.monthly_use`:
  - `chemical` → `(True, False)`;
  - else `category` or `iarc_group` → `(False, True)`;
  - else `(False, False)`.

  `narrow` never makes it multi.
- Produces: form fields:
  - `narrow` is a `ChoiceField` over `stats.NARROW_VALUES`;
  - `category` gives a sorted, deduplicated list of `Chemical.Category` values, from repeated
    params and comma lists, blanks dropped. An unknown value is an `invalid` error naming it.
    Read the raw list with `request.GET.getlist('category')`, passed through the form's `data`
    as a `QueryDict`;
  - `aerial_ground` accepts `none`, which maps to `''`.

- [ ] **Step 1: Tests**
  - `test_counting_mode`: a table of filter dicts to expected tuples, covering chemical alone;
    chemical+narrow; chemical+category; category alone; iarc alone; product+category; product
    alone; each `narrow` alone; commodity; method; empty.
  - `test_narrow_matches_stats`: for each narrow value, the response's `years` equals
    `places.monthly_use(stats.narrow_rows(rollup_rows_for(place), narrow), False, False)`'s
    years.
  - `test_unknown_narrow_is_400`: `narrow=nope` gives 400 `invalid`.
  - `test_several_categories_overlap`: with two categories, the pounds equal the rows whose
    chemical has either category (expected from `rows.filter(chemical__categories__overlap=[a, b])`
    with `multi_chemical=True`). A single category is unchanged from today.
  - `test_category_forms_share_cache_key`: spy `stats.cached` as in the old commodity test.
    `category=a,b`, `category=b&category=a` and `category=a,,b` produce one identical key. An
    unknown category gives 400 whose message names it.
  - `test_aerial_ground_none`: equals the rows with `method=''`, using the once rule. Add a
    rollup row with a blank method in the test if the fixture has none.
- [ ] **Step 2:** Run `-k PesticidePlace`. Expected: the new tests fail.
- [ ] **Step 3:** Implement the fields. `build()` applies `stats.narrow_rows(rows, narrow)`,
  `chemical__categories__overlap=categories` and `method=''` for `none`. Use `counting_mode`.
  Hash the normalized filters (a list sorted) into the cache key as today.
- [ ] **Step 4:** Rerun. Expected: pass.
- [ ] **Step 5:** Commit `Pesticide place: narrow, several categories, not-reported method`.

### Task 3: Placeholder flag

**Files:** Modify `camp/api/v2/pesticides/serializers.py` (`ChemicalSerializer`). Test
`tests.py`.

- [ ] **Step 1: Tests**
  - `test_chemical_serializer_placeholder`: `chemicals/` shows `placeholder: false` for 253.
    A created `Chemical(chem_code=-2, name='AI IS CONFIDENTIAL')` shows `true` in `chemicals/`
    and in `chemicals/<id>/`.
  - `test_placeholder_records_count` (`PesticidePlaceTests`): create that chemical plus one
    `PesticideUseRollup` row in Fresno 2023 with `lbs_chemical=0`, `records=1` and
    `acres_once=5`, then rebuild nothing (insert directly). The unfiltered county 2023
    applications and acres rise by 1 and 5.
  - `test_placeholder_chemical_scope`: `chemical=<placeholder sqid>` gives 200 with pounds 0.
- [ ] **Step 2:** Run. Expected: the serializer test fails; the counting tests may already pass
  (no code is needed there). Note which.
- [ ] **Step 3:** Add `('placeholder', lambda c: c.is_placeholder)` to `ChemicalSerializer`.
- [ ] **Step 4:** Run the whole `camp/api/v2/pesticides/tests.py`. Expected: pass. Nested uses
  (region summary) gain the key, and their tests must still pass.
- [ ] **Step 5:** Commit `Pesticide chemicals: placeholder flag`.

### Task 4: `search/` gains `more` and `placeholder`

**Files:** Modify `EntitySearchBase.get` in `endpoints.py`. Test `EntitySearchTests`.

- [ ] **Step 1: Tests**
  - `test_more_flag`: with `limit=1` and a query matching 2 or more, `more is True` and
    `len(results) == 1`. With a limit at or above the matches, `more is False`. Fewer than 2
    characters gives `{'results': [], 'more': False}`.
  - `test_chemical_results_flag_placeholder`: a placeholder chemical with use in
    `PesticideUseTotal` shows `placeholder: True`; 253 shows `False`. Product and commodity
    results have no `placeholder` key.
  - Existing `EntitySearchTests` stay unchanged and pass. In particular, result order and ids
    stay the same.
- [ ] **Step 2:** Run `-k EntitySearch`. Expected: the new tests fail.
- [ ] **Step 3:** Slice `limit + 1`, set `more`, return `limit` results. Add `placeholder` for
  `kind == 'chemical'`.
- [ ] **Step 4:** Rerun. Expected: pass.
- [ ] **Step 5:** Commit `Pesticide search: more flag and placeholder on chemicals`.

### Task 5: `pesticides/meta/` and the catalog

**Files:** Create `camp/api/v2/pesticides/meta.py` (`PesticidesMeta` endpoint plus builders).
Modify `urls.py` (`path('meta/', meta.PesticidesMeta.as_view(), name='pesticides-meta')`, before
`<str:…>` routes) and `camp/api/v2/meta/catalog.py`. Test `tests.py` (`PesticidesMetaTests`),
`test_catalog.py` and the snapshot.

**Interfaces:** the shape exactly as in spec §2. Sources:
- `Chemical.Category` (model order) for categories. `in_use = value not in
  forms.UNASSIGNED_CATEGORIES`. `description` is the `notes.note(key)['summary']`, with keys
  `prop65` for carcinogen, reproductive and developmental; `carb_tac` for TAC; the category
  value itself otherwise.
- `Chemical.IARCGroup` for IARC groups. Split each label on `' – '` into `label`
  (`"Group 2A"`) and `description`.
- `stats.METHOD_ORDER` / `METHOD_LABELS` for methods, with `''` → key `none`.
- `stats.NARROW_CHOICES` for narrows. Descriptions are new constants in `meta.py`. The
  `aerial` one is `stats.NARROW_HELP['aerial']`. The `restricted` and `fumigant` ones say
  they're product properties, unlike the `category` values of the same name.
- `Chemical.objects.filter(chem_code__in=Chemical.PLACEHOLDER_CODES)`, ordered by
  `chem_code`, for placeholder chemicals.

Response: `public, max-age=86400`. The docstring says `methods` are PUR's.

- [ ] **Step 1: Tests**
  - `PesticidesMetaTests.test_shape`: the top-level keys; ten categories in model order;
    `in_use` false exactly for the four; carcinogen's description equals
    `notes.note('prop65')['summary']`; IARC `2A` label `"Group 2A"`; methods equal
    `[('G','Ground'),('A','Air'),('F','Field fumigation'),('O','Other'),('none','Not reported')]`;
    four narrows; the cache header.
  - `test_placeholder_chemicals`: a created `-1` chemical is listed with its sqid.
  - `test_catalog.py`: `dataset_entry_types('pesticide-use') == ['pounds-applied',
    'acres-treated', 'applications']` (line 99) and the expected set at line 172.
    `applications` display is `{'precision': 0, 'chart': 'bar', 'y_min': 0}` with units
    `'applications'`. Both pesticide datasets' `meta_url == reverse('api:v2:pesticides:pesticides-meta')`.
- [ ] **Step 2:** Run `-k "PesticidesMeta"` and `camp/api/v2/meta`. Expected: they fail.
- [ ] **Step 3:** Implement `meta.py`, the URL, the catalog entry (`_other('applications',
  'Applications', 'applications', ['month','year'])`), `DISPLAY_OVERRIDES['applications'] =
  (0, 'bar', 0)` and the two `meta_url`s.
- [ ] **Step 4:** Regenerate the snapshot (`WRITE_CATALOG_SNAPSHOT=1`). Check that its diff is
  only the two `meta_url`s and the new entry. Rerun. Expected: pass.
- [ ] **Step 5:** Commit `Pesticides meta endpoint; catalog applications and meta links`.

### Task 6: Docs, full suite, review, PR

- [ ] **Step 1:** `CLAUDE.md`: update the "Pesticide place" bullet and the "Domain meta
  endpoints" bullet as spec §Docs says. Add a line on `search/` `more`/`placeholder`. Commit
  `CLAUDE.md: pesticide place filters and meta`.
- [ ] **Step 2:** Full suite (`-n 4 --dist loadscope`). Expected: the baseline plus the new
  tests, with no failures. `git diff --stat origin/develop...HEAD` lists only the allowed files
  and docs.
- [ ] **Step 3:** Run the whole-branch review (`executing-plans`' final review), then push and
  open a PR into `develop`. The body covers each item, the explorer-safety argument, the SDK
  signature list from the spec, and no attribution. Send the coordinator the PR number and the
  final signatures.

## After this plan (not in it)

The sdk-js spec, then a PR into `release/5.0.0` in the sdk-js repo, using the signatures in the
spec's "SDK follow-up". Publishing 5.0.0-beta.6 needs the user's own yes.
