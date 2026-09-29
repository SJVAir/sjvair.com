# Pesticides explorer: the section map as a filter

> **Shelved 2026-09-28.** Built in full (commit beb3def5), reviewed, then taken
> back out in the following commit. Derek's call after using it: a map click that
> narrows the page changes scope outside the scope bar, and "we don't want to
> surprise users". Scope has one home -- the scope bar. The section popup's
> "Section details", "Records here" and "Notices here" links already lead to a
> square mile's data without rewriting the page underneath the reader.
> A UI review also found the response landed off-screen (banner and stat row sit
> above a below-the-fold map; the Map page's panel starts at the fold), the page
> shifted under the cursor as content above the map changed height, a click gave
> less at the map than the popup it replaced, and at the valley zoom the lens's
> ~3 px sections made the click a lottery. Kept from the work: the count
> formatting fix (counts no longer read "7.0") and the shared
> `section_summary()` / section includes behind the section page.

Date: 2026-09-28. Branch: `feature/pesticides-explorer` (draft PR #275).

## Why

A section's popup already leads out to that square mile's page, records and
notices, but clicking a square doesn't change the page around the map. Derek
calls this "the difference between a report and a tool" and ranks it the
largest remaining piece of the explorer. The goal: click one square mile and the
page you are on answers its question *for that square mile*.

## Decisions (Derek, 2026-09-28)

- **Where:** the Map page and the chemical / product / commodity detail pages.
  Every other page with the section map (place pages, records browser, notices
  list, section detail, notice detail) keeps today's popup, unchanged.
- **Unit:** one 1 x 1 mile MTRS section at a time. Townships are never a
  filter. Zoomed out, the hover lens already exposes the sections of the 3 x 3
  townships under the pointer, and only a section can be clicked. Zoomed in,
  the grid's sections are clicked directly.
- **Click:** a click filters immediately. The popup shrinks to a label,
  because the numbers it used to carry now fill the page below.
- **Persistence:** the section belongs to the page it was clicked on. It is not
  an explorer-wide scope like year/county, and it is not in `scope_qs` or the
  scope bar. Links *out* of a narrowed page (records, a related card's "Show
  all", notices) carry the section to the records browser and notices list,
  which already honor `?section=`. A related entity's own page opens
  unnarrowed.

## Approach: a server re-render over the existing htmx swap

A click navigates to the same URL with `?section=<sqid>` added, via the same
boosted `#explorer` swap links and filter forms already use. The server renders
the narrowed page. The swap brings in a new map container, which the
running map **adopts in place** (`adopt()`, as it already does across swaps),
so the camera, layers and toggles stay put and only the content around the map
changes.

Consequences, all wanted:

- A narrowed page is an ordinary GET. It is linkable, it renders without JS, and
  back/forward step through selections (htmx pushes the URL).
- No new API, and no JS copies of templates. Narrowing is one extra filter on
  the rollup (`PesticideUseRollup.mtrs`), the same filter `area_filter()`
  already applies for the records browser.

Rejected: client-side JSON fetch + JS-rendered cards/charts (duplicates every
template in JS); a full page reload (the map rebuilds and loses its view on every
click).

## The map (`assets/js/pesticides/section-map.js`)

- **Opt-in.** `section_map_config(..., select='filter')` emits
  `data-select="filter"` on the map container. Without it the map behaves
  exactly as today. The Map page and the three entity detail views pass it.
- **Click.** In filter mode, a click on a section in the grid (section level),
  the lens, or the all-sections layer calls a `selectSection(sqid)` that
  navigates to the current URL with `section` set (other params kept: year,
  county, compare, narrow, the map's own `tiles`/`ramp`/`bins`/`metric`/
  `notices`/`sections`/`locations`, and the Map page's entity filters). The
  navigation goes through htmx with a pushed history entry and the boosted
  swap's target/select, so it is indistinguishable from following a link.
- **Clicking the selected section again** clears the selection (navigates
  without `section`).
- **Townships.** A township click at township level does what it does today.
  It never filters.
- **Markers.** Notice and school/child-care markers keep their own popups. The
  existing `sectionMapTaken` guard already gives them the click first.
- **Camera.** An adopt must not refit or recentre when the new config carries a
  selected section. The reader clicked on something they can already see.
  A fresh load of a narrowed URL (a pasted link, a reload) opens fitted to the
  section, as the section detail page does (centroid, zoom 13).
- **Selection outline.** The selected section is drawn with the existing
  `highlight` source/layers. The config's `highlight` is the selected sqid, and
  `onAdopt` updates the outline when it changes.
- **The label popup.** On a narrowed page, the selected section carries a
  one-line popup: `Section <external_id> · Open section page · Clear`. "Open
  section page" goes to `section-detail` (scope kept). "Clear" navigates
  without `section`. It opens after each selection and after an adopt that
  changed the selection, and it can be closed without clearing.
- **Hover/cursor.** Unchanged, apart from the pointer cursor over sections in
  filter mode, which it already shows.

## Entity detail pages (`ExplorerDetailMixin`)

- **Resolution.** `?section=` resolves through `resolve_related(request.GET,
  {'section': SECTION_REGIONS})`. An unknown or non-MTRS sqid renders the page
  with a "No matches for that section" notification and empty narrowed data,
  never a silently unfiltered page, matching the Map page's `no_matches`.
- **Narrowing.** `get_rollup()` adds `.filter(mtrs=section)`. That flows through
  everything built from it: the stat row, the summary sentence, the trend chart,
  the by-year table, the month heatmap, and both related cards. `get_notices()`
  results are narrowed to `mtrs=section` in the mixin, so each subclass stays
  as it is.
- **Summary sentence.** With a section: "Applied in Section `<external_id>`
  in `<year label>`, mostly on ..." in place of the county-count phrasing.
- **Hidden while narrowed:** the by-county table, the county map, and
  "Counties that moved most". A section lies in one county, so they have
  nothing to compare. `movers_context`, `by_county` and `county_map` are not
  computed.
- **Banner.** Under the detail header: "Narrowed to Section `<external_id>`
  (`<county>`) · Open section page · Clear". Clear is a plain link to the page
  without `section`. It sits in `detail-base.html` so all three entity
  templates get it.
- **Caching.** `cached_stat` builds live (no cache) when a section is set. A
  section is at most a few thousand rollup rows across every year, and the
  section detail page already aggregates live for the same reason.
- **Links out** gain `&section=<sqid>`: `records_url`, each related card's
  `show_all_url` (the records browser, since that honors `section`. The list
  pages don't), and `notices_url`. `full_map_url` carries it too, so "Open in
  the full map" lands on the Map page with the same selection.
- **The map config** gets `select='filter'`, and with a section,
  `highlight=<sqid>` plus the section's centroid/zoom 13 for a fresh load.
- **County scope.** A section and a county scope that don't intersect produce
  an empty narrowed page with the normal "No confirmed applications" states.
  No special case.

## The Map page (`MapPage`, `pesticides/map.html`)

- `?section=` resolves as above. MISSING joins the page's existing
  `no_matches`.
- With a section, a panel renders **below the map**. It carries the section
  detail page's content, built from the same rollup narrowed further by the
  map's active entity filter (`?chemical=` / `?product=` / `?commodity=`) and
  the concern narrowing:
  a heading ("Section `<external_id>`, `<county>`" plus the entity when one is
  set), the stat row (lbs, applications, chemicals), month bars with the peak
  month line, the top products / chemicals / commodities cards (products
  first), upcoming notices in the section, and "Browse records in this
  section" (records URL with section + entity + scope).
- **Shared code.** The section detail page's aggregation moves from
  `SectionDetail.get_context_data` into a function
  (`section_summary(section, rows, year, all_years, ...)` in `views.py` next to
  `_section_card`) and its markup into
  `pesticides/includes/section-summary.html`. `SectionDetail` and `MapPage`
  both use them, so the two can't drift.
- The page's filter chips (`filters`) gain the section, with its clear URL.
- No section: the page is exactly as today.

## Out of scope

Click-to-filter on the records browser and notices list (both already accept
`?section=` and could opt in later with `select='filter'`); selecting several
sections; township or drawn-area selection; carrying the section across
navigation.

## Testing

- **View tests** (`camp/apps/pesticides/tests/test_views.py`, Django
  `TestCase`, plain `assert`):
  - chemical, product and commodity detail with `?section=`: totals, by-year
    and related rows come only from that section's rollup rows;
  - the by-county table, county map and movers are absent;
  - a bad or non-MTRS sqid gives `no_matches` and no unfiltered data;
  - `records_url`, `show_all_url`, `notices_url` and `full_map_url` carry
    `section=`;
  - the map config has `select == 'filter'` and `highlight == sqid`;
  - the Map page with a section renders the panel; with `?chemical=` too, the
    panel's totals are that chemical's in that section; without a section,
    there's no panel;
  - section detail still renders the same content through the shared
    include (the existing tests keep passing).
- **Map smoke** (`scripts/pesticides_map_smoke.py`): on a chemical page, click
  a section → the URL gains `section=`, the banner appears, the map container
  is the same element (adopted, not rebuilt), and the camera didn't move;
  click it again → cleared; back → reselected.
- **Browser check on :8002:** a lens click while zoomed out, a direct click
  zoomed in, Clear from the label and from the banner, back/forward, a pasted
  narrowed URL, and a phone-width pass. A blank map in an unfocused tab is
  MapLibre throttling, not a bug.
- Full suite through the worktree harness before handing back.
