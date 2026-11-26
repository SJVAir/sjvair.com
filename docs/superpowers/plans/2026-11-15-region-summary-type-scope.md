# Whole-type scope on the bulk region summaries: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `?type=<region type>` scopes `regions/<entry_type>/summaries/<res>/` and
`regions/<entry_type>/summaries/daily/open/` to every current region of that type, with
no `region` list.

**Architecture:** `BulkRegionScopeForm` (shared by both views) gains a `type` field and a
`clean()` that requires exactly one of `type`/`region` and puts the scope in
`cleaned_data['regions']`: the explicit list, or the queryset
`Region.objects.current_vintage().filter(type=...)`. Both views filter on that value, so a
type scope is one SQL statement with a region sub-select.

**Tech Stack:** Django forms, django-resticus, django-filter (OpenAPI no-op filters), PostGIS.

**Spec:** `docs/superpowers/specs/2026-11-15-region-summary-type-scope-design.md`

## Global Constraints

- `type` is one value; exactly one of `type` or `region`; both or neither is a 400.
- `type=land_use` is a 400; any other non-`Region.Type` value is a 400 (`invalid_choice`); `mtrs` is allowed.
- Type scope = `Region.objects.current_vintage().filter(type=...)` (not retired; tracts on `TRACT_VINTAGE` only).
- `region=` lists unchanged: resolved through `Region.all_objects`, retired included; existing error codes (`required`, `unknown`) unchanged.
- Response shape, pagination, cache headers, ETags unchanged. No migration. Monitor bulk endpoints untouched.
- Tests: `django.test.TestCase`, pytest-style asserts, fixtures `regions.yaml`.
- No AI attribution in commits or the PR.

## Review Focus

1. A blank `type=` with a valid `region` list: must behave as a plain region request (blank = absent), not a 400 for "both". Test in Task 1.
2. A blank `type=` and no `region`: must be the "neither" 400 with `region` → `required`, as today. Test in Task 1.
3. `type` plus the date-range errors: the date form's `clean()` must still run (MRO), so a bad span with `type` is still a 400. Test in Task 1.
4. Open days with `type`: only regions with an hourly row since the first open day, as with a list. Test in Task 2.
5. More than 1,000 regions in scope: no `TooManyFieldsSent`, all rows returned across pages. Test in Task 3.

---

### Task 1: `type` on the form and the summary list

**Files:**
- Modify: `camp/api/v2/summaries/forms.py` (`BulkRegionScopeForm`)
- Modify: `camp/api/v2/summaries/endpoints.py` (`BulkRegionSummaryList.get_queryset`, docstring)
- Modify: `camp/api/v2/summaries/filters.py` (`BulkRegionSummaryFilter`)
- Test: `camp/api/v2/summaries/tests.py` (`BulkRegionSummaryListTests`)

**Interfaces:**
- Produces: `BulkRegionScopeForm.cleaned_data['regions']`: a `list[Region]` (from `region`) or a
  `Region` queryset (from `type`), usable in `region__in=` / `pk__in=`.
- Produces: `BulkRegionScopeForm.TYPE_CHOICES`: `Region.Type.choices` minus `land_use`.

- [ ] **Step 1: Write the failing tests** in `BulkRegionSummaryListTests`

Fixture regions: 8 counties (Fresno, Kern, ...), one city, one school district, one zipcode.

