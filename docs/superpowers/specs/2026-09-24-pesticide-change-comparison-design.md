# Year-over-year change in the Pesticides Explorer

Approved direction (Derek, 2026-09-24): "a choropleth map that tracks changes
between years -- select two years and plot the diff (2-hue color scheme)",
plus a ranked "biggest movers" list on place, landing and entity pages.

Both maps get the diverging treatment: the interactive MTRS/township map
(`assets/js/pesticides/section-map.js`) and the static eight-county figure
(`camp/apps/pesticides/maps.py:county_map`, used from `views.py:536`, `:875`,
`:1125` and `:1499`).

## 1. Goal and scope

One new idea, three surfaces:

| Surface | What it gains |
|---|---|
| Interactive map | Sections and townships shaded by the change between two years |
| County figure | The same, over the eight counties |
| Place, landing and entity pages | "Biggest movers": what rose and fell most |

Movers ranks chemicals on place and landing pages, and counties on a
chemical/product/commodity page -- the same question with the axis flipped.

Everything already in the explorer's scope (year, county, chemicals of
concern, and on the map the entity filters) continues to apply. That is the
point of the feature: the valuable query is "how did chlorpyrifos change
between 2018 and 2023 in Kern", not just total volume.

## 2. `compare` is a scope parameter

Movers appears on pages with no interactive map, so the compared year cannot
live in the map's Options menu. It joins `year`, `county` and `concern` as an
explorer-wide scope parameter, threaded through the existing helpers:

```python
stats.scope_param(year, all_years=False, county=None, concern=False, compare=None)
stats.scope_query(year, all_years=False, county=None, concern=False, compare=None)
```

Both gain a `compare=<year>` part, emitted after `county` and before
`concern`. Every call site passes it through; the parameter is otherwise
inert.

A new resolver sits beside `resolve_year_param()`:

```python
stats.resolve_compare_param(requested, year, all_years=False)
```

returning an `int` or `None`, by these rules:

- Not a loaded year (`stats.years_loaded()`) -> `None`.
- Equal to the scope year -> `None`. Comparing a year to itself is not a mode.
- `all_years` is on -> `None`. A range has no second term; the two are
  mutually exclusive, and the scope picker clears `compare` when All years is
  chosen and clears All years when a compare year is chosen.

### 2.1 Which way the sign points

The change is always **the scope year minus the compared year** -- "how the
year I am looking at differs from the one I am comparing against". Nothing
requires the compared year to be the earlier of the two: picking a later one
is legitimate and simply inverts the sign.

Because that is easy to misread, no surface ever shows a bare signed number.
The map legend, the movers heading and the popups all name the pair in order,
"2018 to 2023", reading from the compared year to the scope year.

**Defaults differ between the map and movers, deliberately.** An absent
`compare` leaves the maps in their normal single-year sequential view --
change is an explicit mode a reader turns on, not what they land on. Movers
always compares, so with `compare` absent it falls back to the loaded year
before the scope year (`None` when the scope year is the earliest loaded, in
which case the card is not rendered). A movers card with no comparison would
be meaningless, while a map that silently defaulted to a diff would be
misleading.

## 3. Diverging classification

`quantile_classes` / `quantileClasses` exist twice today -- once in Python for
the county figure (`maps.py:139`) and once in JS for the interactive map
(`section-map.js:139`) -- with matching ramp tables. The diverging pair
follows that established split rather than introducing a shared layer.

### 3.1 Method

Quantile the **absolute** deltas and mirror the breaks around zero. This
keeps the codebase's existing "quantile, not equal steps of the maximum"
philosophy, gives equal magnitudes equal saturation on each side, and handles
outliers the way every other map here already does -- no percentile cap
needed.

Per-side class count is `max(1, NUM_CLASSES // 2)`, so the existing
`?bins=4|5|6|8|10` values split evenly and the default of 6 gives three
classes each way.

### 3.2 Three states, not one

| State | Fill |
|---|---|
| No rollup rows in either year | `NO_DATA` / `NO_DATA_COLOR` (`#f0f0f0`), as today |
| Rows in at least one year, delta of 0 | the ramp's neutral centre |
| Delta non-zero | the diverging ramp |

Distinguishing "no data" from "no change" matters: a single grey would claim
a section was unsprayed in both years when the truth is that nothing was
reported. Both classing functions therefore take deltas that may be `None`
(no data) as distinct from `0.0` (no change):

```python
maps.diverging_classes(deltas_by_key, classes=CLASSES, ramp=None) -> DivergingClasses
```

```js
divergingClasses(values)   // values may contain null for no-data
divergingColorFor(classes, delta)   // null -> NO_DATA_COLOR, 0 -> neutral
```

