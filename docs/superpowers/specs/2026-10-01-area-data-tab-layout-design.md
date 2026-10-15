# Area data tabs: one layout

**Status:** approved in conversation 2026-10-01
**Branch:** feature/pesticides-explorer (PR #275); emissions (feature/ceidars-explorer) follows on its own branch

## Goal

The data tabs on an area page — pesticides' Notices, Records and Schools, and
emissions' Facilities, Oil & gas, Dairies and Schools — share one layout, the
one the standalone Records and Notices browsers already use, so moving between
tabs (and explorers) never rearranges the page:

```
[ area header + tab row                 ]
[ stat row                              ]
+---------+-----------------------------+
| filters |  active-filter chips        |
|---------|                             |
| aside   |            MAP              |
+---------+-----------------------------+
[ table / list, full width              ]
[ pagination                            ]
[ charts · related · notes              ]
```

## Today

| Tab | Under the stats | Filters | Table |
|---|---|---|---|
| Records | filters + map (built by hand in `tab-map`) | beside map | full width |
| Schools | map, full width | beside table (`tab_has_filters`) | narrowed |
| Notices | map, full width | none | "Day by day", upcoming only; archive is a link out |

## 1. Shared skeleton — `camp/templates/regions/area-tab.html`

Owned by the pesticides branch (shared files change only there); emissions
merges it down.

Blocks, in page order:

- `tab-notices`, `tab-stats` — unchanged.
- **Filters row.** Left column (`column is-3-desktop`): `tab-filters`, then
  `tab-aside` (new: boxes that aren't the filter form — the school districts
  box, the SprayDays signup, the notice archive months). Right column: the
  active-filter chips (rendered by the skeleton from `active_filters`
  [{label, clear_url}], when present), then `tab-map`.
- When both `tab-filters` and `tab-aside` are empty, `tab-map` is full
  width. No flag: the left column is always rendered (`.tab-side`), and
  area-pages.sass hides it when it holds no elements
  (`.tab-side:not(:has(*)) { display: none }`); Bulma's flex columns then
  give the map column the full row.
- `tab-table` — full width under the filters row. Block name unchanged.
- `tab-charts`, `tab-related`, `tab-notes`, `tab-after` — unchanged.
- `tab_has_filters` and the filters-beside-table wrapper are removed.

Pagination stays in each tab's `tab-table` (each explorer has its own
pagination include and tag library); the rule is only that long lists
paginate.

Phones: the left column stacks above the map (Bulma columns already do this).

Emissions' existing tabs already fill `tab-filters` and `tab-table`, so they
move to this layout with no template edits; anything they show beside the
map that isn't the form goes in `tab-aside`.

## 2. Pesticides tabs

### Records — `area-records.html`
No visible change. The filters, chips and map it builds by hand inside
`tab-map` move into `tab-filters` / the skeleton's chips / `tab-map`.

### Notices — `AreaNoticesMixin`, `area-notices.html`
- Built on `NoticeList` the way the Records tab is built on `RecordsBrowser`:
  `RegionNotices(RegionAreaMixin, AreaNoticesMixin, NoticeList)` (and
  `NearMeNotices`). `dispatch` adds `area.area_params()` to `request.GET`;
  `get_active_filters` drops the place's own chip (same rule as
  `AreaRecordsMixin`).
- `get_map_config` uses the area's framing (`area.map_kwargs()`), as the tab
  does today, plus the list's chemical/product.
- `tab-filters`: the Active/Archive toggle, then the notice filter form
  (chemical, product, method; the hidden fields as on `notice-list.html`).
  `tab-aside`: archive months (past mode), SprayDays signup.
- `tab-table`: the summary sentence, `notice-rows.html`, `pagination.html`
  (50 per page, `NoticeList.paginate_by`).
- `tab-stats`: unchanged — scheduled now / acres / chemicals, always the
  upcoming notices (`places.upcoming_context`), whatever the mode.
- Removed: "Day by day" (`upcoming-notices.html` stays for the section and
  chemical pages), the "Past notices here" link, `archive_url`.
- Share the filter form and archive box between `notice-list.html` and the
  tab via includes (`includes/notice-filters.html`,
  `includes/notice-archive-months.html`) rather than copying them.

### Schools — `AreaSchoolsMixin`, `area-schools.html`
- `tab-filters`: `schools-filters.html`; `tab-aside`:
  `school-districts-box.html` (keeps its own "Show all" past five — a short
  sidebar list).
- The table paginates, 50 rows per page, on `?page=`: `schools_panel` returns
  all filtered/sorted rows and the mixin pages them with Django's `Paginator`
  into `page_obj` / `is_paginated`, so `pagination.html` works unchanged;
  sort and filter params carry through `qs_replace`. A filter or sort change
  resets to page 1 (the filter form doesn't carry `page`; sort links drop it).
- Removed: `SCHOOLS_VISIBLE`, the rows' `is_collapsed`, `hidden`, the schools
  "Show all" button, and the `[data-schools-toggle]` / `.schools-nearby`
  fallback in `explorer.js` (the `[data-reveal-*]` handler stays — the
  districts box and the "In and around" lists use it).
- Out of range `?page=` → last page (not a 404), as on the other browsers.

## Testing

- Skeleton: with filters/aside → two columns, chips above the map; with
  neither → no left column; `tab-table` outside the columns.
- Notices tab: narrowed to its place (a notice elsewhere is absent); past mode
  lists archived notices and archive months count only the place's; chemical
  filter; the place's own chip isn't offered; stats count upcoming in past
  mode; paginates past 50.
- Schools tab: 51+ rows → two pages; sort and type filter survive paging; a
  filter change lands on page 1; bad `?page=` is not a 500.
- Update existing area-tab, notices, schools tests that assert the old markup.
- `scripts/pesticides_map_smoke.py`: Notices and Schools checks for the new
  positions.

## Out of scope

- The Overview and Community tabs (no filters or tables).
- Emissions' template changes — emissions moves its own tabs (see §1).
