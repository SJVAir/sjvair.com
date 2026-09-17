# Pesticides Explorer v2 — Design

**Date:** 2026-09-16
**Branch:** `feature/pesticides-explorer` (builds on the v1 explorer already on this branch)
**Status:** Approved design; each sub-project gets its own implementation plan
**Supersedes:** the scope limits in `2026-09-16-pesticides-explorer-design.md` (county-only geography, no records browser, live aggregates). The v1 entity pages, year picker, and county choropleth stay and are extended.

## Goal

Turn the explorer into a comprehensive browser for all of SJVAir's pesticide data,
usable by two audiences:

- **Residents** ("the lay person"): "What is sprayed near me, when, and should I
  care?" Answered by a location search, a place page, section-level maps, a
  month-by-month view, upcoming SprayDays notices nearby, and plain-language
  health notes on every flagged chemical.
- **Researchers and journalists**: browse and filter individual PUR application
  records and NOIs by region, date, chemical, product, commodity, and method,
  with shareable URLs and maps, and take bulk exports through the API and
  Python client.

## Decisions taken during brainstorming

| Fork | Decision |
|---|---|
| Geography | Section level (MTRS, one square mile). Region pages aggregate their sections; "near me" is sections within a radius of a point. |
| Time | Year stays the primary bin with a month breakdown inside it. Records browser gets a free date range. NOIs use one live window, **active** (scheduled from four days ago onward; see NOI timing), plus a monthly archive. |
| Location search | MapTiler geocoding called directly from the browser (the key is already exposed by tile URLs), plus browser geolocation, plus county/city/ZIP pickers as fallback. Location lives in the URL; nothing is stored server-side. |
| Front door | Near-me first. Place page is the primary resident destination; entity browsing is the "explore the data" tier. |
| Health notes | Category-level plain-language notes kept in a datafile (no model, no admin), shown wherever a badge appears. |
| NOI alerts | **Explicitly out.** NOI pages link residents to SprayDays' own sign-up. |
| Records browser | Two paginated, filterable record tables (PUR, NOI) with a map; no CSV button, exports go through the API/client. |
| Maps | Interactive plain-Leaflet section maps for place pages and the records browser, fed by a new sections API. Entity pages keep the static county choropleth. |
| Storage | A per-section, per-month rollup table rebuilt at import time replaces live aggregation everywhere. |

## NOI timing (from SprayDays' About page and our ingested data)

SprayDays publishes a notice of intent 48 hours before a fumigant application
and 24 hours before other restricted-material applications, "or as soon as
practicable". Once a notice is approved the grower has **up to four days after
the scheduled date** to start. In our ingested notices the lead time between
filing and the scheduled time is 0–2 days, and some arrive after the scheduled
time because our fetch runs once daily.

Therefore the explorer never offers a "next 7 / 30 days" window. The live
window is **active**: `scheduled_application >= now - 4 days`. Notice pages
say "Scheduled <date>; may begin any time through <date + 4 days>". The
monthly archive covers everything older. Residents who want advance warning are
sent to SprayDays' own sign-up, which notifies by address for the square-mile
section and its neighbors.

## Sub-projects and build order

1. Rollup table and sections API
2. Interactive section map
3. Records browser and NOI section
4. Near me and place pages
5. Plain-language layer (datafile-driven; can run alongside 4)

Each sub-project ships independently and leaves the site working. Later ones
depend on earlier ones as noted.

---

## 1. Rollup table and sections API

### Model

`pesticides.PesticideUseRollup` (sqid not needed; never exposed by id):

| Field | Type | Notes |
|---|---|---|
| `year` | int | |
| `month` | int | 1–12; 0 when `application_date` is null |
| `county` | FK Region (county) | |
| `mtrs` | FK Region (mtrs), nullable | null when the record had no resolvable section |
| `chemical` | FK Chemical, nullable | |
| `product` | FK Product, nullable | |
| `commodity` | FK Commodity, nullable | |
| `lbs_chemical` | float | Sum |
| `lbs_product` | float | Sum |
| `acres_treated` | float | Sum |
| `applications` | int | Count of PUR rows |

