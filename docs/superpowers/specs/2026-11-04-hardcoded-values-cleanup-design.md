# Hardcoded values cleanup (Release 1, step 3, batch 2, spec 5)

## Intent

sjvair.com now has metadata that describes its data: the level sets in
`camp/apps/entries/levels.py`, the scales in `camp/utils/scales.py` and each domain's
`scales.py`, the domain meta endpoints, and the `meta/datasets/` catalog. Metadata is the
source of truth (data-dashboard ARCHITECTURE.md → "Metadata as source of truth"). This spec
removes the places in sjvair.com that still keep their own copy of what that metadata says,
so a level label, breakpoint, color or guidance sentence changes in one place.

A survey (2026-11-04) found that sjvair.com hardcodes less than expected. Nothing it
hardcodes still uses the pre-2024 PM2.5 breakpoints. The copies that do exist are:
- the two `/guidelines/` pages;
- the account pages' level tags;
- `camp/utils/aqi.py` and the forecast API;
- the catalog's own labels and lists;
- a few Python copies (the group-map command, the PM2.5 cleaning tiers, a legacy choices
  list).

The user also decided to remove `monitors/meta/`'s legacy `levels` dict in this spec.

## Decisions (the user's)

1. **Remove `monitors/meta/`'s legacy `levels` dict.** The key is removed from each
   `entries.<type>` entirely, not set to `null`. This replaces the 2026-11-03 deferral
   (data-dashboard DEFERRED.md → Mobile app → "Retire the old air-quality `levels` format in
   `monitors/meta/`").
   - **Why now:** the user releases the updated mobile app and sjvair.com `develop` on the
     same day. Map-sdk will be on the latest sdk-js, monitor-map rebuilt from map-sdk, and
     mobile on that monitor-map, all before `develop` ships. Mobile auto-updates, most
     likely overnight, the day a release is published.
   - **Known cost, accepted:** an installed app that hasn't updated yet shows no level on its
     alert and subscription screens.
   - **sdk-js is not in this spec.** Removing `levels` from sdk-js (schema, getter,
     `asIter.levels`, fixtures) went to the coordinator for sdk-js-8c.
2. **The `/guidelines/` pages read from the level sets.** Labels, colors, PM2.5 ranges and
   units, AQI ranges, and guidance all come from the same Python source `monitors/meta/` uses.
   - Where the page's per-level advice differs from the metadata's `guidance`, the metadata
     wins: the page's longer, audience-split text is replaced by the level's `guidance`
     sentence.
   - The AQI Good range starts at 0, as in the scale, not 1.
3. **The school activity rows become metadata, served from an endpoint.**
   - Rows: Recess, P.E., Athletic Practice & Training, and Scheduled Sporting Events.
   - **The text is carried over word for word.** "Let's not reword anything. It's fine as is."
4. **The forecast API takes `color` and `aqi_category` from the AQI scale:** the level's
   discrete color and label for `aqi_value`.
   - `color` is a blended gradient today.
   - `aqi_category` is text saved at import, and reads "Out of Range" above 500.
   - No client reads either field except sdk-js's schema (checked in monitor-map, map-sdk,
     mobile, data-dashboard and web-widget).
5. **Not added:** no `aqi_level` key on forecasts, and no `short_label` for region types.
   Nothing needs them yet; clients find a forecast's level from `aqi_value` and
   `forecasts/meta/`.

## Goals

### 1. `monitors/meta/`