`DivergingClasses` mirrors the `QuantileClasses` dataclass interface
(`breaks`, `colors`, `members`, `index_for`, `color_for`, `legend`) so
`rank_counties()` and the figure builder need no structural change. Its
`breaks` ascend from the most negative class through the neutral class to the
most positive, so `index_for`'s "first break at or above the value" scan works
unchanged.

**No "new use" or "stopped" categories.** While the metric is absolute
change, a section going from nothing to 500 lbs simply *is* +500; those cases
only become undefined if percent change is added later (§8).

### 3.3 Ramps

Seven-stop, colourblind-safe, defined already reversed so index 0 is the
largest decrease and index 6 the largest increase -- blue/teal/purple for
down, red/brown/orange for up:

```
rdbu (default)  #2166ac #67a9cf #d1e5f0 #f7f7f7 #fddbc7 #ef8a62 #b2182b
puor            #542788 #998ec3 #d8daeb #f7f7f7 #fee0b6 #f1a340 #b35806
brbg            #01665e #5ab4ac #c7eae5 #f5f5f5 #f6e8c3 #d8b365 #8c510a
```

Selectable with the existing `?ramp=` experiment switch, in a separate
`DIVERGING_RAMPS` table so a sequential name cannot be used for a diff or the
reverse; an unknown or sequential name falls back to `rdbu`.

### 3.4 Sampling the ramp

The neutral class always takes the middle stop (index 3). Each side samples
`per_side` colours from its half -- indices 0..2 for the decreases, 4..6 for
the increases -- so the two sides are mirror images whatever the class count.

The two implementations sample differently today and this work has to
reconcile them. `sampleRamp()` in JS (`section-map.js`) interpolates between
stops, so it produces any count from any ramp. `quantile_classes()` in Python
(`maps.py:161`) *selects* the nearest stop:

```python
colors = [ramp[round(i * (len(ramp) - 1) / (count - 1))] for i in range(count)]
```

which cannot produce more distinct colours than the ramp has stops, and
silently emits duplicates past that. It is never hit today because
`CLASSES = len(RAMP) = 5` with five-stop ramps. With seven-stop diverging
ramps it still is not hit, but the latent bug is a foot-gun as soon as either
number moves, so Python gains a `sample_ramp(ramp, count)` that interpolates
exactly as the JS does, and both classification functions use it.

The two maps will still cut a different number of classes -- the interactive
map defaults to six (three per side) and honours `?bins=`, while the county
figure is fixed at `CLASSES` (two per side). They already differ this way for
sequential maps, so this is existing behaviour, not something the diff mode
introduces.

`maps.py`'s module docstring currently requires ramps to be
"luminance-monotonic". That cannot hold for a diverging scheme, where both
ends are dark and the middle is light, so the docstring gains a sentence
saying the diverging ramps are exempt and noting the consequence: printed in
greyscale a diff map loses the sign of the change. Hue is the only channel
carrying direction, which is why all three ramps are colourblind-safe.

## 4. The interactive map

- `data-compare` joins the container's attributes (via
  `views.section_map_config`) and `commonParams()` so grid, lens and
  all-sections requests all carry it.
- The classing step already writes `fill` and `opacity` onto feature
  properties before `setData`. In compare mode it computes
  `delta = value - value_prev` per feature for the current metric (§2.1), passes
  `null` where neither year has rows, and takes its colour from
  `divergingColorFor`.
- The metric selector keeps working: change-in-pounds and
  change-in-applications are both meaningful, which is why compare is a mode
  orthogonal to metric rather than a third metric.
- `METRIC_UNITS` gains no entries; the legend prefixes the existing unit with
  a sign and the legend heading names the pair ("Change, 2018 to 2023, lbs").
- The legend renders the negative classes, the neutral "no change" row, the
  positive classes, and the existing no-data row. `renderLegend` branches on
  a `diverging` flag on the classes object.
- Popups show both years and the delta -- "2,400 -> 5,100 lbs (+2,700)" --
  which is why the payload carries both values rather than a precomputed
  difference.
- Options gains a "Compare with" year select, mirroring the scope parameter.
  Choosing a year sets `?compare=`; choosing the blank option clears it.
  It is disabled, with a note, while the scope is All years.
- The lens and all-sections modes use the same classing, so a diff is visible
  at every level the map already draws.

## 5. API

`?compare=<year>` on `sections/` and `townships/`
(`camp/api/v2/pesticides/sections.py`). The endpoints aggregate `TOTALS`
(`lbs_chemical`, `lbs_product`, `acres_treated`, `applications`) per feature
through `apply_filters()`; compare adds a second aggregation restricted to
the compared year and returns both sets per feature, the compared year's keys
suffixed `_prev`. Features absent from both years are omitted exactly as they
are today, so `MAX_SECTIONS` (2,500) still bounds the response.