Unique together on the seven key columns. Indexes: `(year, mtrs)`,
`(year, county)`, `(year, chemical)`, `(year, product)`, `(year, commodity)`,
`(mtrs, year, month)`.

Estimated size: a few million rows for four years (the raw table is 6.5M rows;
the rollup collapses same-day repeats of the same key).

### Rebuild

`rebuild_pesticide_rollup --year YYYY` (management command, also called at the
end of `import_pur` for that year): delete the year's rollup rows, then one
`INSERT … SELECT … GROUP BY` from `PesticideUse`. Runs inside a transaction so
readers never see a half-built year. Idempotent. A `--all` flag loops over
loaded years. Rollup rebuild time on the local 6.5M rows is measured and
recorded in the PR.

### Stats switch

`stats.py` keeps its function signatures and return shapes but reads the rollup:
`by_year`, `by_county`, `year_totals`, `top_related`, list-page annotations
(`lbs_subquery`, commodity `chemical_count`), and `landing_stats`. New helpers:
`by_month(uses_or_rollup, year)` and `by_section(...)`. `recent_uses` and the
records browser still read `PesticideUse` (they need individual records).
The landing warm task stays but becomes cheap.

Acceptance: the existing 157 explorer tests pass unchanged except where they
assert on query counts; list pages render in well under a second on the local
dataset (measured and recorded).

### Sections API (v2)

`GET /api/2.0/pesticides/sections/` returns a GeoJSON FeatureCollection of MTRS
sections with rollup totals, for one of:

- `bbox=west,south,east,north` (required unless `lat/lng`), capped to a size
  that returns at most ~2,500 sections; larger boxes return `400` with a
  message so the map zooms in rather than the server melting.
- `lat`, `lng`, `radius` (miles, 1/3/5) — sections whose geometry intersects
  the circle.

Filters: `year` (default latest), `month`, `chemical` (chem code),
`product` (prodno), `commodity` (site code), `county` (slug). Each feature:
`properties = {mtrs, sqid, county, lbs_chemical, lbs_product, acres_treated,
applications}` (the popup fetches `sections/<sqid>/` on click for top
chemicals/products/commodities). MTRS boundaries are 5-point squares in SRID
4326, so they are served as stored; no simplification or per-section geometry
cache is needed. The totals come from one grouped rollup query. Response
cached for an hour keyed on the full query string (the rollup only changes at
import).

Also: `GET /api/2.0/pesticides/sections/<sqid>/` for one section's yearly and
monthly totals and top chemicals/products/commodities (feeds the popup and a
section page in sub-project 3).

Documented in the OpenAPI schema like the other pesticides endpoints; the
Python client gets a matching resource in a follow-up PR on that repo.

---

## 2. Interactive section map

A single plain-Leaflet script, `assets/js/pesticides/section-map.js`, plus a
stylesheet, loaded only on pages that use it. No framework, no bundler; served
through the existing static pipeline like the admin map script.

### Contract

A container carries data attributes:

```html
<div class="section-map"
     data-sections-url="/api/2.0/pesticides/sections/"
     data-notices-url="/api/2.0/pesticides/notice/"
     data-year="2023" data-chemical="" data-product="" data-commodity="" data-county=""
     data-center="36.74,-119.79" data-zoom="11" data-radius="1"
     data-fallback="#county-map-static"></div>
```

Behavior:

- Fetches sections for the current viewport (debounced on moveend), shades them
  with the same five-step quantile ramp and legend the county map uses,
  recomputed from the sections in view. Sections with no data are outlined
  only.
- Draws active NOIs as points within the viewport, with a
  distinct marker and a popup: scheduled date, products, method, link to the
  notice page.
- Click a section: popup with pounds, applications, top three chemicals with
  badges, and links "records in this section" and "this section" (sub-project
  3 pages).
- When `data-radius` is set, draws the circle and fits to it; the "near me"
  page uses this.
- A small control switches the shading metric between pounds and applications.
- Without JavaScript, the container is hidden and the static county map in
  `data-fallback` shows. With JavaScript, the static map is hidden.
- Respects `prefers-reduced-motion`; keyboard-accessible popups; attribution as
  today.

### First use

