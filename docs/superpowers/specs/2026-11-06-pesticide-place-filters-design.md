# Pesticide place filters and metadata

Date: 2026-11-06. The server side of data-dashboard spec 3b's pesticide layer. The scope is
items 1–5 of the explorer comparison, approved by the user on 2026-11-06 and relayed by the
coordinator. The research behind it is in the findings file sent to the coordinator. Spec 3b
then asked for three more things (items 6–8 below); item 6, the picker search, is **added
scope**.

## Why

The dashboard's pesticide layer charts monthly and yearly pounds, acres and applications per
place from `pesticides/place/`. People combine filters and save them on the layer. The user's
goal: the dashboard should have at least as many ways to filter the data as the Pesticides
Explorer, without copying it, and without breaking the Pesticides Explorer or the Facility
Emissions Explorer.

Today `place/` falls short in four ways:
- It takes CDPR codes where the dashboard has our ids. A chemical sqid is a 400, and a
  commodity sqid silently matches nothing.
- It has no labels source: the catalog's `meta_url` is empty.
- Its catalog entry lists no applications count, though `place/` already returns one.
- It has no concern/restricted/fumigant narrowing, no product filter, only one category at a
  time, and no "not reported" method.

## Constraint: the explorers stay untouched

**Anti-goal:** a change that alters what either explorer shows.

- The Facility Emissions Explorer doesn't use the pesticide API.
- The Pesticides Explorer's map calls `sections/`, `townships/`, `sections/<id>/`,
  `notices/active|archive/`, `locations/` and `search/`, sending codes (`chem_code`, `prodno`,
  `site_code`). It never calls `place/`, `filters.py`, the list endpoints or the catalog.

So this change may touch only:
- `camp/api/v2/pesticides/endpoints.py`: `PesticidePlaceForm` / `PesticidePlace`, the new
  counting-rule function, and **additive** keys on `EntitySearchBase`'s response (item 6);
- `camp/api/v2/pesticides/urls.py`: the new route;
- a new meta module for `pesticides/meta/` (e.g. `camp/api/v2/pesticides/meta.py`);
- `camp/api/v2/pesticides/serializers.py`: an additive field;
- `camp/api/v2/meta/catalog.py`, its tests and its snapshot;
- `camp/api/v2/pesticides/tests.py` (or new test modules);
- `CLAUDE.md`.

It may *read* explorer helpers (`stats.narrow_rows`, `stats.concern_rows`,
`stats.METHOD_LABELS`, `notes`) but not change them. It must not touch `sections.py`,
`locations.py`, `stats.py`, `places.py`, `views.py` or the templates. `filters.py` (`use/`,
`notice/`, `region/<id>/…`, which are live in production) stays on codes.

## 1. `place/` takes our ids

- `chemical`, `commodity` and the new `product` take the sqid that `pesticides/chemicals/`,
  `commodities/` and `products/` return as `id`. Codes are no longer accepted on `place/`.
- **Why sqid-only, not both:** sqids can be all digits. Locally, 3 chemical sqids and 92
  product sqids are digit-only, and 57 of those product sqids equal some product's `prodno`. A
  digit-only value can't be read as one or the other safely.
- `place/` is on `develop` only, not production, so nothing outside depends on the code form.
- **A value that names nothing is a 400** naming the field, the same as other invalid values
  on `place/` (`no-cache`). This replaces today's silent empty answer for commodities.
- **Two error codes** (spec 3b: widgets save these ids, and the dashboard needs to tell a
  retired id from a typo). The 400 body is the form's usual
  `{"errors": {"<field>": [{"message", "code"}]}}`.
  - `code: "invalid"` for a value that isn't one of our ids: it doesn't decode, or doesn't
    re-encode to itself (sqids has non-canonical spellings).
  - `code: "not_found"` for a well-formed id with no row (deleted or merged).
