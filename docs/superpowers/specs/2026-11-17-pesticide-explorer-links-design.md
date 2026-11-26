# Pesticide explorer links in meta, section-detail filters, shades note

Date: 2026-11-17. Branch `feature/pesticide-explorer-links`, PR into `develop`.

## Why

The data dashboard's Map opens a card for a section of pesticide use. The card mirrors the
explorer map's section popup (`assets/js/pesticides/section-map.js`, `sectionPopupHtml`) and
carries its links: Section details, Records here, Notices here, and each top chemical's page.
Each link opens in a new tab. Metadata is the source of truth, so the server serves these links,
as it already serves `links.spraydays_signup`, and clients hold no site URLs. The card's months
and top chemicals follow the Map's filters, so `sections/<id>/` takes those filters. One help
note names a colour that the dashboard doesn't draw.

## Goals

1. `pesticides/meta/` `links` gains URL templates for the four links, plus a documented map of
   the query parameters each link takes and the value that fills each one.
2. `pesticides/sections/<id>/` takes the map layers' value filters and `month`, opt-in.
3. The `notes.shades_valley` summary drops "Gray".

## Non-goals and anti-goals

- **The explorers must not change behaviour.** Their data attributes, pages and the responses
  the explorer popup gets from `sections/<id>/` stay byte-for-byte the same. A change that
  alters any of them is a failure even if the dashboard works.
- No new parameters on the explorer pages, such as a `month` on records or a day on notices.
  The links use only what the pages already take.
- No "Zoom in" link.
- No `county` in any link: the dashboard never sends it on sections.

## Approaches

- **Templates plus a parameter map in meta (chosen).** Each link is a URL template with `{id}`.
  Beside the templates, `link_params` lists, per link, the query parameters the page takes and
  the value that fills each one. The client appends the values it has. Meta stays static and is
  cached for a day. The client does no work beyond filling values, apart from a month's first
  and last day.
- Templates with every parameter as a placeholder (`…&year={year}&chemical={chemical}…`). This
  was dropped: blank placeholders need an "omit when empty" rule, and the URLs carry empty
  parameters.
- Concrete URLs on `sections/<id>/`, built from the request's own parameters. This was dropped:
  the endpoint would accept parameters that only feed the links, and the cached response would
  carry site URLs. The coordinator also decided the links belong in meta.

## Design

### 1. `links` and `link_params` in `pesticides/meta/`

All link URLs are absolute, like `spraydays_signup`, so that a client on another origin (SDK
users) gets working links. The origin is the request's (`request.build_absolute_uri('/')`, with
the path from `reverse()` appended; passing the template itself would percent-encode the
braces). The explorer is mounted at `/tools/pesticides/`, and a test asserts those real paths.
Behind a proxy that keeps the browser's `Host` (for example the dashboard's Vite dev proxy,
`changeOrigin: false`), the origin is the proxy's, so the links work there only if that proxy
also forwards `/tools/`. In production the dashboard is served from the site itself, so the
origin is the site. `{id}` is the section's or chemical's sqid. Keys are permanent.

```json
"links": {
  "spraydays_signup": "https://…",
  "section_page": "https://www.sjvair.com/tools/pesticides/sections/{id}/",
  "section_records": "https://www.sjvair.com/tools/pesticides/records/?section={id}",
  "section_notices": "https://www.sjvair.com/tools/pesticides/notices/?section={id}",
  "section_notices_past": "https://www.sjvair.com/tools/pesticides/notices/?section={id}&past=1",
  "chemical_page": "https://www.sjvair.com/tools/pesticides/chemicals/{id}/"
},
"link_params": {
  "section_page": [{"param": "year", "from": "year"}, {"param": "narrow", "from": "narrow"}],
  "section_records": [
    {"param": "year", "from": "year"},
    {"param": "start", "from": "month_start"},
    {"param": "end", "from": "month_end"},
    {"param": "chemical", "from": "chemical_id"},
    {"param": "product", "from": "product_id"},
    {"param": "commodity", "from": "commodity_id"},
    {"param": "method", "from": "aerial_ground"},
    {"param": "narrow", "from": "narrow"}
  ],
  "section_notices": [
    {"param": "chemical", "from": "chemical_id"},
    {"param": "product", "from": "product_id"},
    {"param": "narrow", "from": "narrow"}
  ],
  "section_notices_past": [
    {"param": "archive_year", "from": "notices_year"},
    {"param": "month", "from": "notices_month"},
    {"param": "chemical", "from": "chemical_id"},
    {"param": "product", "from": "product_id"},
    {"param": "narrow", "from": "narrow"}
  ],
  "chemical_page": [{"param": "year", "from": "year"}, {"param": "narrow", "from": "narrow"}]
}
```