The records browser (sub-project 3) is the proving ground. Sub-project 2 ships
the script, its CSS, a template include (`pesticides/includes/section-map.html`)
that emits the container plus the static fallback, and a demo route behind
`DEBUG` for development. Browser-level checks are done with the Chrome
extension against local data; unit tests cover the include's rendering only.

---

## 3. Records browser and NOI section

### PUR records browser

`/tools/pesticides/records/`: a paginated (50/page), sortable table of
`PesticideUse` rows with filters:

| Filter | Param | Notes |
|---|---|---|
| Date range | `start`, `end` (ISO dates) | defaults to the selected year |
| Year | `year` | picker as elsewhere; sets the default range |
| County | `county` (slug) | |
| Region | `region` (Region sqid) | city/ZIP/place; MTRS spatial join as the API does |
| Section | `section` (MTRS sqid) | |
| Chemical / product / commodity | sqids | any combination |
| Method | `method` (A/F/G/O) | |
| Near | `lat`, `lng`, `radius` | same semantics as the sections API |

Columns: date, county, section (link), commodity, product, chemical (with
badges), lbs chemical, acres, method. Sortable on date, lbs, acres. The section
map sits above the table with the same filters; the map and table are two views
of one query. Counts and sums for the current filter show above the table
("2,314 applications, 41,200 lbs"), computed from the rollup when the filter
is expressible there (year/month/county/section/entity) and from the records
otherwise (arbitrary dates, regions).

Records are read from `PesticideUse` with `select_related`; the new composite
indexes plus `(application_date)` keep filtered pages fast. The heaviest case,
a region filter with no other constraint, is bounded by the MTRS join and
measured in the plan.

### Section page

`/tools/pesticides/sections/<sqid>/`: a small page for one square mile: map
zoomed to it, yearly and monthly totals, top chemicals/products/commodities,
upcoming NOIs in it, and a link to the records browser filtered to it. This is
where map popups and record rows link.

### NOI section

- `/tools/pesticides/notices/`: active notices (see NOI timing), filterable by county, region, chemical, product,
  method, and near. Table plus map (points). A second tab, "Past notices",
  is the monthly archive with the same filters plus month/year.
- `/tools/pesticides/notices/<sqid>/`: one notice: scheduled date and time,
  county and section on the map, products and chemicals with badges and health
  notes, treated amount, method, and a plain-language note that NOIs are
  intentions, not confirmations. A prominent panel: "Want to be told about
  notices near you? Sign up with SprayDays" linking to SprayDays' notification
  sign-up. No alert features of our own.
- Entity pages' "Planned applications" sections link into `/notices/` filtered
  by that entity; their "Most recent records" shrink to five rows with a
  "Browse all records" link into the browser.

### Navigation

The explorer sub-nav grows to: Near me · Chemicals · Products · Commodities ·
Records · Notices. "Near me" appears when sub-project 4 lands; until then the
tab is absent.

---

## 4. Near me and place pages

### Landing page

Reordered to lead with location:

1. Hero: title, one-line pitch, the year picker.
2. **Find your area**: a search box ("Address, city, or ZIP") backed by MapTiler
   geocoding called from the browser (bounded to California, results as a
   dropdown), a "Use my location" button (browser geolocation), and three
   pickers: county, city, ZIP (regions already loaded). Submitting goes to the
   near-me page or the region page.
3. The SprayDays callout, then the existing stat row, county map, cards,
   leaderboards, and explainer. The explainer gains a "How to read this page"
   panel written for residents.

### Near me

`/tools/pesticides/near/?lat=&lng=&radius=1[&year=]`. Renders the place-page
layout for the sections within the radius. Radius options 1, 3, 5 miles.
A reverse-geocoded label ("near Selma, Fresno County") comes from the same
MapTiler call made client-side and is passed along in a `label` param; the
server never geocodes. The page states in one sentence that the location is
only in the link and is not stored.

### Region pages

`/tools/pesticides/region/<sqid>/<slug>/` for county, city, ZIP, and place
regions: the same place-page layout for the region's sections. County pages
double as the target for county names throughout the explorer (by-county
tables, notice rows), replacing plain text with links.

### Place-page layout (shared by near me and region pages)