- **Names for a saved id:** the detail endpoints (`chemicals/<id>/`, `commodities/<id>/`,
  `products/<id>/`) already return `name` (chemicals also `display_name`) by sqid, and a 404
  for a gone id. No change is needed there.
- **Builder's call:** resolve with one indexed lookup per given id (`Model.objects.filter(sqid=…)`
  or django_sqids' decode), then filter the rollup on the FK id. Don't join through the code
  columns.

## 2. `pesticides/meta/`

A `GET` endpoint with no parameters, `public, max-age=86400`. The shape below is *my call*. It
follows the labels-and-keys style of the other domain meta endpoints. Keys are permanent;
labels may change.

```json
{"data": {
  "categories": [{"key": "carcinogen", "label": "Carcinogen", "description": "…", "in_use": true}, …],
  "iarc_groups": [{"key": "2A", "label": "Group 2A", "description": "Probably carcinogenic to humans"}, …],
  "methods": [{"key": "G", "label": "Ground"}, {"key": "A", "label": "Air"},
              {"key": "F", "label": "Field fumigation"}, {"key": "O", "label": "Other"},
              {"key": "none", "label": "Not reported"}],
  "narrows": [{"key": "concern", "label": "Flagged chemicals", "description": "…"}, …],
  "placeholder_chemicals": [{"id": "<sqid>", "name": "UNKNOWN"}, …]
}}
```

- **Categories:** all ten `Chemical.Category` values, in model order.
  - `in_use: false` for the four no import assigns (`biopesticide`, `cholinesterase_inhibitor`,
    `groundwater_contaminant`, `oil`; the explorer's `UNASSIGNED_CATEGORIES` in
    `camp/apps/pesticides/forms.py`). They're listed rather than left out, because `place/` and
    the chemical list still accept them, and metadata is the source of truth. *(My call.)*
  - Read `UNASSIGNED_CATEGORIES` from forms.py rather than copying it, so the two can't drift.
  - Descriptions come from `notes`: `prop65` for carcinogen, reproductive toxin and
    developmental toxin; `carb_tac` for toxic_air_contaminant; the category's own note for the
    rest.
  - The `summary` field is the description; `detail` and `source_url` aren't included. *(My
    call; the dashboard can link out later.)*
- **IARC groups:** the four `Chemical.IARCGroup` values. The model label "Group 2A – Probably
  carcinogenic to humans" splits on the dash into `label` and `description`.
  - **Builder's call:** split it at serialization, or add the parts to the model. Don't change
    the model label: the explorer shows it.
- **Methods:** the explorer's wording, `stats.METHOD_LABELS` in `METHOD_ORDER`, as the user
  chose. The blank method's key is `none`, as in the explorer's forms.
- **Narrows:** `stats.NARROW_CHOICES` labels. Descriptions:
  - concern: what the set is (Prop 65, CARB TAC, California restricted, IARC 1/2A/2B);
  - restricted: CDPR's per-product restricted-material flag;
  - fumigant: the product classification;
  - aerial: `NARROW_HELP`.

  Write the first three as short constants in the meta module, citing the stats definitions.
  Builder's call on wording. Each must say that restricted and fumigant are product
  properties, unlike the `category` filter's same-named chemical categories.
- **Placeholder chemicals:** the `Chemical.PLACEHOLDER_CODES` rows that exist, by sqid and
  name.
- **`methods` are PUR's (use records).** Spray notices name their methods in SprayDays' own
  free text (`'Aircraft'`, …), and this meta doesn't describe them. Say so in the endpoint's
  docstring and in CLAUDE.md. A notice-methods section is deferred until a notices layer is
  scoped. *(My call. Both datasets still point here, as approved, because the categories,
  IARC groups and narrows apply to notices too.)*
- **Catalog:** `meta_url` for `pesticide-use` and `pesticide-notices` points at
  `pesticides/meta/`. The catalog snapshot is regenerated, and its diff must be only these
  changes and the item 3 entry.

## 3. Catalog: applications