**Fill rule.** Replace `{id}` with the sqid, then append `&param=value` (or `?` when the
template has no query) for each entry whose `from` value the client has. Skip the entries it
doesn't have. Values are URL-encoded. The `from` values:

- `year`: the period's year (`all` for all years). Records needs it as well as the dates.
- `month_start`, `month_end`: the first and last Pacific calendar day of a month period
  (`YYYY-MM-DD`). Records has no `month`; it takes dates inside the year. For a year period,
  leave them off.
- `chemical_id`, `product_id`, `commodity_id`, `aerial_ground`, `narrow`: the values the client
  sends to `sections/`, under the same names.
- `notices_year`, `notices_month`: the year and month (1-12) of the notices layer's chosen day.

**Which notices link.** Use `section_notices_past` when the Map's notices layer is on and
showing a past day (its features carry `past: true`). Use `section_notices` otherwise. This
matches the explorer: its archive page links the archive month, and every other map links the
upcoming list. The notices list can't narrow to one day, so a past day lands on its month.

**Left off, because no explorer page takes them:** `category` and `iarc_group` on every link,
and `month` on the section and chemical pages (they show the year). `aerial_ground` is left off
the notices links: the notices page filters on SprayDays' own wording, and the codes don't map
onto it (`O` means any other method). `commodity_id` is left off the notices links (notices
record no commodity).

The entity ids carry over as-is: the explorer pages read `chemical`, `product` and `commodity`
as our sqids. The chemical link is the bare-sqid redirect, which passes the query along to the
slugged page.

**Reuse.** The base templates come from the code the explorer map already uses
(`page_url_pattern`, and the records and notices `reverse(...) + '?section={id}'`). Those move
into small helpers that both `section_map_config` and meta call. A test checks that the explorer
map's config, and so its data attributes, is unchanged.

The explorer pages and `/workspace` are both behind the `beta_tools` gate
(`camp/utils/beta.py`), so a dashboard user can open every link.

### 2. Filters on `pesticides/sections/<id>/`

New optional parameters: `chemical_id`, `product_id`, `commodity_id`, `category` (repeated or
comma-separated, any of them), `iarc_group`, `aerial_ground`, and `month` (1-12). `narrow`
already works. They are validated and applied as on `sections/` (`parse_map_filters(params,
ROLLUP_MAP_FILTERS)` and the matching part of `apply_filters`). A bad value is a 400
`{"error": …}` with the same messages.

- The value filters narrow `years`, `months` and the top lists.
- `month` narrows only the top lists. `months` stays the year's twelve rows.
- **Counting matches `sections/`** (`section_figures`), so the card agrees with the map's shading.
  With `chemical_id`, the per-ingredient columns count. With `category` or `iarc_group` and no
  `chemical_id`, a record can match on several ingredient rows, so acres, applications and
  product pounds take the MAX per record key. Otherwise the once-per-record columns count.
  Top chemicals and top commodities rank by chemical pounds, which are per ingredient either way.
- The CDPR-code forms (`chemical`, `product`, `commodity`, `method`) and `county` stay ignored,
  as today.
- **Opt-in.** With none of the new parameters, the response is byte-for-byte what it is today
  (a test). The cache key is the view plus the query string, so each filter set is its own
  entry. `cache_key_version` stays 1, because unfiltered answers don't change.

### 3. `notes.shades_valley`

The last sentence, "Gray means nothing was reported.", becomes "An outline with no shading
means nothing was reported." Only meta serves this note; the explorer uses `shades`, which is
unchanged. The test at `camp/api/v2/pesticides/tests.py:2402` follows.

### Docs

The meta docstring, the `sections/<id>/` docstring, the API docs and the `CLAUDE.md` meta
bullet describe the new keys, the fill rule, the notices rule and the section-detail params.

## Deploy and cache

No deploy step beyond a normal deploy: no migration, command or cache clear. `pesticides/meta/`
is `public, max-age=86400`, so a client may see the old meta, without the new keys, for up to a
day after the deploy. `sections/<id>/` cache entries for unfiltered requests stay valid.

## Left to the builder

- The helper names and module for the shared URL templates.
- How the record-key MAX counting is reused for `years` and `months` on one section (extend
  `stats.section_totals_by_record`'s approach or add per-year and per-month variants).
