# Location name search ("Pick my school")

Release 1, step 3, second batch, spec 3 (sjvair.com + sdk-js). Drafted 2026-11-04.

Earlier work: first batch (#293, `2026-10-22-metadata-enablers-design.md`: location codes and
retirement, `regions/locations/`), spec 1 (#300) and spec 2 (#301, sdk-js #38, @sjvair/sdk
4.8.0-beta.5). The dashboard's requirements live in data-dashboard `ARCHITECTURE.md` →
"Widget data selection (partial datasets)" → "Schools and child care are places", and
"Saving & sharing documents" → "Stable ids and retirement".

## Why

The dashboard's shared place picker (built in its step 4) lets someone pick a school or
child-care site as a place, next to monitors and regions. The server holds those sites
(`regions.Location`: public schools, private schools, child care; about 2,800 rows locally)
and can resolve one by code (`regions/locations/?source=&external_id=`), but it has no way
to find one by name. The only location listing, `pesticides/locations/`, is a map layer
(bbox, region or radius) under the pesticides namespace, and the SDK doesn't wrap it.

**The moment this serves (the user, 2026-11-04):** a parent types part of their kid's school
name into the picker and picks it from the list.

## Goals

- A name search for schools and child-care sites that finds a school from part of its name
  and tolerates small typos ("linc", "Linclon", "Rosevelt" all find the school).
- Results ordered so a parent finds theirs among same-named schools (13 "Lincoln
  Elementary" rows locally): **best name match first, then alphabetical by city** (the
  user, 2026-11-04).
- Fast enough for search-as-you-type: the picker fires a request about every 250 ms of
  typing, from 2 characters, alongside its monitor and region searches.
- Each result carries everything the picker needs to show and store it without a second
  request.
- sdk-js wrappers for the new search and for `pesticides/locations/`.

## Non-goals

- A new resolve-by-code endpoint. Saved documents hold `{ source, code }` and resolve
  through the existing `regions/locations/?source=&external_id=` (comma list, up to the
  existing lookup limit) and sdk-js `getLocationsByCode` (the coordinator, 2026-11-04).
- Searching monitors or regions here. The picker runs those searches itself, in parallel.
- Tidying names. The state's child-care list stores names and cities in capitals, some cut
  off (`BCSD/ROOSEVELT ELEMENTARY PRE-KINDERGAR`). They are shown as published (the user,
  2026-11-04): a rule-based tidy would get acronyms and names like McKinley wrong, which
  looks worse than the state's own capitals. Recorded in DEFERRED.md.
- Accent-insensitive matching. No local name has a non-ASCII character today.
- Production data checks (the user's call, 2026-10-20).
- The SDK quick batch, the hardcoded-value cleanup and pesticide metadata (separate items).

## Anti-goals

- Retired sites in search results. A closed school must not be offered for new picks. (It
  still resolves by code, flagged `retired`, so saved dashboards keep working.)
- A child-care center showing once per state license. The state licenses a center's day
  care and school-age rooms separately; to a parent it is one place.
- Results that differ between environments for the same data (ties must break on stable
  values, not database ids).
- A search slow enough that the picker's location results arrive well after its monitor
  and region results.

## Part 1: `GET /api/2.0/regions/locations/search/`

It goes beside the by-code lookup, outside `pesticides/`, since schools matter for air
quality too (decided here; ARCHITECTURE asked for "outside the `pesticides/` namespace").

### Parameters

| Param | Meaning |
|---|---|
| `q` | The typed text. Stripped. Fewer than 2 characters → `{"data": [], "more": false}` (200). Over 100 characters → 400. |
| `type` | Optional comma list of `public_school`, `private_school`, `child_care`. Default: all three. An unknown value → 400 naming it. |
| `region_type`, `region` | Optional, together: a region by code (the same pair the heat and forecast place endpoints take). Only types a location links to directly: `county`, `city`, `cdp`, `zipcode`, `school_district`. Another type → 400; one without the other → 400; an unknown code → 404. A retired region still filters. |

`region_type=city` and `region_type=cdp` both filter on the location's `city` link (it holds
either). The filter is a plain foreign-key match, so it costs nothing extra. Spatial filters
(tracts, air districts, a buffer) are left out: no caller needs them yet, and
`pesticides/locations/?region=` already does spatial.

### Matching

A row matches when its name contains `q` (case-insensitive), or its trigram word similarity
to `q` is at least 0.3 (`TrigramWordSimilarity`, as `Region.objects.search_regions` uses).
The second rule catches typos; the first catches partial words the trigram score is too low
for ("el", "linc").

