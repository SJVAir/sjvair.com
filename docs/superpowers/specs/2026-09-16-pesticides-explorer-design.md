# Pesticides Data Explorer — Design

**Date:** 2026-09-16
**Branch:** `feature/pesticides-explorer`
**Status:** Approved design, pending implementation plan

## Goal

A public, server-rendered browser for the pesticides data already ingested by
`camp.apps.pesticides`: chemicals, products, and commodities, cross-linked to each
other and to where and when they are applied. Confirmed applications come from
DPR's Pesticide Use Reporting (PUR, `PesticideUse`); planned applications come
from SprayDays notices of intent (`PesticideNotice`).

Audience is both community members (plain-language classification context, "what
is sprayed where" framing) and journalists/researchers (dense sortable tables,
per-year and per-county totals, links into the raw API).

## Scope

### In

- `/tools/pesticides/` landing page with explainer, live stats, leaderboards.
- List pages with search, filters, sortable columns, pagination for chemicals,
  products, commodities.
- Detail pages for each, with classification, related entities, confirmed
  (PUR) and planned (SprayDays) application summaries and recent records.
- Postgres full-text `.search()` queryset methods on the three
  models, following the helpdesk pattern.
- `get_absolute_url()` on `Chemical`, `Product`, `Commodity`.
- A "Data Tools" navbar dropdown containing "Pesticide Data", plus a
  footer link.
- Tests for querysets, views, templates, and query counts.

### Out (explicitly deferred)

- Community/place-level geography. v1 is **county only**. Finer regions use the
  MTRS spatial join already present in the API and can be added later.
- A full paginated browser of individual PUR records or notices. Detail pages
  show the 10 most recent / next 10 and link to the v2 API for the rest.
- Precomputed summary tables. v1 aggregates live over `PesticideUse`. See
  Performance.
- Changes to the v2 API filters (they keep `icontains`).
- Charts. (A static county map is in scope; see County map.)

## Data facts that shape the design

- Local/prod volume: ~4.4k chemicals, ~70k products, ~540 commodities,
  ~1.6M `PesticideUse` rows per year (6.5M for 2020–2023 locally), tens of
  notices at a time.
- `PesticideUse.county` is a direct FK to a county `Region`; `mtrs` is nullable.
- `PesticideNotice` has `chemicals` and `products` M2M but **no commodity**.
- `Chemical.categories` is an `ArrayField` of DPR category codes. Prop 65 and
  CARB TAC status are *derived* from categories (see Classification), not
  separate fields.
- `Chemical.iarc_group` is one of `1`, `2A`, `2B`, `3`, or blank.
- All three models have `sqid` (django_sqids) as the public identifier.

## Architecture

### Files

```
camp/apps/pesticides/
  views.py          # vanilla ListView / DetailView subclasses + Home
  urls.py           # namespace 'pesticides'
  forms.py          # filter/search GET forms
  querysets.py      # + .search() on Chemical/Product/Commodity querysets
  stats.py          # aggregate helpers shared by views (latest year, by-year,
                    #   by-county, related rankings, landing stats)
  tests/            # tests.py converted to a package
    __init__.py
    test_spraydays.py     # existing tests, moved
    test_querysets.py
    test_views.py
    test_stats.py
camp/templates/pesticides/
  base.html               # extends page.html: header, breadcrumbs, sub-nav
  home.html
  chemical-list.html
  product-list.html
  commodity-list.html
  detail-base.html        # shared detail layout, blocks for entity specifics
  chemical-detail.html
  product-detail.html
  commodity-detail.html
  includes/
    filter-form.html
    data-table.html       # sortable header + pagination chrome
    stat-row.html
    classification-badges.html
    by-year-table.html
    by-county-table.html
    recent-uses.html
    upcoming-notices.html
fixtures/pesticides-explorer.yaml   # test fixture
```

No new models, no schema migrations.

### Routing

Mounted in `camp/urls.py` **above** the catch-all `PageTemplate` route:

```python
path('tools/pesticides/', include(('camp.apps.pesticides.urls', 'pesticides'), namespace='pesticides')),
```