- Drop `levels` from every `entries.<type>`. `scale` stays exactly as it is.
- Add `school_guidelines` to every `entries.<type>`. It is `null` except for `pm25`; it is
  additive.

  ```json
  "school_guidelines": {
    "label": "Outdoor Activity Guidelines for Schools",
    "resolution": "hour",
    "source": {"name": "SJVAir", "url": "https://<host>/guidelines/schools/"},
    "activities": [
      {
        "key": "recess",
        "label": "Recess",
        "duration": "15 minutes",
        "levels": {
          "good": ["No restrictions."],
          "moderate": ["Ensure that sensitive individuals are medically managing their condition."],
          "...": ["..."]
        }
      }
    ]
  }
  ```

  - **`activities`** is an ordered array: `recess`, `pe`, `athletics`, `events`, in the
    page's order. Activity keys are permanent.
  - **Labels and durations** come from the page:
    - `"Recess"` / `"15 minutes"`
    - `"P.E."` / `"1 hour"`
    - `"Athletic Practice & Training"` / `"2-4 hours"`
    - `"Scheduled Sporting Events"` / `null` (the page gives no duration)
  - **`levels`** is keyed by the PM2.5 scale's level keys, and every key in that scale is
    present (all six). Each value is the cell's paragraphs as plain strings, in order. There
    is no HTML or Markdown; `&amp;` becomes `&`.
  - **`resolution: "hour"`** uses the catalog's resolution vocabulary. It says the
    guidelines apply to hourly PM2.5 (the page's footnote: "Guidelines are based on hourly
    PM2.5 concentration").
  - **`source`** credits sjvair.com's own page; its `url` is absolute, built from the request.
    No upstream credit for now: the matrix looks adapted from the Valley Air District's ROAR
    guidance or CDE's school air quality guide, but neither is confirmed.
  - **English only.** Strings are wrapped in `_()` like the level labels, so translation later
    keeps the keys.
  - **Built from a static Python definition next to `levels.PM25`:** one source for the
    endpoint and the page. A test checks that its level keys equal `levels.PM25`'s keys.

### 2. Guidelines pages

The general page (`/guidelines/`) and the schools page (`/guidelines/schools/`) are built from
`levels.PM25`, `levels.AQI` and the school guidelines definition, passed in as template
context, rather than written into the HTML.
- **Routing:** both pages are rendered today by the catch-all `PageTemplate` with an empty
  context, so they need their own view (or a context hook).
- **Columns:** one per PM2.5 level, in scale order, headed by the level label on the level's
  color.
- **Range rows show the same text as today,** with AQI Good starting at 0:
  - PM2.5: `0.0 – 9.0`, `9.1 – 35.4`, `35.5 – 55.4`, `55.5 – 125.4`, `125.5 – 225.4`,
    `≥225.5`, with units from the entry model (`µg/m³`).
  - AQI: `0 – 50`, `51 – 100`, `101 – 150`, `151 – 200`, `201 – 300`, `≥301`.
  - Inclusive upper bounds are the next level's `min` minus one step at the value's display
    precision: 0.1 for PM2.5, 1 for AQI.
- **The general page's "Guidance" row** shows each level's `guidance`. Good's is empty on
  purpose (`""`), so its cell is blank; today's "No restrictions: It's a great day to be
  active outside." goes away (the user's call, 2026-11-04). No fallback text is added on the
  page or in the metadata.
- **The schools page** shows one row per activity, label and duration in the row header,
  each cell's sentences as paragraphs, then the PM2.5 and AQI range rows.
- **Unchanged:** page titles, tabs, the footnote ("AQI is based on 24-hour average PM2.5
  concentration. Guidelines are based on hourly PM2.5 concentration."), and the table
  layout.
- **Colors** come from the level, not from the positional `level-1`…`level-6` classes. The
  light background tints on body cells may stay as styling.

### 3. Account level tags

`account/alerts.html` and `account/subscriptions.html` color the `.tag.air` level tag from
the level's own `color`, not from the per-key Sass rules.
- **Text color:** keep today's contrast (dark text on Good and Moderate, white from
  Unhealthy for Sensitive Groups up), worked out from the level.
- **Bug fix:** this fixes the unstyled `very_hazardous` tag, which has no Sass rule.
- **Cleanup:** remove the per-level `.tag.air.<key>` background rules from `global.sass`. The
  tag's shape rules stay.

### 4. Forecasts

- **Remove `camp/utils/aqi.py`.** Its only caller is the forecast import.
- **The import** fills `Forecast.aqi_category` from `levels.AQI.get_level(aqi_value).label`.
  The column stays; the admin lists and filters on it.
- **`Forecast.color`** returns the discrete level color, `levels.AQI.get_level(aqi_value).color`.
- **The forecast API** (`ForecastSerializer`, used by `forecasts/` and `forecasts/place/`)
  serves `aqi_category` as the scale label computed from `aqi_value`, so stored rows that
  say "Out of Range" read "Hazardous".
- **No backfill of stored `aqi_category`** (my call). `aqi_label()` and the scale give the
  same label for every AQI up to 500, so only rows above 500 differ. The local database has
  none (138 rows, checked 2026-11-04); production wasn't checked, and won't be. The admin
  keeps listing and filtering on the stored value.
- **The admin forecast panel** (`camp/apps/forecasts/panels.py`) shows the burn-status
  scale's label for a known `burn_status`, and the feed text otherwise. Its color and
  category follow the two changes above.

### 5. Catalog (`meta/datasets/`): same output, fewer copies

- **Smoke density, fire FRP, AQI forecast, burn status and heat score** read their label and
  units from the scale functions (`get_smoke_scale`, `get_fire_scale`,
  `get_aqi_forecast_scale`, `get_burn_status_scale`, `get_heat_scale`), not their own
  strings.
- **The weather dataset's monitor types** come from `settings.MONITOR_OPT_IN_TYPES`, not a
  hardcoded `[CIMIS]`.
- **`FACILITY_POLLUTANTS`** comes from `camp/apps/emissions/pollutants.py`, and its unit
  from `Pollutant.unit_label`.
- **TEMPO units** come from one shared definition, merged with
  `camp/api/v2/tempo/endpoints.py`'s `PRODUCT_UNITS`. `cldo4`'s `'fraction'` exists only in
  the catalog; it moves into the shared definition.
- **A test** pins the catalog response before and after. It must not change.

### 6. Smaller copies

- **`generate_group_map.py`** uses `levels.PM25`'s breakpoints and colors. Its map colors
  change to the official ones.
- **The PM2.5 cleaning tiers in `lcs.py`** derive their upper bounds from `levels.PM25`. They
  must give exactly today's output: inclusive bounds 9.0 / 35.4 / 55.4 / 125.4 / 225.4, so
  each is the next `min` minus 0.1. Cleaned data must not change.
- **Delete `Subscription.LEVELS`** (legacy, used only by `camp/api/v1/alerts/tests.py`) and
  move those tests to `AQLevel.choices`.
- **`LevelSet.as_dict()`** has no other caller once `levels` is gone (the
  `camp/datasci/series.py` `as_dict` is unrelated). Delete it along with its tests, including
  spec 1's test that the two formats agree.
- **`monitors/meta/`'s `get_default_pollutant`** falls back to a hardcoded `'pm25'`. Leave it:
  it is the guard for a bad setting, not metadata.

### 7. Docs

- **sjvair.com CLAUDE.md** → "Metadata Endpoints": the `monitors/meta/` paragraph no longer
  says to keep the old `levels` dict, describes `school_guidelines`, and notes that the
  forecast `color` and `aqi_category` come from the AQI scale.
- **data-dashboard docs** (own worktree, docs rules in its TODO.md):
  - DEFERRED.md → Mobile app → "Retire the old air-quality `levels` format": mark it done by
    this spec.
  - TODO.md "Release 1, step 3" item: update its status.
  - ARCHITECTURE.md → "Metadata as source of truth": record the final `school_guidelines`
    shape, so step 4 spec 4's "Can we go outside?" card can find it.
  - Tell the coordinator.

## Non-goals

- **sdk-js:** removing `levels`, and the `school_guidelines` accessor next to `scale`. That
  is sdk-js-8c's work; this spec sends it the final shape.
- **The map:** map-sdk, monitor-map, and the `/` and `/monitor/<id>/` pages, which only embed
  it.
- **Mobile:** its three screens that read `levels` and its hardcoded scale. They go on the
  coordinator's same-day release checklist.
- **Emissions and pesticide labels and units:** a later pesticide metadata spec. (The
  catalog's `FACILITY_POLLUTANTS` and `tons/yr` lines move to read the emissions module only
  as a copy removal; nothing about emissions metadata changes.)
- **`camp/apps/summaries`:** another session works there. Its `DEFAULT_POLLUTANT` copy stays.
- **Anything in production:** deploys, data, logs. Production needs go in data-dashboard
  DEFERRED.md → "Production deploy of sjvair.com `develop` → `main`".

## What stays, and why

- **Short region-type labels in the pesticide, emissions and reports views** ("ZIP", "AB 617
  community", "CDP"). This is UI wording, and nothing needs it as metadata (the user, item 5).
- **The Sass `$air-*` variables and the Bulma `is-air-*` helpers,** for styling that isn't a
  level. Only the level tags and the guidelines tables stop depending on them.
- **The entry models' field `help_text`** ("PM2.5 (µg/m³)"). It is admin field help, not
  served to clients.
- **The guidelines footnote and page titles.** No metadata describes them.
- **Admin prose mentioning pollutants** (`admin/menu.html`) and the admin monitor page's
  "°F" / "%" column units. These are descriptive admin chrome.
- **`LevelSet.get_color()`'s blending.** It stays for any caller that wants a gradient; the
  forecast stops using it. `regions/admin.py` calls it at a level's own value, which returns
  the level's color.

## Constraints

- **Ids and level keys are permanent.** Activity keys `recess`, `pe`, `athletics` and
  `events` join them.
- **Older clients keep working, except for the accepted `levels` removal:**
  `school_guidelines` is additive, and the catalog output is unchanged.
  - The forecast `color` and `aqi_category` values change. No client reads them.
- **Performance.** The level sets and the guidelines definition are in-memory Python, so the
  pages and `monitors/meta/` gain no queries.
  - Verify against the real local database: query counts and timings for `/guidelines/`,
    `/guidelines/schools/`, `monitors/meta/`, `meta/datasets/`, `forecasts/` and the account
    pages, before and after.
  - Run EXPLAIN where a query changes.
  - Cache keys, if any are added, must be memcached-safe.
- **Shared local stack.** Use the throwaway `:8001` container and your own test database.
  Don't swap `sjvaircom_web_1` or restart the Huey workers. Ask the coordinator before
  writing to the local database.
- **Process.** Approved spec, then an approved plan, then code. Branch
  `feature/hardcoded-cleanup` from `origin/develop`, with a PR into `develop`; never merge
  without the user's yes. No AI attribution.

## Left to the builder

- The view structure for the guidelines pages (a view class or a context hook on
  `PageTemplate`) and the template helpers for range text.
- Where the guidelines definition lives (`levels.py` or a sibling module) and its Python
  shape, as long as the JSON above comes out.
- How the tag text color is derived (by tier or by an explicit per-level value), as long as
  today's contrast is kept.
- Whether the TEMPO units' shared definition lives in the tempo app or the catalog.
  `/tempo/products/` must not change: its filter currently relies on `cldo4` being missing
  from `PRODUCT_UNITS`.
- Keeping `lcs.py`'s 10000 top cap; rewriting `test_served_ranges`
  (`camp/apps/entries/tests/test_aqi_breakpoints.py`) against the scale; fixing the stale
  "levels from monitors/meta/" comment in `camp/api/v2/accounts/endpoints.py`.

## Coordination

- Once this spec is approved, send the final `school_guidelines` shape and the `levels`
  removal to sdk-js-8c and the coordinator (data-dashboard-2c). Step 4 spec 4 (a later
  session) reads the shape from data-dashboard ARCHITECTURE.md. Done 2026-11-04.
- Tell the coordinator when the PR opens.