1. Header: place name, radius or region type, the year picker.
2. **Right now**: active NOIs within the area ("3 notices
   scheduled nearby"), each linking to its notice page; SprayDays sign-up link.
   Visually separated from the year-binned sections below, as on the landing
   page.
3. Stat row for the year: pounds, applications, sections with any use out of
   sections in the area, distinct chemicals used.
4. Section map (interactive) with the area outlined or the circle drawn.
5. **By month**: a twelve-bar chart of pounds per month for the year,
   rendered as plain HTML/CSS bars from the rollup (no chart library), with the
   peak month called out in a sentence ("Spraying peaks in March here").
6. **What's applied here**: top ten chemicals with badges and health notes,
   top commodities, top products; each row links to its entity page with the
   year preserved, and a "show all" goes to the records browser filtered to
   the area.
7. Links: "Browse all records for this area", "See past notices here".
8. The sources footer.

### Performance

Everything on the place page comes from the rollup grouped by section id, with
the section ids for the area resolved once per request (radius: spatial query
against the cached simplified section geometries; region: the existing MTRS
join, cached per region for a day). Target under one second per page on the
local dataset.

---

## 5. Plain-language layer

### Content

No new model. Notes live in `datafiles/pesticide-health-notes.yaml`, loaded
with the existing `datafile()` helper / `{% load_datafile %}` tag like the
other site content (partners, data providers), and cached in-process for the
request. One entry per key:

| Key | Covers |
|---|---|
| `prop65` | the Prop 65 badge |
| `iarc_1`, `iarc_2a`, `iarc_2b`, `iarc_3` | the IARC badges |
| `carb_tac` | the CARB TAC badge |
| `fumigant`, `cholinesterase_inhibitor`, `groundwater_contaminant`, `biopesticide`, `oil` | DPR category tags |
| `restricted_material` | the product "CA restricted" badge |
| `noi_meaning` | what a notice of intent is (and isn't) |
| `pur_lag` | why the latest year is last year |

Each entry: `title` (short label), `summary` (one to two plain-language
sentences), optional `detail` (a paragraph, markdown allowed), `source_url`
(OEHHA, IARC, CARB, or DPR). Wording changes are a datafile edit and deploy,
the same as the rest of the site's copy.

### Presentation

- Every badge gets a `title` tooltip from `summary` and, on entity, notice, and
  place pages, an expandable "What this means" line under the header listing
  the notes for the badges present.
- Place pages and notice pages get a "How to read this page" panel: what PUR
  is and its lag, what an NOI is, what the shades mean, what the badges mean.
- The explainer on the landing page renders the same notes so copy lives in one
  place.

Deliverable: no badge anywhere without an explanation a resident can read in
one breath, with the copy in one datafile.

---

## Cross-cutting

- **Year picker** on every page with year-binned data; NOIs always shown in
  the active window and visually separated from year-binned blocks.
- **URLs are the only state.** Every view is shareable. No cookies or sessions
  for location or filters.
- **Privacy:** the near-me page explains that the location is only in the URL.
  Server logs contain it as they would any URL; no other storage.
- **Stack:** Django templates, Bulma, plain Leaflet, `django-vanilla-views`,
  the v2 API for JSON. No new frontend framework or build step.
- **Exports:** the API docs and the Python client remain the way to pull data
  in bulk; explorer pages never link to raw endpoints.
- **Accessibility:** tables remain real tables; maps have text equivalents
  (the tables beside them); color is never the only signal (legend text, badges
  with labels).
- **Testing:** Django `TestCase` with the existing `pesticides-explorer` fixture
  extended with a few MTRS sections and rollup rows; per-page query ceilings;
  browser checks with the Chrome extension against local data recorded in each
  PR.
- **Performance gate:** every sub-project's PR records local timings for the
  pages it touches; anything over one second is fixed or explicitly accepted.

## Out of scope

- NOI alerts or notifications of any kind (SprayDays does this).
- CSV/download buttons in the explorer.
- Per-chemical bespoke health copy in the first pass (category-level only).
- Anything below section resolution (PUR has none).
- A mobile-app view (the sections API is designed so one could be built later).