```python
def test_type_scope_returns_every_current_region_of_the_type(self):
    data = get_response_data(self._get({**self.january, 'type': 'county'}))
    assert {r['id'] for r in data['data']} == {self.fresno.sqid, self.kern.sqid}

def test_type_scope_leaves_out_other_types(self):
    city = Region.objects.get(type='city')
    make_region_summary(city, self.day, resolution='day', entry_type='pm25')
    data = get_response_data(self._get({**self.january, 'type': 'county'}))
    assert city.sqid not in {r['id'] for r in data['data']}

def test_type_scope_leaves_out_retired_regions(self):
    Region.all_objects.filter(pk=self.kern.pk).update(retired_at=date(2026, 1, 15))
    data = get_response_data(self._get({**self.january, 'type': 'county'}))
    assert {r['id'] for r in data['data']} == {self.fresno.sqid}
    # An explicit list still answers for the retired region.
    data = get_response_data(self._get({**self.january, 'region': self.kern.sqid}))
    assert {r['id'] for r in data['data']} == {self.kern.sqid}

def test_type_scope_leaves_out_old_vintage_tracts(self):
    # Two tracts, boundaries on TRACT_VINTAGE and '2010'; each with a daily row.
    # type=tract returns only the TRACT_VINTAGE one.

def test_type_and_region_together_is_400(self):
    response = self._get({**self.january, 'type': 'county', 'region': self.fresno.sqid})
    assert response.status_code == 400
    assert get_response_data(response)['errors']['__all__'][0]['code'] == 'exclusive'

def test_neither_type_nor_region_is_400(self):
    response = self._get({**self.january, 'type': ''})
    assert response.status_code == 400
    assert get_response_data(response)['errors']['region'][0]['code'] == 'required'

def test_blank_type_with_region_list_is_a_region_request(self):
    data = get_response_data(self._get({**self.january, 'type': '', 'region': self.fresno.sqid}))
    assert {r['id'] for r in data['data']} == {self.fresno.sqid}

def test_land_use_type_is_400(self):
    response = self._get({**self.january, 'type': 'land_use'})
    assert get_response_data(response)['errors']['type'][0]['code'] == 'invalid_choice'

def test_unknown_type_is_400(self):
    response = self._get({**self.january, 'type': 'galaxy'})
    assert get_response_data(response)['errors']['type'][0]['code'] == 'invalid_choice'

def test_type_scope_still_checks_the_date_span(self):
    response = self._get({'type': 'county', 'start': '2020-01-01', 'end': '2026-01-01'})
    assert response.status_code == 400

def test_type_scope_with_no_rows_is_empty_200(self):
    response = self._get({**self.january, 'type': 'cdp'})
    assert response.status_code == 200
    assert get_response_data(response)['data'] == []

def test_type_scope_hourly(self):
    make_region_summary(self.fresno, self.day, resolution='hour', entry_type='pm25')
    data = get_response_data(self._get({**self.january, 'type': 'county'}, resolution='hour'))
    assert {r['id'] for r in data['data']} == {self.fresno.sqid}
```

The tract test builds its regions with `Region.objects.create(type='tract', ...)` and
`Boundary.objects.create(region=..., version=..., geometry=...)`, then sets
`region.boundary` (pattern: `camp/apps/regions/tests/test_retirement.py:83`).
The existing `test_requires_region_param` and `test_blank_region_is_not_enough` must keep passing.

- [ ] **Step 2: Run them to verify they fail**

Run (worktree, per-session DB, see "Running tests" below):
`pytest camp/api/v2/summaries/tests.py::BulkRegionSummaryListTests -v`
Expected: the new tests FAIL (`type` is ignored, so `region` → `required` 400s).

- [ ] **Step 3: Implement**