**The town can be typed too** (the user, 2026-11-04). Same-named schools (13 "Lincoln
Elementary" rows) can't be told apart by typing more of the name, and parents know their
town. When `q` has two or more words, it is also tried as a name part plus a town part: the
town part is the last one or more words, or the first one or more words ("lincoln visalia",
"lincoln elem visalia", "visalia lincoln"). A split matches a row when the town part is a
case-insensitive prefix of the row's city (the linked city/CDP region's name, falling back
to `city_name`) and the name part matches the name by the rules above. Every split is tried;
a row matches if any split (or the whole of `q`) does.

Only current rows (`Location.objects`), grouped with `one_per_place()`, so a child-care
center's several licenses are one result, represented by its lowest code (stable across
environments).

### Ordering

0. **Town matched**, first: a row matched through a name + town split ranks above rows
   matched on the name alone, since the parent narrowed it on purpose.
1. **Match tier**, best first: the name starts with the name text; then a word in the name
   starts with it (after a space, `/`, `-` or `(`); then any other match. The name text is
   the whole of `q`, or the split's name part for a town-matched row (the best split's).
2. **Similarity**, highest first (`TrigramWordSimilarity` of the same name text).
3. **City**, alphabetical, ignoring case: the linked city/CDP region's name, falling back to
   the row's own `city_name`.
4. Name (ignoring case), then `source`, then `external_id`: a stable final tie-break.

Prototyped on local data (2026-11-04): "linc" → the Lincoln Elementaries by city; "Linclon"
and "Rosevelt" find Lincoln and Roosevelt schools; "fresno high" → Fresno High first; about
10 ms a query once warm.

### Response

```json
{
  "data": [
    {
      "id": "…",
      "source": "cde-public",
      "external_id": "10621661234567",
      "aliases": [],
      "type": "public_school",
      "name": "Lincoln Elementary",
      "address": "1100 E Voorman Ave",
      "city_name": "Fresno",
      "zip": "93704",
      "point": {"lat": 36.79, "lng": -119.80},
      "regions": {
        "county": {"type": "county", "external_id": "06019", "name": "Fresno County"},
        "city": {"type": "city", "external_id": "0627000", "name": "Fresno"},
        "zipcode": {"type": "zipcode", "external_id": "93704", "name": "93704"},
        "school_district": {"type": "school_district", "external_id": "…", "name": "Fresno Unified"}
      },
      "retired": null
    }
  ],
  "more": true
}
```

- Each row is exactly the `regions/locations/` row (`LocationSerializer`), so the picker and
  a reopened dashboard see the same shape. `retired` is always `null` here.
- Normally **10** rows, stretched to at most **15** when names tie (the user, 2026-11-04):
  if the rows after the 10th have the same name as the 10th (ignoring case and surrounding
  spaces), they are included too, up to 15 in all. So "lincoln elementary" returns all 13
  Lincolns. Fetch 16 rows to decide.
- `more` is true when any matching row is left out: the picker shows "keep typing to narrow
  it down" (now workable, since the town can be typed). No total count (a second query) and
  no paging.

### Caching

`Cache-Control: public, max-age=3600` on a 200, so the browser reuses an answer when someone
backspaces or retypes. No server-side cache: almost every keystroke is a new key, so the hit
rate would be low, and the query is fast. Errors are `no-cache`. A re-import or retirement
shows up within the hour.

### Performance

The table is small (about 2,800 rows locally; production should be similar since both import
the same state lists for the valley), so a sequential scan with trigram scoring is expected
to stay around 10 ms with no new index. The builder confirms on the real local database with
`EXPLAIN ANALYZE` (warm and cold, short and long queries, with and without `type` and
`region`), including the `one_per_place()` subquery. Add a `gin_trgm_ops` index on `name`
only if the plan or timing says it's needed.

## Part 2: region names on location rows

`LocationSerializer`'s `regions` refs gain `name`: `{type, external_id, name}`. The picker
shows city and county names without another request. This also changes
`regions/locations/` (an added field; nothing removed). The serializer already
`select_related`s the four regions, so it costs no query.

## Part 3: location type labels in `regions/meta/`

The picker shows each row's type, and labels come from metadata, not client strings.
`regions/meta/` gains `location_types`, keyed by type:

```json
"location_types": {
  "public_school": {"type": "public_school", "label": "Public school", "source": "cde-public"},
  "private_school": {"type": "private_school", "label": "Private school", "source": "cde-private"},
  "child_care": {"type": "child_care", "label": "Child care", "source": "cdss-ccl"}
}
```

Labels come from `Location.SHORT_TYPES` (the short, sentence-case labels the explorer already
shows). `source` is the code source rows of that type use, so a client knows which source
pairs with a type. The builder confirms each type maps to exactly one source in the import
code; if not, `source` becomes a list.

## Part 4: sdk-js

Branch from `origin/release/4.8.0`, PR into it. Search first for existing wrappers (by URL
string and name); none exists for either endpoint today (checked 2026-11-04).

- **`searchLocations({ q, type?, region?, ...requestOptions })`** in
  `lib/regions/search_locations.ts`, exported from `@sjvair/sdk/regions`. `type` is a
  `LocationType` or an array of them (sent as a comma list); `region` is
  `{ type, external_id }` (sent as `region_type` and `region`). Returns
  `{ results: Location[], more: boolean }`. Accepts the SDK's usual request options,
  including an `AbortSignal`, as `searchRegionPlaces` does. Returns the empty result
  without a request for `q` under 2 characters, matching the server.
- **`locationSchema`**: region refs gain `name`; `type` becomes a `LocationType` enum
  (`public_school`, `private_school`, `child_care`).
- **`regionsMetaSchema`** gains `location_types`.
- **`getPesticideLocations(params)`** in `lib/pesticides/`, wrapping `pesticides/locations/`:
  `bbox`, or `region` (a sqid) with optional `buffer` (0, 1, 3, 5), or `lat`, `lng` and
  `radius` (miles, up to 10); plus `type` and `county` (a county slug). Returns the GeoJSON
  FeatureCollection, with the properties the endpoint sends (`id`, `name`, `type`,
  `type_label`, `address`, `city`, `school_district`, `school_district_id`,
  `school_district_url`, `grade_span`, `enrollment`, `capacity`). Its docs say the radius
  form puts coordinates in the URL, so it is for public points (a school), never a
  person's own location.
- Tick both URLs in `api-urls.md`. Tests run against the local API, following the existing
  `lookup_by_code_test.ts` pattern.

No beta is cut without the user's yes.

## Testing (sjvair.com)

Django `TestCase` in `camp/api/v2/regions/tests.py` (or a new test module beside it), with
fixtures or rows built in `setUp`:

- prefix, word-start and substring matches, a typo match, and the tier order between them;
- same-named schools in different cities come back ordered by city, ignoring case;
- a retired location is never returned; a child-care center with two licenses is one row,
  represented by its lowest code;
- `type` filtering (single, list, unknown → 400); `region_type`/`region` filtering for each
  linked type, a retired region, an unlinked type (400), half a pair (400), an unknown
  code (404);
- `q` under 2 characters → empty 200; over 100 → 400;
- town matching: "lincoln visalia", "visalia lincoln" and a partial town ("lincoln vis")
  find the Visalia school and rank it first; a town word alone doesn't make a non-matching
  name match; a one-word `q` never splits;
- the 10-row cap, the stretch to 15 on a name tie at the 10th row (and not past 15), and
  `more` in each case;
- the `Cache-Control` header on 200s and errors;
- `regions/locations/` region refs carry `name`; `regions/meta/` lists `location_types`.

## Docs

- sjvair.com `CLAUDE.md` → "Region and Location Codes" or "Metadata Endpoints": one bullet
  on the search endpoint and `location_types`.
- data-dashboard (own worktree, pushed to `main`, per its docs rules): the step 3 location
  item in TODO.md, ARCHITECTURE.md → "Schools and child care are places" (what was built),
  and a DEFERRED.md entry for tidying child-care names (why: rule-based casing gets
  acronyms and names wrong; revisit if parents or partners find the capitals confusing in
  the picker).

## Left to the builder

- How the word-start tier is expressed (escaped regex or several `ILIKE`s), as long as user
  input can never act as a pattern.
- How the splits are expressed in SQL (one query with OR'd conditions and `Case`
  annotations is expected; a query has few words, so few splits). The `EXPLAIN ANALYZE`
  check above covers multi-word queries.
- `searchLocations` reads `more` beside `data`, so it uses the SDK's `apiCall` rather than
  `jsonCall` (which keeps only `data`).
- Whether the search lives on `LocationQuerySet` (e.g. `search(q)`) or in the endpoint; a
  queryset method is preferred so it can be reused.
- Test module layout.