Add an `applications` entry type to `pesticide-use`:
`_other('applications', 'Applications', 'applications', ['month', 'year'])`, after
`acres-treated`. Give it `DISPLAY_OVERRIDES['applications'] = (0, 'bar', 0)`, the same as
`pounds-applied` (spec 3b). Without it, it falls through to a 1-decimal line. It's
the `applications` value `place/` already returns. Update the catalog tests that list the
dataset's entry types (`test_catalog.py:99`, `:172`) and the snapshot. Entry-type ids are
permanent.

## 4. More filters on `place/`

All filters combine with AND.

- **`narrow`:** one of `concern`, `restricted`, `fumigant`, `aerial`. It's exclusive, as in
  the explorer. Apply it with `stats.narrow_rows(rows, narrow)`, which works on rollup rows. An
  unknown value is a 400. (The explorer falls back to all use, but the API is strict like its
  other filters.)
- **`product`:** a product sqid (item 1), filtering the rollup's `product` FK.
- **`category`:** several values, repeated (`category=a&category=b`) or comma-separated, kept
  with `categories__overlap`, i.e. OR, as on the explorer's chemicals list. One value behaves
  as today. Each value must be a `Chemical.Category`, and an unknown one is a 400 naming it.
- **`aerial_ground=none`:** the "not reported" method, matching the rollup's blank `method`.
  The existing A/F/G/O values are unchanged.