Returning both years rather than a delta is deliberate: the popup needs both
numbers anyway, so sending them costs four floats per feature and buys
metric-switching with no refetch.

An invalid or unloaded `compare` year is a 400 through the existing
`bad_request()` helper, and `CachedEndpointMixin` keys on it like any other
parameter.

## 6. The county figure

`maps.county_map()` and `maps.rank_counties()` gain an optional second
mapping of per-county totals for the compared year. When present they classify
with `diverging_classes` and the `?ramp=` name resolves against
`DIVERGING_RAMPS`. The four `views.py` call sites pass the compared year's
`by_county` rows, which they obtain from the same `stats.by_county()` helper
they already call for the scope year.

Nothing about the figure's rendering path changes -- it is still a
`MapFigure` with flat `fillColor`/`fillOpacity`/`color`/`weight` properties
per feature.

## 7. Biggest movers

A sibling of `top_related()` in `stats.py`:

```python
stats.top_movers(rows, year_from, year_to, field, lbs_field='lbs_chemical', limit=10)
```

`field` is `'chemical' | 'product' | 'commodity' | 'county'`. One group-by
over `year__in=[year_from, year_to]` with a conditional sum per year:

```python
.annotate(
    lbs_from=Sum(Case(When(year=year_from, then=F(lbs_field)), default=0.0, output_field=FloatField())),
    lbs_to=Sum(Case(When(year=year_to, then=F(lbs_field)), default=0.0, output_field=FloatField())),
)
```

sliced twice (change descending for risers, ascending for fallers) and
resolved with one `in_bulk()` over the union of ids, as `top_related()` does
and for the same reason -- `sqid` is not a database column and templates need
`get_absolute_url()`. A chemical ranking excludes the placeholder chemicals
via `real_chemicals()`.

Returns `{'rising': [...], 'falling': [...]}` of
`SimpleNamespace(obj, lbs_from, lbs_to, change, pct)`, where
`change = lbs_to - lbs_from` (§2.1).

**Ranked by absolute change**, matching the map. `pct` is computed only where
`lbs_from >= MOVERS_PCT_MIN_LBS` (100 lbs) and is `None` otherwise, so the
template can show a percentage where it means something and omit it where a
tiny baseline would produce a meaningless four-digit number. Rows where both
years are zero never appear, since the group-by only sees rollup rows.

A `includes/movers.html` include renders the two lists in the idiom of
`includes/leaderboard.html`, with the numbered-rank styling the existing
place-page leaderboards use. It is omitted entirely when there is no
comparable year, or when both lists are empty.

## 8. Out of scope

Deliberately not in this work:

- **Percent-change mode.** Small baselines wreck the ramp (0.1 -> 1.0 lbs is
  +900%). Adding it later means a minimum-baseline guard and the "new use" /
  "stopped" categories §3.2 does not need.
- Change columns on `includes/by-county-table.html` and
  `includes/by-year-table.html`.
- Movers in the records browser.
- Any equity cross-tab (CES4 x MTRS); that is its own project.
- Rates (per square mile, per treated acre). Independent of this work: an
  MTRS section is one square mile by definition, so a section-level total is
  already a rate, and the two features only meet at township and county level.

## 9. Testing

Python (`camp/apps/pesticides/tests/`, Django `TestCase`, plain `assert`):

- `scope_param`/`scope_query` round-trip `compare`, and omit it when absent.
- `resolve_compare_param` returns `None` for an unloaded year, the scope year
  itself, and All years.
- `diverging_classes`: symmetric breaks, the neutral class for a zero delta,
  `NO_DATA` for `None`, a single-value input, and an all-zero input.
- `top_movers`: rising and falling ordering, the `in_bulk` resolution, `pct`
  suppressed below the baseline, placeholder chemicals excluded, and the
  county axis.
- The API's `compare` aggregation, including the 400 for an unloaded year and
  that a feature present in only one of the two years still comes back.
- The four `county_map` call sites render a diverging figure when a compared
  year is in scope.

Browser (`scripts/pesticides_map_smoke.py`, dev-only): compare mode draws a
diverging legend whose row count matches the bins, a no-change feature and a
no-data feature take visibly different fills, a popup shows both years and the
delta, and clearing the compare year restores the sequential ramp.

## Global constraints

Worktree only (`.claude/worktrees/feature+pesticides-explorer`), stage by
name, no AI attribution or co-author trailers, do not push (the controller
pushes), Django `TestCase` + plain `assert` for Python tests, Bulma, static JS
not cache-busted (hard refresh), `invoke styles` after Sass, dev server on
:8002 (never 8000/8001). This work lands on `feature/pesticides-explorer`
inside PR #275, which stays a draft until the explorer is complete and ready
for internal CCAC and partner review.