In `forms.py`: `RegionListField(required=False)`; add
`type = forms.ChoiceField(choices=TYPE_CHOICES, required=False)`; `clean()` calls
`super().clean()` first (keeps the date form's checks), then:
- both `region` (non-empty list) and `type` → `add_error(None, ValidationError('Pass either region or type, not both.', code='exclusive'))`
- neither → `add_error('region', ValidationError(RegionListField.default_error_messages['required'] reworded to 'At least one region, or a type, is required.', code='required'))`
- else `cleaned_data['regions']` = the list, or `Region.objects.current_vintage().filter(type=type)`.

Skip the checks when `region` or `type` already has a field error (unknown id, invalid choice).

In `endpoints.py`: `BulkRegionSummaryList.get_queryset` filters
`region__in=self.form.cleaned_data['regions']`; update the docstring (one of `region` or `type`).

In `filters.py`: add to `BulkRegionSummaryFilter`
`type = django_filters.CharFilter(method='noop', help_text='Region type; every current region of it. Exclusive with region.')`
and change `region`'s help text to "Region id; repeatable. Exclusive with type."

- [ ] **Step 4: Run the class to verify it passes**

Run: `pytest camp/api/v2/summaries/tests.py::BulkRegionSummaryListTests -v`
Expected: all PASS.

- [ ] **Step 5: Commit**: `git commit -m "Bulk region summaries: whole-type scope (?type=)"`

### Task 2: `type` on the bulk open days

**Files:**
- Modify: `camp/api/v2/summaries/endpoints.py` (`BulkRegionOpenDays`)
- Modify: `camp/api/v2/summaries/filters.py` (new `BulkRegionOpenDaysFilter`)
- Test: `camp/api/v2/summaries/tests.py` (`BulkOpenDaysEndpointTests`)

**Interfaces:**
- Consumes: `BulkRegionScopeForm.cleaned_data['regions']` (Task 1).

- [ ] **Step 1: Write the failing tests** in `BulkOpenDaysEndpointTests` (use its `_regions`, `_hours`, `_by_id` helpers)

```python
def test_region_bulk_type_scope(self):
    self._hours(make_region_summary, self.fresno)
    by_id = self._by_id(self._regions([('type', 'county')]))
    # Kern (a county) has no hourly rows in the open window, so it isn't listed.
    assert set(by_id) == {self.fresno.sqid}
    assert len(by_id[self.fresno.sqid]['summaries']) == 2

def test_region_bulk_type_and_region_400(self):
    assert self._regions([('type', 'county'), ('region', self.fresno.sqid)]).status_code == 400

def test_region_bulk_land_use_400(self):
    assert self._regions([('type', 'land_use')]).status_code == 400
```

- [ ] **Step 2: Run to verify they fail**: `pytest camp/api/v2/summaries/tests.py::BulkOpenDaysEndpointTests -v`

- [ ] **Step 3: Implement**

`BulkRegionOpenDays.get_queryset`: `Region.all_objects.filter(Exists(recent), pk__in=self.form.cleaned_data['regions'])`
(a list of `Region` instances is fine for `pk__in`; drop the `ids` list comprehension). Update
its docstring. Add `BulkRegionOpenDaysFilter(FilterSet)` with no-op `region` and `type`
(same help texts as Task 1; `Meta.model = Region`, `fields = []`) and set
`filter_class = BulkRegionOpenDaysFilter` on the view.

- [ ] **Step 4: Run to verify they pass**, plus `BulkRegionSummaryListTests` again.

- [ ] **Step 5: Commit**: `git commit -m "Bulk region open days: whole-type scope"`

### Task 3: Scale check, docs, full suite, PR

**Files:**
- Test: `camp/api/v2/summaries/tests.py` (new `BulkRegionTypeScopeScaleTests`)
- Modify: `CLAUDE.md` (Metadata Endpoints, "Open days" bullet and a new "Bulk region scope" line)

- [ ] **Step 1: Write the scale test**

```python
class BulkRegionTypeScopeScaleTests(TestCase):
    def test_more_than_1000_regions_by_type(self):
        # Region.objects.bulk_create 1,100 zipcode regions (names/external_ids unique),
        # one daily pm25 row each on 2026-01-01 (RegionSummary bulk_create).
        # Through the test client:
        #   GET /api/2.0/regions/pm25/summaries/daily/?type=zipcode&start=2026-01-01&end=2026-01-01
        # Page through with page=N until has_next_page is false.
        # assert every page is 200 and the union of ids is all 1,100 sqids.
```

`page_size` is 168, so 7 pages. Run it; it should pass as soon as Tasks 1–2 are in (this pins the behaviour, no new code).

- [ ] **Step 2: Check the query plan on the shared stack (read-only)**

`podman exec sjvaircom_web_1 python manage.py shell -c` with the scoped queryset built by hand
(`RegionSummary.objects.filter(entry_type='pm25', resolution='day', timestamp__gte=..., timestamp__lt=..., region__in=Region.objects.current_vintage().filter(type='tract')).order_by('region_id','timestamp')`)
and `.explain(analyze=True)`, for one recent day of tracts, and the open-days region query for `type=tract`.
Expected: the summary unique index (`region, entry_type, resolution, timestamp`) and a
semi-join / hash join on the region sub-select; no seq scan of the summary table. Record timings for the PR.
The shared stack runs `develop`, so build the querysets in the shell instead of calling the new endpoint.

- [ ] **Step 3: CLAUDE.md**: add under Metadata Endpoints a "Bulk region scope" bullet stating the
Global Constraints' first four lines in one paragraph; change the open-days bullet's "(`region` required)" to "(`region` or `type` required)".

- [ ] **Step 4: Full suite**: `pytest -n 4 --dist loadscope`; tee to a log in the scratchpad. Expected: all pass.

- [ ] **Step 5: Commit, push, PR into `develop`** (no attribution). PR body: the new parameter,
the 400s, unchanged behaviour, EXPLAIN results, the old-vintage tract report. Don't merge without the user's yes.

## Running tests

From the worktree, with a per-session DB (never print `DATABASE_URL`):

```bash
DB_URL=$(grep '^DATABASE_URL=' .env.test | cut -d= -f2- | sed 's#/[^/]*$#/test_region_type_scope#')
podman run --rm --network sjvaircom_sjvair-net --env-file .env.test -e DATABASE_URL="$DB_URL" \
  -e BAM_MIRROR_ENABLED=0 -e TWILIO_AUTH_TOKEN=test-token -v "$PWD":/app:z -w /app \
  sjvair-com-test:latest pytest <target>
```