| Name | Path |
|---|---|
| `pesticides:home` | `tools/pesticides/` |
| `pesticides:chemical-list` | `tools/pesticides/chemicals/` |
| `pesticides:chemical-detail` | `tools/pesticides/chemicals/<sqid>/<slug>/` |
| `pesticides:product-list` | `tools/pesticides/products/` |
| `pesticides:product-detail` | `tools/pesticides/products/<sqid>/<slug>/` |
| `pesticides:commodity-list` | `tools/pesticides/commodities/` |
| `pesticides:commodity-detail` | `tools/pesticides/commodities/<sqid>/<slug>/` |

The slug is `slugify(name)`, generated in `get_absolute_url()`, and ignored on
lookup (lookup is by `sqid` only). A bare `<sqid>/` path also resolves and
redirects permanently to the slugged URL so short links work.

### Views

All views are `vanilla` class-based views, matching `camp/apps/helpdesk/views.py`.

**List views** (`ChemicalList`, `ProductList`, `CommodityList`) share a
`ExplorerListMixin`:

- `paginate_by = 50`.
- `get_queryset()`:
  1. Start from the model manager.
  2. If `q` is present and non-blank, apply `.search(q)`.
  3. Apply the existing v2 `FilterSet` (`ChemicalFilter`, `ProductFilter`,
     `CommodityFilter`) to `request.GET` for the non-search filters.
     Category filtering for chemicals is handled in the view instead, because
     the view accepts multiple categories (OR) while the API filter accepts one.
  4. Annotate list columns (see List pages).
  5. Apply sort from `sort` param against a per-view allowlist
     (`sort_fields = {'name': 'name', 'lbs': '-lbs_applied', ...}`). Unknown
     values fall back to the default. A leading `-` in the param flips
     direction.
- Context includes `form` (bound filter form), `sort`, `latest_year`,
  `result_count`, and a `summary_sentence` string describing the active
  filters in plain language.

**Detail views** (`ChemicalDetail`, `ProductDetail`, `CommodityDetail`) share
`ExplorerDetailMixin`:

- `lookup_field = 'sqid'`, `get_object_or_404` semantics via vanilla.
- Context is assembled from `stats.py` helpers (see Detail pages).

**`Home`** is a `TemplateView` whose context comes from
`stats.landing_stats()`, cached (see Caching).

### Search

`.search(query)` on each queryset, mirroring `camp/apps/helpdesk/managers.py`:

```python
def search(self, query):
    search_query = SearchQuery(query)
    search_vector = SearchVector('name', weight='A') + SearchVector('cas_number', weight='B')
    return (self
        .annotate(search=search_vector, rank=SearchRank(search_vector, search_query))
        .filter(Q(search=search_query) | Q(name__icontains=query))
        .order_by('-rank', 'name'))
```

Fields per model:

| Model | Weight A | Weight B |
|---|---|---|
| Chemical | `name` | `cas_number` |
| Product | `name` | `reg_number` |
| Commodity | `name` | `site_code` |

The `icontains` OR keeps partial-token typing working (`chlor` matches
`CHLORPYRIFOS`), which pure tsquery matching would not. When a search is
active, the list view's default sort is rank; any explicit `sort` param
overrides it.

### Classification (chemicals and products)

Derived properties on `Chemical`:

| Property | Rule |
|---|---|
| `is_prop65` | any of `carcinogen`, `reproductive_toxin`, `developmental_toxin` in `categories` |
| `is_tac` | `toxic_air_contaminant` in `categories` |
| `iarc_group` | existing field; blank means "not evaluated" |
| `is_of_concern` | `is_prop65 or is_tac or iarc_group in ('1', '2A', '2B')` |

`Product` mirrors these as "contains a chemical that…" by checking its
`chemicals`. The detail queryset prefetches chemicals so this is not N+1.

Badges are rendered by `includes/classification-badges.html`, each with a
plain-language `title` and an anchor link to the matching explainer section on
the landing page (`#prop65`, `#iarc`, `#tac`, `#categories`).

### Latest full year

`stats.latest_year()` returns `max(PesticideUse.year)`, cached 1 hour under
`pesticides:latest-year`. Every "latest year" number in the explorer uses this
single value. PUR is published as whole years, so the max year is always a
complete year.

## List pages

