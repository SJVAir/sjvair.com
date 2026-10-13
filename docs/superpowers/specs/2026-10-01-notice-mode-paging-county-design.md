# Notices mode as a page filter; consistent paging; county column

**Status:** draft for review, 2026-10-01
**Branch:** feature/pesticides-explorer (PR #275)
**Follows:** `2026-10-01-area-data-tab-layout-design.md`

## 1. Scheduled / Past is a filter on the whole page

Applies to the standalone notice list (`/notices/`) and every place's Notices
tab — both render `includes/notice-filters.html`.

- **Control.** The Active/Archive toggle above the form goes. In its place,
  the first field *inside* the filter box: "Notices" with two options,
  **Scheduled** (default, `past` absent) and **Past** (`past=1`), as a
  two-button toggle that submits the form on change like the method select.
  Switching modes drops `archive_year`, `month` and `page`. The archive
  months box stays under the filter box (`tab-aside` / left column) in past
  mode.
- **List.** Unchanged behaviour: scheduled soonest first, or the archive
  newest first, narrowed by month when one is picked. No month = all past
  notices.
- **Stats (Notices tab).** The stat row follows the page: mode, month and
  every filter (product, chemical, method, narrowing). Scheduled: "Scheduled
  now · Acres · Chemicals". Past: "Past notices · Acres · Chemicals" with
  the month in the heading when one is picked ("Past notices in January
  2020"). Computed from the list's own filtered queryset (one
  `stats.notice_summary(queryset)` → `{count, acres, chemicals}`, the same
  acres rule as `upcoming_by_day`: only amounts in acres count, `None` when
  none do), not from `places.upcoming_context`.
- **Map.** Shows the notices the list shows.
  - New endpoint `GET /api/2.0/pesticides/notices/archive/` — same
    GeoJSON feature shape, filters (`bbox`, `chemical`, `product`, `county`,
    `narrow`) and `MAX_NOTICES` cap as `notices/active/`, plus optional
    `year` + `month` (America/Los_Angeles month bounds, as the list uses);
    only notices past the grace period; cached like the active endpoint.
    The two share one implementation (a mode on the base), not a copy.
  - The page's `map_config` points `notices_url` at the archive endpoint in
    past mode, with `year`/`month` in its query string when a month is
    picked (`fetchJson` already appends the bbox with `&`).
  - Map popups and the legend say "Past notice" / "Scheduled …" instead of
    "may begin through …" for an archived notice (a `past` property on the
    archive features).
  - Out of scope: the section page's and chemical/product pages' maps (they
    stay on scheduled notices).

## 2. Paging is the same everywhere

Every paginated list — Products, Chemicals, Commodities, Records (page and
tab), Notices (page and tab), Schools tab:

- One pager: `includes/pagination.html`, placed directly after its table,
  outside the table include (Records currently includes it inside
  `records-table.html`; move it out to the page and tab).
- One behaviour: a junk or out-of-range `?page=` lands on the nearest real
  page (first or last), never a 404 — a shared `NearestPageMixin`
  (`paginate_queryset` via `Paginator.get_page`) used by `ExplorerListMixin`'s
  lists, `RecordsBrowser` (keeping its count reuse and two-query hydration)
  and `NoticeList` (replacing its own override). The Schools tab already
  uses `get_page`.
- One count line above each table, styled as the others' `summary-sentence`:
  the Schools tab's small grey `schools-count` line becomes a
  `summary-sentence` ("312 schools and child care sites · showing 40").

## 3. County column only where it says something

`includes/notice-rows.html` and `includes/records-table.html` drop the County
column when the page is one county's — the context's `county` (the scope
county; on a county's tabs the injected `county=` param sets it) is set.
Everywhere else it stays.

## 4. Remove what's never shown

- The Notices tab stops calling `places.upcoming_context` (its stat row comes
  from §1's summary), so `upcoming_days`, `upcoming`, `upcoming_by_county`
  and the rest aren't built there.
- Sweep the three area-tab mixins (Notices, Records, Schools) and
  `NoticeList` for context keys no template they render reads, and drop
  them. The Overview, section, chemical and product pages are out of scope.

## Testing

- Mode: the control renders inside the form on both pages; past mode list,
  stats and `map_config['notices_url']` (archive endpoint, with year/month
  when picked); switching modes drops month/page; stats follow a chemical
  filter in both modes.
- Archive endpoint: only past-grace notices; month bounds; filters; cap;
  feature shape matches the active endpoint's plus `past`.
- Paging: `?page=99` / `?page=nope` → 200 on a list page, Records page and
  tab, Notices, Schools; the pager sits after the table on Records.
- County column: absent on a county's Notices and Records tabs and on
  `/notices/?county=kern`; present on the valley-wide pages.
- Smoke: `scripts/pesticides_map_smoke.py` on a county Notices tab in both
  modes.