- **Counting rule** (`places.monthly_use`, unchanged): pick `chemical_scoped` /
  `multi_chemical` from what's filtered.
  - A `chemical` makes it chemical-scoped.
  - Otherwise `category` or `iarc_group` makes it multi-chemical, as today.
  - Otherwise the once-per-record columns are right. This covers product, commodity, method,
    any `narrow`, or nothing.
    - A product- or record-level filter keeps every row of a record, so its designated row
      (one per `(year, county, use_no)` in the rollup's rebuild) is kept too.
    - `narrow=concern` also counts once, as the explorer does. The rebuild designates a
      restricted ingredient first, then any concern ingredient, and the concern set includes
      `california_restricted`. So every record with a concern ingredient has its designated row
      inside the set. (The MAX route would give the same numbers, minus the 27 rows with no
      product, at the cost of raw SQL.)
  - Write this choice as a small function in `endpoints.py` (not `places.py`), with its own
    tests.
- **Server cache key:** the filters are already hashed into it. Normalize `category` (sorted,
  deduplicated) before hashing, so `a,b` and `b,a` share a cache entry.

## 5. Placeholder chemicals

- **They carry no pounds.** The `PLACEHOLDER_CODES` comment says so; locally they have 0 lbs,
  but 389,065 records and 17.6 M acres. So the decision is about **applications and acres**.
- Their records **stay** in `place/`'s applications and acres: they're real applications whose
  active ingredient CDPR doesn't name. [USER DECISION PENDING: confirm]
- `ChemicalSerializer` gains `placeholder` (`chemical.is_placeholder`). It's additive.
  Everything that nests the serializer (lists, details, region summaries) gets it. No explorer
  reads it.
- `pesticides/meta/` lists them too (item 2).

## 6. Picker search (added scope, spec 3b)

The dashboard's chemical, commodity and product pickers need one page of matches. The list
getters fetch every page; `products/?name=a` is 57,434 rows. `pesticides/search/`
(`EntitySearch`) already does this for the explorer's entity picker:
- one page (`limit`, default 10, max 25);
- ranked exact → prefix → rest, then closer match and shorter name;
- only entities with reported use (optionally by `year`, `county`, `narrow`);
- `id` is the sqid.

It changes only by **adding** response keys. The explorer's `entity-picker.js` reads `results`
only, and nothing about which results come back or in what order changes:
- `more`: `true` when matches beyond `limit` were left out. Compute it by fetching `limit + 1`.
- For `type=chemical`, each result gains `placeholder` (bool), so the dashboard can leave
  placeholders out of its picker. They stay in the results, because the explorer's picker
  behavior is unchanged.

The cached-endpoint cache key is unaffected: the parameters are the same. Tests: `more`
true/false at the boundary; `placeholder` on chemical results; the existing `EntitySearchTests`
unchanged.

## Tests

- `place/`:
  - each id filter by sqid;
  - a code given instead of a sqid gives a 400 (shown for chemical and product);
  - an undecodable value and an unknown sqid each give a 400;
  - `narrow` with each value, matching `stats.narrow_rows` on the same rows, plus an unknown
    value giving a 400;
  - `product`;
  - several categories (overlap; repeated and comma forms; order-insensitive cache key) plus an
    unknown category giving a 400;
  - `aerial_ground=none`;
  - the error codes: `invalid` (undecodable, non-canonical) and `not_found` (deleted row);
  - the counting-rule function for each filter combination;
  - placeholder records counted in applications and acres (fixture rows with
    `records`/`acres_once` on a placeholder chemical).
- `search/`: `more` and `placeholder`, as in item 6.
- `pesticides/meta/`: its shape; all ten categories with `in_use`; the method labels and order;
  placeholder chemicals; cache header.
- Catalog: the `meta_url`s, the `applications` entry type, and a snapshot diff of exactly
  those.
- Chemicals serializer: `placeholder` true/false.
- **Explorer guard:** the full suite stays green, including the explorer's view and map-API
  tests and `EntitySearchTests`. `git diff --stat` touches only the allowed files above.

## Docs

Update `CLAUDE.md` in the same PR:
- **"Pesticide place" bullet:** the filters now take sqids (`chemical`, `commodity`,
  `product`) with `invalid`/`not_found` codes; add `narrow`, repeatable/comma `category`,
  `aerial_ground=none`, the counting-rule additions, and that placeholder records count in
  applications and acres.
- **"Domain meta endpoints" bullet:** add `pesticides/meta/` and its shape.

## SDK follow-up (separate sdk-js spec and PR into `release/5.0.0`)

Signature changes, for spec 3b and beta.6:
- `PesticidesForPlaceFilters`:
  - `chemical?: string`, `commodity?: string`, `product?: string` (our ids, from the list
    getters);
  - `category?: string | string[]` (sent repeated, or comma-joined to match sdk-js's existing
    list style; settled in that spec);
  - `narrow?: 'concern' | 'restricted' | 'fumigant' | 'aerial'`;
  - `aerial_ground` gains `'none'`.
- A `getPesticidesMeta()` getter and its types (`methods` documented as PUR's).
- A one-page search getter over `pesticides/search/`, e.g.
  `searchPesticides(type, q, {limit, year, county, narrow})` → `{results: [{id, name, detail,
  placeholder?}], more}`. The name is settled in the sdk-js spec.
- The 400 error codes (`invalid` / `not_found`) on the place filters, surfaced the way sdk-js
  already surfaces field errors.
- `Chemical` gains `placeholder: boolean`.
- The catalog's types are unchanged (it's data).

Publishing 5.0.0-beta.6 needs the user's own yes.

## Deferred (to data-dashboard `DEFERRED.md`, in the same docs push as this spec)

- **Buffer and radius on `place/`:** the explorer's region pages take a 0/1/3/5 mi buffer, and
  near-me takes a point plus 1/3/5 mi. **Revisit when** the dashboard wants "around this place"
  or "near me".
- **A per-place breakdown endpoint:** top chemicals, products and commodities, by method,
  biggest movers. **Revisit when** the dashboard designs a "what's used here" view.
- **Schools' 3×3 section block:** `place/` can't address a location today, and the shared
  place resolver would need a location form. **Revisit when** the dashboard adds school-level
  pesticide answers.

## Non-goals

- Changing `filters.py` endpoints, the explorer, or its map APIs.
- Fumigation technique or day-level dates (the rollup has neither).
- Excluding placeholder pounds.