Shared chrome from `pesticides/base.html`: page header, breadcrumbs
(Pesticides Explorer › Chemicals), and a sub-nav with Chemicals / Products /
Commodities tabs.

Layout: filter form in a left sidebar column (`is-3-desktop`), results in the
main column. The form is GET, with Apply and Clear buttons, and preserves
values. Above the table: result count and the summary sentence, e.g.
"12 chemicals in IARC Group 2A matching 'chlor'". Below: Bulma pagination that
preserves all current query params.

Sortable column headers link to the same URL with `sort` toggled, preserving
filters and resetting `page`. The active sort shows a direction icon.

| Page | Search + filters | Columns | Default sort |
|---|---|---|---|
| Chemicals | `q`; `category` (checkbox group, OR); `iarc_group` (select) | name, categories (tags), IARC group, products (count), lbs applied (latest year) | `-lbs_applied`; `rank` when `q` present |
| Products | `q`; `fumigant` (any/yes/no); `california_restricted` (any/yes/no) | name, reg number, fumigant + restricted (tags), active ingredients (count), lbs applied (latest year) | `name`; `rank` when `q` present |
| Commodities | `q` | name, site code, chemicals (count), lbs applied (latest year) | `-lbs_applied`; `rank` when `q` present |

**Related-entity filters.** Each list accepts hidden `chemical=<sqid>`,
`product=<sqid>`, or `commodity=<sqid>` params (whichever apply) that restrict
the list to entities linked to that object: products/commodities by
`PesticideUse` rows, product↔chemical by `ProductChemical`. When active, the
summary sentence names the related object with a link and a "clear" control,
and the filter is carried in pagination and sort links like any other param.
The filter form does not render an input for it.

Annotations:

- `lbs_applied = Sum('pesticide_uses__lbs_chemical', filter=Q(pesticide_uses__year=latest_year))`
  (for products, `lbs_product`).
- `product_count = Count('products', distinct=True)` on chemicals.
- `chemical_count = Count('product_chemicals', distinct=True)` on products;
  `Count('chemicals', distinct=True)` on commodities.

Product rows link "reg number" to the same product detail, and each chemical
row's category tags are links to the chemical list filtered by that category.

## Detail pages

`detail-base.html` provides the layout; entity templates fill blocks. Sections,
top to bottom:

1. **Header.** Name, identifiers, classification badges. Chemical: chem code,
   CAS number, DTXSID (linked to CompTox when present). Product: reg number,
   product number. Commodity: site code.
2. **At a glance.** `includes/stat-row.html` with: lbs applied (latest year),
   applications (latest year), counties applied in (latest year, "6 of 8"),
   upcoming notices (chemical/product only). Below, one generated sentence:
   "Applied in 6 of 8 SJV counties in 2023, mostly on Almond and Grape."
   (top 2 commodities by lbs; for a commodity page, top 2 chemicals).
3. **Related.** Two side-by-side cards, each a top-10 table ranked by lbs
   (latest year) with a "show all" link:
   - Chemical: products containing it (with `pct_active`) and commodities.
   - Product: active ingredients (`pct_active`) and commodities.
   - Commodity: chemicals and products.

   "Show all" links go to the corresponding list page with a related-entity
   filter (below), e.g. `products/?chemical=<sqid>`.
4. **Confirmed applications (PUR).** By-year table (year, lbs, acres treated,
   applications) across all loaded years; by-county table for the latest year
   (county, lbs, acres, applications); then the 10 most recent use records
   (date, county, commodity, product/chemical, lbs, method), each linked.
   A developer note in the footer links to the API docs and the Python client docs, with the filter hint `chemical=<chem_code>`
   (or `product=`, `commodity=`).
5. **Planned applications (SprayDays).** Chemical and product pages only.
   Upcoming count by county, then the next 10 notices (scheduled date, county,
   method, treated amount + units, other chemicals/products on the notice,
   linked). Commodity pages show a one-line note that notices do not include
   the crop.
6. **Sources and caveats.** PUR years loaded (min–max), SprayDays window (count
   of notices and date range), link to landing page methodology.

Section 4 is omitted with an empty-state message when the entity has no use
records; section 5 likewise when there are no upcoming notices.

