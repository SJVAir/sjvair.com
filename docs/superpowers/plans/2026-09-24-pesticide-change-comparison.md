# Year-over-year Change Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Pesticides Explorer can compare two years — both maps shade the change with a diverging ramp, and place, landing and entity pages rank what rose and fell most.

**Architecture:** `compare` becomes an explorer-wide scope parameter beside `year`/`county`/`concern`. The interactive map fetches both years' totals per feature and diffs in the browser; the eight-county figure classifies in Python; "biggest movers" is a `stats.py` queryset rendered server-side. Diverging classification is added on both sides of the existing JS/Python split rather than unifying them.

**Tech Stack:** Django 5.2 + PostGIS, `PesticideUseRollup`, django-resticus (`CachedEndpointMixin`), MapTiler SDK via `assets/js/maps/*` + `assets/js/pesticides/section-map.js` (plain ES5-style, no build step for our own JS), `camp/utils/mapfigure.py` for the county figure, Bulma, htmx, selenium smoke script (dev-only).

**Spec:** `docs/superpowers/specs/2026-09-24-pesticide-change-comparison-design.md` — read it before Task 1; the sections referenced below (§2.1, §3.2, §3.4 …) are its.

## Global Constraints

Worktree only, on `feature/pesticides-explorer` (PR #275) — not a new branch. Stage files by name (never `git add -A`), no AI attribution or co-author trailers, do not push (the controller pushes). Python tests are Django `TestCase` with plain `assert` (`pytest.raises` for exceptions) and Django fixtures. Verbose names use `_()` as the first positional arg; don't align `=` signs. Bulma for markup. Our own JS is not cache-busted (hard refresh); run `invoke styles` after any Sass change. Dev server on :8002, never 8000/8001. Run tests with `docker compose run --rm test pytest <path> -v`. The change is always **scope year minus compared year** (§2.1) and no surface shows a bare signed number without naming the pair in order.

---

## File Structure

| File | Responsibility |
|---|---|
| `camp/apps/pesticides/stats.py` | `resolve_compare_param`, `previous_year`, `compare` in `scope_param`/`scope_query`, `top_movers` |
| `camp/apps/pesticides/maps.py` | `sample_ramp`, `DIVERGING_RAMPS`, `DivergingClasses`, `diverging_classes`, compare mode in `rank_counties`/`county_map` |
| `camp/apps/pesticides/views.py` | `scope_compare`, `compare` through `year_context` and the base `dispatch`, compared-year rows at the four `county_map` call sites, movers context |
| `camp/api/v2/pesticides/sections.py` | `?compare=` on the sections and townships endpoints |
| `assets/js/pesticides/section-map.js` | `DIVERGING_RAMPS`, `divergingClasses`, `divergingColorFor`, compare in the classing step, legend, popups, Options control |
| `camp/templates/pesticides/includes/movers.html` | **new** — the rising/falling lists |
| `camp/templates/pesticides/includes/{map-options,scope-picker,section-map}.html` | the compare controls and `data-compare` |
| `scripts/pesticides_map_smoke.py` | browser checks for compare mode |

---

### Task 1: The `compare` scope parameter

**Files:**
- Modify: `camp/apps/pesticides/stats.py` (add after `resolve_year_param`, ~line 102; `scope_param` at :128; `scope_query` at :147)
- Modify: `camp/apps/pesticides/views.py` (`year_context` at :47, `scope_concern` at :78, base `dispatch` at :272)
- Test: `camp/apps/pesticides/tests/test_stats.py`, `camp/apps/pesticides/tests/test_views.py`

**Interfaces:**
- Produces: `stats.resolve_compare_param(requested, year, all_years=False) -> int | None`; `stats.previous_year(year) -> int | None`; `compare=None` keyword on `stats.scope_param`/`stats.scope_query`; `views.scope_compare(request, year, all_years) -> int | None`; `self.compare` on the base explorer view; `compare` and `compare_label` in `year_context()`.
- Consumes: `stats.available_years()` (ascending list of loaded years).

- [ ] **Step 1: Write the failing tests**

Both test classes use `RollupTestMixin` (`camp/apps/pesticides/tests/rollup_mixin.py`)
so the fixture has rollup rows. `available_years()` and `latest_year()` are
cached under `YEARS_KEY`/`LATEST_YEAR_KEY`, so any test that changes which
years exist must call `stats.refresh_landing_stats()` (or delete those keys)
first — otherwise a stale list from another test class decides what counts as
a loaded year.

In `test_stats.py`:

```python
def test_resolve_compare_param(self):
    # available_years() is [2022, 2023] for the fixture.
    assert stats.resolve_compare_param('2022', 2023) == 2022
    # Not loaded, the scope year itself, junk, and missing all mean "no comparison".
    assert stats.resolve_compare_param('1999', 2023) is None
    assert stats.resolve_compare_param('2023', 2023) is None
    assert stats.resolve_compare_param('banana', 2023) is None
    assert stats.resolve_compare_param(None, 2023) is None
    # A range has no second term.
    assert stats.resolve_compare_param('2022', None, all_years=True) is None

def test_previous_year(self):
    assert stats.previous_year(2023) == 2022
    assert stats.previous_year(2022) is None       # earliest loaded
    assert stats.previous_year(1999) is None       # not loaded

def test_scope_param_carries_compare(self):
    assert stats.scope_param(2023, compare=2022) == 'compare=2022'
    assert stats.scope_param(2022, county='kern', compare=2021, concern=True) == (
        'year=2022&county=kern&compare=2021&concern=1')
    assert stats.scope_param(2023) == ''
    assert stats.scope_query(2023, compare=2022) == '?compare=2022'
```

- [ ] **Step 2: Run them and watch them fail**

`docker compose run --rm test pytest camp/apps/pesticides/tests/test_stats.py -v`
Expected: `AttributeError: module 'camp.apps.pesticides.stats' has no attribute 'resolve_compare_param'`.

- [ ] **Step 3: Implement the resolvers**

```python
def previous_year(year):
    """The loaded year before `year`, or None when it is the earliest (or not loaded)."""
    years = available_years()
    if not years or year not in years:
        return None
    index = years.index(year)
    return years[index - 1] if index else None


def resolve_compare_param(requested, year, all_years=False):
    """
    The `?compare=` scope parameter as an int, or None when there is nothing
    to compare against: a year with no rollup, the scope year itself, or any
    value at all while the scope is All years -- a range has no second term.
    Nothing requires it to be the earlier of the two; see the spec's §2.1.
    """
    years = available_years()
    if all_years or year is None or not years:
        return None
    try:
        compare = int(str(requested).strip())
    except (TypeError, ValueError):
        return None
    if compare == year or compare not in years:
        return None
    return compare
```

- [ ] **Step 4: Thread it through `scope_param`/`scope_query`**

Add `compare=None` as the last keyword of both, and in `scope_param` insert between the county and concern parts (matching the docstring's stated order):

```python
    if compare:
        parts.append(f'compare={compare}')
```

Update both docstrings to name `compare`.

- [ ] **Step 5: Run the tests to verify they pass**

`docker compose run --rm test pytest camp/apps/pesticides/tests/test_stats.py -v` — all pass.

- [ ] **Step 6: Wire it into the views**

Beside `scope_concern` in `views.py`:

```python
def scope_compare(request, year, all_years=False):
    """The year the explorer is comparing against (`?compare=<year>`), or None."""
    return stats.resolve_compare_param(request.GET.get('compare'), year, all_years)
```

In `year_context()`, take `compare=None`, and add to the returned dict:

```python
        'compare': compare,
        # "2018 to 2023" -- headings and legends always name the pair in
        # order, so a signed number is never shown bare (spec §2.1).
        'compare_label': f'{compare} to {year}' if compare else '',
        'scope_qs': stats.scope_query(year, all_years, county, concern, compare),
```

In the base view's `dispatch` (:272), after the county/concern lines:

```python
        self.compare = scope_compare(request, self.year, self.all_years)
```

and pass `compare=self.compare` at every `year_context(...)` call site (grep `year_context(` — they all sit in `get_context_data`).

- [ ] **Step 7: Test the context and scope round-trip**

In `test_views.py`:

```python
def test_compare_rides_in_the_scope(self):
    response = self.client.get('/tools/pesticides/', {'year': 2023, 'compare': 2022})
    assert response.context['compare'] == 2022
    assert response.context['compare_label'] == '2022 to 2023'
    assert 'compare=2022' in response.context['scope_qs']

def test_compare_is_dropped_for_all_years(self):
    response = self.client.get('/tools/pesticides/', {'year': 'all', 'compare': 2022})
    assert response.context['compare'] is None
    assert 'compare=' not in response.context['scope_qs']
```

- [ ] **Step 8: Run the full pesticides suite**

`docker compose run --rm test pytest camp/apps/pesticides -v` — green.

- [ ] **Step 9: Commit**

```bash
git add camp/apps/pesticides/stats.py camp/apps/pesticides/views.py \
        camp/apps/pesticides/tests/test_stats.py camp/apps/pesticides/tests/test_views.py
git commit -m "feat(pesticides): carry a compare year through the explorer scope"
```

---

### Task 2: Diverging classification in Python

**Files:**
- Modify: `camp/apps/pesticides/maps.py` (module docstring ~:7, `RAMPS` at :37, `quantile_classes` at :139 and its colour line at :161)
- Test: `camp/apps/pesticides/tests/test_maps.py`

**Interfaces:**
- Produces: `maps.sample_ramp(ramp, count) -> list[str]`; `maps.DIVERGING_RAMPS`; `maps.diverging_ramp_for(name)`; `maps.DivergingClasses` (same interface as `QuantileClasses`: `breaks`, `colors`, `members`, `index_for`, `color_for`, `legend`); `maps.diverging_classes(deltas_by_key, classes=CLASSES, ramp=None)`.
- Consumes: `maps.NO_DATA`, `maps.CLASSES`.

- [ ] **Step 1: Read the spec's §3.1–§3.4** — the mirrored-quantile method, the three fill states, the ramps, and the sampling reconciliation.

- [ ] **Step 2: Write the failing tests**

```python
def test_sample_ramp_interpolates(self):
    ramp = ['#000000', '#ffffff']
    assert maps.sample_ramp(ramp, 2) == ['#000000', '#ffffff']
    assert maps.sample_ramp(ramp, 3) == ['#000000', '#808080', '#ffffff']
    # More classes than stops must not repeat a colour.
    assert len(set(maps.sample_ramp(ramp, 5))) == 5
    assert maps.sample_ramp(ramp, 1) == ['#ffffff']

def test_diverging_classes_mirror_around_zero(self):
    classes = maps.diverging_classes({'a': -100.0, 'b': -10.0, 'c': 10.0, 'd': 100.0}, classes=5)
    # Breaks ascend through the neutral class; the magnitudes mirror.
    assert classes.breaks == sorted(classes.breaks)
    negative = [b for b in classes.breaks if b < 0]
    positive = [b for b in classes.breaks if b > 0]
    assert sorted(abs(b) for b in negative) == sorted(positive)

def test_diverging_classes_three_states(self):
    classes = maps.diverging_classes({'a': -50.0, 'b': 0.0, 'c': 50.0, 'd': None}, classes=5)
    # No data is grey; no change is the neutral centre; both differ from each other.
    assert classes.color_for(None) == maps.NO_DATA
    assert classes.color_for(0.0) != maps.NO_DATA
    assert classes.color_for(0.0) != classes.color_for(50.0)
    assert classes.color_for(-50.0) != classes.color_for(50.0)

def test_diverging_classes_degenerate_inputs(self):
    assert maps.diverging_classes({}).breaks == []
    # Every delta zero: nothing to grade, but zero is still "no change", not "no data".
    flat = maps.diverging_classes({'a': 0.0, 'b': 0.0})
    assert flat.color_for(0.0) != maps.NO_DATA
    assert maps.diverging_classes({'a': None, 'b': None}).color_for(None) == maps.NO_DATA
```

- [ ] **Step 3: Run them and watch them fail**

`docker compose run --rm test pytest camp/apps/pesticides/tests/test_maps.py -v`
Expected: `AttributeError: ... has no attribute 'sample_ramp'`.

- [ ] **Step 4: Add `sample_ramp` and use it in `quantile_classes`**

```python
def sample_ramp(ramp, count):
    """
    `count` colors spread across `ramp`, interpolating between its stops --
    the same algorithm as sampleRamp() in section-map.js. Selecting the
    nearest stop instead (what this replaces) silently repeats colors once
    `count` passes the number of stops.
    """
    if count <= 1:
        return [ramp[-1]]
    stops = [(int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)) for h in ramp]
    colors = []
    for i in range(count):
        t = i * (len(stops) - 1) / (count - 1)
        lo = math.floor(t)
        hi = min(len(stops) - 1, lo + 1)
        f = t - lo
        rgb = [round(stops[lo][c] + (stops[hi][c] - stops[lo][c]) * f) for c in range(3)]
        colors.append('#%02x%02x%02x' % tuple(rgb))
    return colors
```

Replace `quantile_classes`'s colour line (:161) with `colors = sample_ramp(ramp, count)`, keeping the `count == 1` branch above it (`sample_ramp` handles it identically, so that branch can go).

- [ ] **Step 5: Add the diverging ramps and classifier**

```python
# Diverging ramps for the year-over-year change maps, stored already
# reversed: index 0 is the largest decrease, index -1 the largest increase.
# Unlike the sequential ramps above these cannot be luminance-monotonic --
# both ends are dark and the middle is light -- so hue alone carries the
# direction. All three are colorblind-safe; a greyscale print loses the sign.
DIVERGING_RAMPS = {
    'rdbu': ['#2166ac', '#67a9cf', '#d1e5f0', '#f7f7f7', '#fddbc7', '#ef8a62', '#b2182b'],
    'puor': ['#542788', '#998ec3', '#d8daeb', '#f7f7f7', '#fee0b6', '#f1a340', '#b35806'],
    'brbg': ['#01665e', '#5ab4ac', '#c7eae5', '#f5f5f5', '#f6e8c3', '#d8b365', '#8c510a'],
}
DIVERGING_RAMP = DIVERGING_RAMPS['rdbu']


def diverging_ramp_for(name):
    """A diverging ramp by `?ramp=` name, or the default. A sequential name
    never resolves here, so a diff map cannot be drawn with a one-sided ramp."""
    return DIVERGING_RAMPS.get(name or '', DIVERGING_RAMP)
```

`DivergingClasses` subclasses `QuantileClasses` to inherit `index_for`/`legend`, overriding only `color_for` (a `None` delta is no data, `0.0` is the neutral class) and carrying `neutral_index`. `diverging_classes(deltas_by_key, classes=CLASSES, ramp=None)`:

1. Drop `None` values; take `magnitudes = sorted({abs(v) for v in deltas if v})`.
2. `per_side = max(1, classes // 2)`; if no magnitudes, return `DivergingClasses()` with a single neutral class.
3. Quantile the magnitudes into `per_side` upper bounds using the same
   `math.ceil(i * len(distinct) / count) - 1` cut as `quantile_classes`.
4. `breaks = [-m for m in reversed(bounds)] + [0.0] + bounds`.
5. Colours: `sample_ramp(ramp[:4], per_side + 1)[:-1]` for the decreases, the
   middle stop for neutral, and `sample_ramp(ramp[3:], per_side + 1)[1:]` for
   the increases — so both sides mirror and the neutral stop is shared.
6. Populate `members` by `index_for`, as `quantile_classes` does.

- [ ] **Step 6: Run the tests to verify they pass**

`docker compose run --rm test pytest camp/apps/pesticides/tests/test_maps.py -v` — all pass.

- [ ] **Step 7: Amend the module docstring**

The line requiring ramps to be "luminance-monotonic" gains a sentence exempting the diverging ramps and noting the greyscale consequence (spec §3.3).

- [ ] **Step 8: Commit**

```bash
git add camp/apps/pesticides/maps.py camp/apps/pesticides/tests/test_maps.py
git commit -m "feat(pesticides): diverging quantile classes for change maps"
```

---

### Task 3: Compare mode on the county figure

**Files:**
- Modify: `camp/apps/pesticides/maps.py` (`rank_counties` at :68, `county_map` at :170)
- Modify: `camp/apps/pesticides/views.py` (`county_map(` call sites at :536, :875, :1125, :1499)
- Test: `camp/apps/pesticides/tests/test_maps.py`, `camp/apps/pesticides/tests/test_views.py`

**Interfaces:**
- Consumes: `maps.diverging_classes`, `maps.diverging_ramp_for` (Task 2); `self.compare` (Task 1); `stats.by_county(rows, year, ...)`.
- Produces: `compare_by_county=None` keyword on `maps.rank_counties` and `maps.county_map`.

- [ ] **Step 1: Write the failing tests** — a `county_map` given `compare_by_county` returns a figure whose county fills come from `DIVERGING_RAMPS` (not `RAMPS`); a county present in neither year keeps `NO_DATA`; a county with equal totals in both years takes the neutral colour and *not* `NO_DATA`; without `compare_by_county` the figure is unchanged from today.

- [ ] **Step 2: Run them and watch them fail.**

- [ ] **Step 3: Implement.** Both functions take `compare_by_county=None`. When present, build `deltas_by_key = {county_id: (metric in by_county) - (metric in compare_by_county)}` over the union of county ids, with `None` where the id appears in neither, classify with `diverging_classes(..., ramp=diverging_ramp_for(ramp_name))`, and otherwise leave the rendering path untouched — the figure still emits flat `fillColor`/`fillOpacity`/`color`/`weight` per feature.

- [ ] **Step 4: Update the four view call sites** to pass `compare_by_county=stats.by_county(rows, self.compare, ...)` when `self.compare`, using the same `rows`/`lbs_field` each site already passes for the scope year.

- [ ] **Step 5: Run the tests to verify they pass.**

- [ ] **Step 6: Check it by eye** at `http://localhost:8002/tools/pesticides/?year=2023&compare=2022` — eight counties, red where use rose and blue where it fell.

- [ ] **Step 7: Commit**

```bash
git add camp/apps/pesticides/maps.py camp/apps/pesticides/views.py \
        camp/apps/pesticides/tests/test_maps.py camp/apps/pesticides/tests/test_views.py
git commit -m "feat(pesticides): shade the county figure by year-over-year change"
```

---

### Task 4: `stats.top_movers()`

**Files:**
- Modify: `camp/apps/pesticides/stats.py` (beside `top_related` at :400)
- Test: `camp/apps/pesticides/tests/test_stats.py`

**Interfaces:**
- Produces: `stats.top_movers(rows, year_from, year_to, field, lbs_field='lbs_chemical', limit=10) -> {'rising': [...], 'falling': [...]}` of `SimpleNamespace(obj, lbs_from, lbs_to, change, pct)`; `stats.MOVERS_PCT_MIN_LBS = 100`.
- Consumes: `stats.real_chemicals(rows)`, `stats.in_year` conventions, `rows.model._meta.get_field(field).related_model`.

- [ ] **Step 1: Write the failing tests**

```python
def test_top_movers_ranks_by_absolute_change(self):
    movers = stats.top_movers(PesticideUseRollup.objects.all(), 2022, 2023, 'chemical')
    rising = movers['rising']
    assert [m.change for m in rising] == sorted((m.change for m in rising), reverse=True)
    assert all(m.change > 0 for m in rising)
    assert all(m.change < 0 for m in movers['falling'])
    # change is always scope year minus compared year (spec 2.1).
    for mover in rising:
        assert mover.change == mover.lbs_to - mover.lbs_from

def test_top_movers_suppresses_meaningless_percentages(self):
    movers = stats.top_movers(PesticideUseRollup.objects.all(), 2022, 2023, 'chemical')
    for mover in movers['rising'] + movers['falling']:
        if mover.lbs_from < stats.MOVERS_PCT_MIN_LBS:
            assert mover.pct is None
        else:
            assert mover.pct == pytest.approx((mover.lbs_to - mover.lbs_from) / mover.lbs_from * 100)

def test_top_movers_resolves_instances_and_skips_placeholders(self):
    movers = stats.top_movers(PesticideUseRollup.objects.all(), 2022, 2023, 'chemical')
    for mover in movers['rising']:
        assert mover.obj.get_absolute_url()
    names = [m.obj.name for m in movers['rising'] + movers['falling']]
    assert not any(name.upper().startswith('UNKNOWN') for name in names)

def test_top_movers_on_the_county_axis(self):
    movers = stats.top_movers(PesticideUseRollup.objects.all(), 2022, 2023, 'county')
    assert all(m.obj.type == Region.Type.COUNTY for m in movers['rising'])
```

- [ ] **Step 2: Run them and watch them fail.**

- [ ] **Step 3: Implement**

```python
MOVERS_PCT_MIN_LBS = 100


def top_movers(rows, year_from, year_to, field, lbs_field='lbs_chemical', limit=10):
    """
    What rose and fell most on `field` between two years, ranked by absolute
    change (`lbs_to - lbs_from`, always the scope year minus the compared
    one). `pct` is filled in only where `lbs_from` is at least
    MOVERS_PCT_MIN_LBS, so a tiny baseline can't produce a meaningless
    four-digit percentage. Rows absent from both years never appear.

    Three queries, as top_related(): the group-by sliced each way, then
    in_bulk for the instances (sqid is not a DB column and templates need
    get_absolute_url()).
    """
    if field == 'chemical':
        rows = real_chemicals(rows)
    grouped = (
        rows.filter(year__in=[year_from, year_to], **{f'{field}__isnull': False})
        .values(field)
        .annotate(
            lbs_from=Sum(Case(When(year=year_from, then=F(lbs_field)),
                default=0.0, output_field=FloatField())),
            lbs_to=Sum(Case(When(year=year_to, then=F(lbs_field)),
                default=0.0, output_field=FloatField())),
        )
        .annotate(change=F('lbs_to') - F('lbs_from'))
    )
    # Filtered by sign, not just sliced: with fewer than `limit` movers a
    # single ordered queryset would hand the tail of the risers to the
    # fallers and vice versa.
    rising = list(grouped.filter(change__gt=0).order_by(F('change').desc(), field)[:limit])
    falling = list(grouped.filter(change__lt=0).order_by(F('change').asc(), field)[:limit])

    model = rows.model._meta.get_field(field).related_model
    objects = model.objects.in_bulk([row[field] for row in rising + falling])

    def build(found):
        movers = []
        for row in found:
            obj = objects.get(row[field])
            if obj is None:
                continue
            lbs_from = row['lbs_from'] or 0
            pct = ((row['lbs_to'] - lbs_from) / lbs_from * 100) if lbs_from >= MOVERS_PCT_MIN_LBS else None
            movers.append(SimpleNamespace(obj=obj, lbs_from=lbs_from,
                lbs_to=row['lbs_to'] or 0, change=row['change'], pct=pct))
        return movers

    return {'rising': build(rising), 'falling': build(falling)}
```

Add `Case`, `When`, `FloatField` to the `django.db.models` import at the top of `stats.py`.

- [ ] **Step 4: Run the tests to verify they pass.**

- [ ] **Step 5: Commit**

```bash
git add camp/apps/pesticides/stats.py camp/apps/pesticides/tests/test_stats.py
git commit -m "feat(pesticides): rank what rose and fell most between two years"
```

---

### Task 5: The movers card

**Files:**
- Create: `camp/templates/pesticides/includes/movers.html`
- Modify: `camp/apps/pesticides/views.py` (landing, place, and the three entity detail views)
- Test: `camp/apps/pesticides/tests/test_views.py`

**Interfaces:**
- Consumes: `stats.top_movers` (Task 4), `stats.previous_year` (Task 1), `self.compare`.
- Produces: a `movers` context key — `{'rising', 'falling', 'year_from', 'year_to'}` or `None`.

- [ ] **Step 1: Read `includes/leaderboard.html`** and match its markup, numbered-rank styling and number formatting.

- [ ] **Step 2: Write the failing tests**

```python
def test_movers_defaults_to_the_previous_year(self):
    response = self.client.get('/tools/pesticides/', {'year': 2023})
    assert response.context['movers']['year_from'] == 2022
    assert response.context['movers']['year_to'] == 2023

def test_movers_follows_an_explicit_compare_year(self):
    response = self.client.get('/tools/pesticides/', {'year': 2023, 'compare': 2022})
    assert response.context['movers']['year_from'] == 2022

def test_movers_is_absent_without_a_comparable_year(self):
    # 2022 is the earliest loaded year in the fixture.
    response = self.client.get('/tools/pesticides/', {'year': 2022})
    assert response.context['movers'] is None
    assert 'Biggest movers' not in response.content.decode()

def test_movers_is_absent_for_all_years(self):
    response = self.client.get('/tools/pesticides/', {'year': 'all'})
    assert response.context['movers'] is None

def test_entity_pages_rank_counties(self):
    chemical = Chemical.objects.exclude(name__startswith='UNKNOWN').first()
    response = self.client.get(chemical.get_absolute_url(), {'year': 2023})
    assert all(m.obj.type == Region.Type.COUNTY for m in response.context['movers']['rising'])
```

- [ ] **Step 3: Run them and watch them fail.**

- [ ] **Step 4: Implement.** A small helper on the base view:

```python
    def movers_context(self, rows, field, lbs_field='lbs_chemical'):
        """
        The movers card's context, or None when there is nothing to compare
        against. Unlike the maps, movers always compares -- an uncompared
        card would say nothing -- so an absent `?compare=` falls back to the
        previous loaded year (spec 2).
        """
        if self.all_years or not self.year:
            return None
        year_from = self.compare or stats.previous_year(self.year)
        if not year_from:
            return None
        movers = stats.top_movers(rows, year_from, self.year, field, lbs_field)
        if not movers['rising'] and not movers['falling']:
            return None
        return {**movers, 'year_from': year_from, 'year_to': self.year}
```

Landing and place pages pass `field='chemical'`; the three entity detail views pass `field='county'`. Include the template where the spec says — after the existing leaderboards, before the map on place pages.

- [ ] **Step 5: Run the tests to verify they pass.**

- [ ] **Step 6: Check it by eye** on the landing page, a county page, a school-district page and a chemical page. The heading names the pair in order ("2022 to 2023"), per §2.1.

- [ ] **Step 7: Commit**

```bash
git add camp/templates/pesticides/includes/movers.html camp/apps/pesticides/views.py \
        camp/apps/pesticides/tests/test_views.py
git commit -m "feat(pesticides): biggest movers on landing, place and entity pages"
```

---

### Task 6: `?compare=` on the map endpoints

**Files:**
- Modify: `camp/api/v2/pesticides/sections.py` (`TOTALS`/`ZERO` at :27, `apply_filters` at :51, both endpoint classes)
- Test: `camp/apps/pesticides/tests/test_sections.py`

**Interfaces:**
- Produces: `?compare=<year>` on the sections and townships endpoints; each feature gains `lbs_chemical_prev`, `lbs_product_prev`, `acres_treated_prev`, `applications_prev`.
- Consumes: `stats.resolve_compare_param` (Task 1), the existing `bad_request()` and `CachedEndpointMixin`.

- [ ] **Step 1: Write the failing tests** — with `?compare=`, a feature carries both years' totals; a feature present in only one of the two years still comes back, with `0` for the missing side; without `compare` the payload is byte-identical to today's; an unloaded or non-numeric `compare` is a 400 through `bad_request()`; `compare` equal to `year` behaves as no comparison; `MAX_SECTIONS` still bounds the response.

- [ ] **Step 2: Run them and watch them fail.**

- [ ] **Step 3: Implement.** Resolve `compare` alongside the existing params; when set, add a conditional aggregation per `TOTALS` key restricted to the compared year, emitted under the `_prev` suffix, and widen the year filter to both years. Features with no rows in either year are still omitted. Returning both years rather than a delta is deliberate — the popup needs both numbers and metric switching must not refetch (spec §5).

- [ ] **Step 4: Run the tests to verify they pass.**

- [ ] **Step 5: Check the payload**

```bash
curl -s "http://localhost:8002/api/2.0/pesticides/townships/?year=2023&compare=2022" | head -c 400
```

- [ ] **Step 6: Commit**

```bash
git add camp/api/v2/pesticides/sections.py camp/apps/pesticides/tests/test_sections.py
git commit -m "feat(pesticides): return a compared year from the map endpoints"
```

---

### Task 7: The interactive map draws the change

**Files:**
- Modify: `assets/js/pesticides/section-map.js` (`RAMPS` at :54, `quantileClasses` at :139, `colorFor`/`renderLegend` at :176/:180, `METRIC_UNITS` at :91, `commonParams` , the classing steps at :1621/:1686/:2345/:2359/:2602, popup builders)
- Modify: `camp/apps/pesticides/views.py` (`section_map_config`), `camp/templates/pesticides/includes/section-map.html`
- Test: `camp/apps/pesticides/tests/test_views.py` (the new `data-compare` attribute)

**Interfaces:**
- Consumes: the `_prev` payload keys (Task 6); `self.compare` (Task 1).
- Produces: `DIVERGING_RAMPS`, `divergingClasses(values)`, `divergingColorFor(classes, delta)`, `this.compare` on `SectionMap`, `data-compare` on the container.

- [ ] **Step 1: Read the spec's §3 and §4**, and `quantileClasses`/`sampleRamp`/`renderLegend` as they stand.

- [ ] **Step 2: Add `data-compare`** to `section_map_config` and the template, with a Python test asserting it is rendered and empty when no comparison is in scope.

- [ ] **Step 3: Port the classification.** `DIVERGING_RAMPS` with the same three ramps and stop values as `maps.py` (spec §3.3); `divergingClasses(values)` mirroring `diverging_classes` step for step, including `perSide = Math.max(1, Math.floor(NUM_CLASSES / 2))`; `divergingColorFor(classes, delta)` returning `NO_DATA_COLOR` for `null`, the neutral colour for `0`, and the ramp otherwise. `?ramp=` resolves against `DIVERGING_RAMPS` while comparing.

- [ ] **Step 4: Use it in the classing steps.** Each of the five call sites computes, per feature, `value - value_prev` for the current metric when `this.compare` is set, passing `null` where both years are absent, then writes `fill`/`opacity` from `divergingColorFor`. The metric selector keeps working — compare is orthogonal to metric.

- [ ] **Step 5: Legend and popups.** `renderLegend` branches on `classes.diverging` to render the decrease classes, the "No change" row, the increase classes and the existing no-data row; the heading names the pair ("Change, 2022 to 2023, lbs"). Popups show both years and the delta, e.g. `2,400 → 5,100 lbs (+2,700)`.

- [ ] **Step 6: Verify by hand** at `http://localhost:8002/tools/pesticides/map/?year=2023&compare=2022` (hard refresh): townships shade red/blue, a popup shows both years, `?ramp=brbg` changes the scheme, `?bins=8` gives four classes a side.

- [ ] **Step 7: Run the Python tests and the existing smoke script**

```bash
docker compose run --rm test pytest camp/apps/pesticides -v
.venv/bin/python scripts/pesticides_map_smoke.py --base http://localhost:8002 /tools/pesticides/map/
```

- [ ] **Step 8: Commit**

```bash
git add assets/js/pesticides/section-map.js camp/apps/pesticides/views.py \
        camp/templates/pesticides/includes/section-map.html camp/apps/pesticides/tests/test_views.py
git commit -m "feat(pesticides): shade the interactive map by year-over-year change"
```

---

### Task 8: The compare controls, and smoke coverage

**Files:**
- Modify: `camp/templates/pesticides/includes/map-options.html`, `camp/templates/pesticides/includes/scope-picker.html`
- Modify: `assets/js/pesticides/section-map.js` (URL sync beside the existing `?metric=`/`?bins=` handling)
- Modify: `scripts/pesticides_map_smoke.py`
- Test: `camp/apps/pesticides/tests/test_views.py`

**Interfaces:**
- Consumes: everything above.
- Produces: a "Compare with" select in the map's Options and in the scope picker, both writing `?compare=`; a `compare mode` smoke check.

- [ ] **Step 1: Add the scope-picker control.** A year select offering `year_options` minus the scope year, plus a blank "(none)" option. It is disabled with a short note while All years is selected, and choosing a compare year clears All years — they are mutually exclusive (spec §2).

- [ ] **Step 2: Mirror it in the map's Options** menu, writing the same parameter.

- [ ] **Step 3: URL sync** — `?compare=` is read on load and pushed on change beside the existing map params, so the view is linkable.

- [ ] **Step 4: Python tests** — the control renders the right options on a page with a map and one without; selecting All years disables it.

- [ ] **Step 5: Add the smoke check** `check_compare_mode`, registered after `check_legend_options`: with `?compare=`, the legend row count matches `bins` per side plus the neutral and no-data rows; a no-change feature and a no-data feature have visibly different fills; a popup names both years; clearing the compare year restores the sequential ramp.

- [ ] **Step 6: Run everything**

```bash
docker compose run --rm test pytest camp/apps/pesticides -v
.venv/bin/python scripts/pesticides_map_smoke.py --base http://localhost:8002 \
    /tools/pesticides/map/ '/tools/pesticides/map/?year=2023&compare=2022'
```

- [ ] **Step 7: Run the whole suite** — `docker compose run --rm test pytest`. CI runs the full `camp` tree, not a scoped subset, so a `loaddata`/`transaction=True` fixture leak only shows up here.

- [ ] **Step 8: Commit**

```bash
git add camp/templates/pesticides/includes/map-options.html \
        camp/templates/pesticides/includes/scope-picker.html \
        assets/js/pesticides/section-map.js scripts/pesticides_map_smoke.py \
        camp/apps/pesticides/tests/test_views.py
git commit -m "feat(pesticides): compare-year controls in the scope bar and map options"
```

---

## Deploy notes

These fold into PR #275's existing deploy notes; this work does not get a PR
of its own. No migrations. Requires the rollup to hold at least two years (`rebuild_pesticide_rollup --all`); with one year loaded every compare control hides itself and the movers card is omitted. Static JS is not cache-busted, so a hard refresh is needed after deploy. No new environment variables.
