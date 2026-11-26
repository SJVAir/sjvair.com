# Whole-type scope on the bulk region summaries

## Why

A map can fill every region of one type (counties, cities, ZIPs, school districts,
CDPs, census tracts, ...) by each day's level. The bulk region summary endpoints
require each region as a repeated `region=<sqid>`, which breaks for a whole type:
tracts (978 current) exceed Django's `DATA_UPLOAD_MAX_NUMBER_FIELDS` (1000), a 400 in
production, with a ~16 K-character URL; MTRS (27,917) is a 414. The server should
accept the type itself.

## What changes

Two endpoints, both scoped by `BulkRegionScopeForm`:

- `GET /api/2.0/regions/<entry_type>/summaries/<resolution>/` (`BulkRegionSummaryList`;
  every resolution, `start`/`end` still required)
- `GET /api/2.0/regions/<entry_type>/summaries/daily/open/` (`BulkRegionOpenDays`)

New parameter `type`: one region type value (`Region.Type`, e.g. `tract`, `zipcode`).

- Exactly one of `type` or `region` is required. Both, or neither, is a 400 with form
  errors. `type` takes a single value; a repeated `type` uses the last one, as
  Django's `QueryDict.get` does (decided: one type per request).
- `type=land_use` is a 400 (land use isn't referenceable, has no stable codes and no
  summaries). Any other unknown value is a 400 (`invalid_choice`). `mtrs` is allowed.
- The scope is the type's **current** regions: `Region.objects` (not retired),
  `.exclude(boundary=None)` and `.current_vintage()` (tracts on `TRACT_VINTAGE` only),
  the same set `/regions/geojson/` draws. A type with no current regions (or none with rows) is an
  empty 200.
- `region=` lists are unchanged: explicit ids still resolve through `Region.all_objects`,
  retired and old-vintage regions included.
- Response shapes, pagination (summary list: by row, `page_size` 168, the cross-page
  merge contract; open days: by region, 100 per page), cache headers and ETags are
  unchanged.

The monitor bulk endpoints (`BulkMonitorSummaryList`, `BulkMonitorOpenDays`) are not
touched: they have no required id list. Unscoped they return every published monitor;
`region` and `bbox` only narrow it.

## Approaches

1. **Sub-select (picked).** The form cleans `type` into the queryset
   `Region.objects.current_vintage().filter(type=...)`; the views filter
   `region__in=` / `pk__in=` with it, so the database selects the regions inside the
   same statement. Scales to MTRS without a 28 K-value `IN` list.
2. Resolve ids in Python, then filter by the id list: an extra query and a huge `IN`
   list for MTRS. Rejected.
3. Filter on joined region columns (`region__type`, `region__retired_at`, the boundary
   version): the same plan for type and retirement, but the vintage rule would be
   re-stated instead of reusing `current_vintage()`. Rejected.

## Builder's calls

- The cleaned scope is a single `regions` value (list or queryset) the views use the
  same way; how the form names it is the builder's.
- OpenAPI: declare `type` on `BulkRegionSummaryFilter` as a no-op filter like `region`,
  and give `BulkRegionOpenDays` an equivalent filter class so its schema shows `region`
  and `type`.
- Performance: check `EXPLAIN` for a whole-type daily and open-days query on the local
  stack (expect the `(region, entry_type, resolution, timestamp)` unique index and a
  semi-join on the region sub-select).
- Tests: `type` alone, the 400s (both, neither, land use, unknown), retired and
  old-vintage tracts left out, `region` lists unchanged, open days with `type`, and
  a scope of more than 1,000 regions with no id list.
- CLAUDE.md: a line under Metadata Endpoints.

## Not in scope

- Old-vintage tracts still get summaries (locally 380 tracts have daily rows, 300 of
  them current), and `/regions/?type=tract` lists all tracts. Reported, not changed.
- No migration, no caching changes, no monitor-side scope, no hour filter.