### County map

`camp/utils/leaflet.py` (merged to main 2026-09-16) renders a non-interactive
Leaflet map from `Area`/`Marker` elements plus a GeoJSON payload; the browser
draws it with the bundled `js/admin/leaflet/*` assets. The explorer reuses it
for a county choropleth:

- `camp/apps/pesticides/maps.py` exposes `county_geometries()` (the eight
  county boundaries simplified to ~0.005°, as GeoJSON strings keyed by region
  pk, cached 24h under `pesticides:county-geometries`; about 33 KB total) and
  `county_map(by_county_rows)` which shades each county by its share of the
  max `lbs` on a five-step sequential ramp, greys counties with no rows, labels
  each with name and pounds, and returns the rendered HTML (or `None` when no
  county has a boundary).
- Detail pages show it beside the by-county table for the latest year.
- The landing page shows it for total pounds in the latest year (the rows come
  from `landing_stats()['by_county']`, so they're cached; the map HTML itself
  is rendered per request and is cheap).
- `pesticides/base.html` includes the Leaflet CSS/JS via the `extra-head` and
  `javascripts` blocks. A style rule makes the fixed-pixel container fluid.

### Aggregate helpers (`stats.py`)

All take a base `PesticideUse` queryset already filtered to the entity, so the
same functions serve all three detail pages.

| Function | Query |
|---|---|
| `by_year(qs)` | `values('year').annotate(lbs=Sum, acres=Sum, applications=Count).order_by('-year')` |
| `by_county(qs, year)` | `filter(year=year).values('county__name','county__slug','county__sqid').annotate(...).order_by('-lbs')` |
| `top_related(qs, year, field, limit=10)` | `filter(year=year).values(field, f'{field}__name', f'{field}__sqid').annotate(lbs=Sum).order_by('-lbs')[:limit]` |
| `recent_uses(qs, limit=10)` | `select_related(county, product, chemical, commodity).order_by('-application_date')[:limit]` |
| `upcoming_notices(qs, limit=10)` | `filter(scheduled_application__gte=now()).select_related('county').prefetch_related('chemicals','products')[:limit]` |
| `upcoming_by_county(qs)` | `filter(scheduled_application__gte=now()).values('county__name','county__sqid').annotate(n=Count('id'))` |
| `landing_stats()` | see Landing page |
| `county_map(...)` | see County map (`maps.py`) |

Sum fields: `lbs_chemical` for chemical/commodity pages, `lbs_product` for
product pages. Application count is `Count('id')` (rows), not
`Sum('application_count')`, because PUR rows are already one application each
for the counties we load and `application_count` is nullable.

## Landing page

`home.html` sections:

1. Intro: what the tool is, two sentences on PUR and SprayDays, the eight
   counties covered.
2. Stat row: PUR years loaded, chemicals / products / commodities counts, total
   lbs applied in the latest year, upcoming notices in the next 7 days.
3. Three cards linking to each list page, with one-line descriptions and an
   example search link (e.g. "Try: glyphosate").
4. Leaderboards, latest year: top 10 chemicals by lbs; top 10 chemicals *of
   concern* by lbs (filtered to `is_of_concern`); top 10 commodities by lbs.
5. Explainer with anchors: `#pur`, `#spraydays`, `#categories` (DPR category
   definitions), `#prop65`, `#iarc` (groups 1/2A/2B/3), `#tac`. Caveats: PUR
   lags roughly a year; SprayDays covers notices of intent for restricted
   materials only; v1 location resolution is county.

Between the stat row and the cards, the county map of total pounds in the
latest year.

`landing_stats()` returns a dict with all of the above numbers and lists, plus
`by_county` rows for the map. The
chemicals-of-concern board is computed in Python by filtering the top-N query
result, since `is_of_concern` is derived; the query pulls top 50 and filters to
10, falling back to a second query with `categories__overlap` if fewer than 10.

## Caching

| Key | TTL | Contents |
|---|---|---|
| `pesticides:latest-year` | 1 h | int |
| `pesticides:landing-stats` | 24 h | landing dict |

Everything else is uncached in v1. Tests use the local-memory cache from
`camp.settings.test`; tests that assert on stats call `cache.clear()` in
`setUp`.

## Performance (known risk, accepted)

At ~1.6M rows/year, the list-page `lbs_applied` annotation joins one year of
`PesticideUse` per request, and sorting by it forces a full aggregate over all
products (70k) before pagination. Detail aggregates are FK-bounded and indexed
(`chemical`, `product`, `commodity`, `(year, county)`) so they scale with the
entity's row count, not the table.

The user chose live aggregates for v1. If list pages are slow in production,
the planned fix is a `PesticideUseSummary` table keyed by
`(year, county, chemical, product, commodity)` rebuilt at the end of
`import_pur`, with `stats.py` and the list annotations switched to read from
it. Templates do not change. Nothing in v1 should make that harder.

## Navigation

`page.html`: new "Data Tools" `has-dropdown` navbar item between "Get the App!"
and "Resources", containing "Pesticides Explorer" (`fa-regular fa-fw fa-flask`).
Footer: "Pesticides Explorer" added to the Resources column. Reverse with
`{% url 'pesticides:home' %}`.

## Templates and design

Bulma 0.9 components already used on the site (`section`, `container`,
`columns`, `table is-striped is-hoverable`, `tag`, `breadcrumb`, `pagination`,
`level` for stat rows, `card` for landing cards). No new CSS framework or JS
dependency. Any explorer-specific styles go in the existing `style.css` source
under a `.pesticides` body-class scope. The `frontend-design` skill is applied
during the template pass.

Every number is formatted with `intcomma` and floats rounded to whole pounds
(`floatformat:0`). Dates use the site's `America/Los_Angeles` timezone.

## Error handling

- Bad sqid → 404 via the standard `404.html`.
- Empty database (no `PesticideUse` rows) → landing page and lists render with
  zeros and empty states; `latest_year()` returns `None` and annotations that
  depend on it are skipped, so the pages never 500 on a fresh environment.
- Invalid filter values (e.g. unknown `iarc_group`) are ignored by the form's
  `ChoiceField` validation and the summary sentence omits them.
- Unknown `sort` → default sort.
- `page` out of range → last page (Django `Paginator` behavior via vanilla).

## Testing

Fixture `fixtures/pesticides-explorer.yaml`: 2 counties (each with a simple
square boundary so the map renders), 3 chemicals (one
Group 1 + carcinogen, one TAC-only, one unclassified), 3 products (one
fumigant + restricted), 3 commodities, ~12 `PesticideUse` rows across 2022 and
2023 spanning both counties, 3 notices (one past, two upcoming in different
counties).

`test_querysets.py`
- `search()` substring hit, full-text hit, no match, exact-name-first ordering,
  CAS / reg number / site code hits.

`test_stats.py`
- `latest_year()` value and caching; `None` on empty DB.
- `by_year`, `by_county`, `top_related` totals match fixture arithmetic.
- `upcoming_notices` excludes past notices.
- `landing_stats()` values and that the second call hits cache.

`test_views.py`
- Each list: 200 unfiltered, each filter narrows correctly, categories OR,
  invalid sort falls back, valid sort orders, search ranks, pagination params
  preserved in links, annotations correct, empty DB renders.
- Each detail: 200 with slug, 200 and 301 for bare sqid, 404 bad sqid,
  badges present/absent per fixture, by-year and by-county numbers in the
  response, related entities ordered by lbs, notices split, API links present,
  `assertNumQueries` ceiling (target ≤ 15 per detail page).
- Home: 200, stats and leaderboards, renders on empty DB.
- `get_absolute_url()` for all three models.
- Navbar contains the Data Tools link (one assertion on the home page).

All tests use `django.test.TestCase`, Django fixtures, and plain `assert`.

## Implementation order

1. Convert `tests.py` → `tests/` package; add fixture.
2. `get_absolute_url()` + classification properties + `.search()` (TDD).
3. `stats.py` helpers (TDD).
4. URLs, `base.html`, list views + templates (TDD).
5. Detail views + templates (TDD).
6. Landing page + caching (TDD).
7. Navigation.
8. Template/design pass with `frontend-design`; browser check against the
   local dataset.
9. Full pesticides test run, then full suite before PR.
