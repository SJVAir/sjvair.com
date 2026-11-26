# Location groups and valley-wide locations

Two additive API changes for the data dashboard: location types carry a group in
`regions/meta/`, and `pesticides/locations/` answers for the whole valley when no
area is given.

## Why

The dashboard shows schools and child care as two sections ("Schools": public and
private school; "Child care") and takes types, labels and groupings only from
metadata. `regions/meta/` `location_types` has no grouping today. The dashboard's Map
with no place selected loads every location in one call, and it has no valley region
or bbox to send without hardcoding coverage; `pesticides/locations/` with no area is a
400 today.

## Goals / non-goals

- Goal: a permanent group key on each location type, and the groups' labels and order.
- Goal: `pesticides/locations/` with no area and no bbox returns every current
  location; `type` and `county` still filter.
- Non-goal: changing any existing key or value in `regions/meta/`, or any response to
  a request that works today. The Pesticides explorer's bbox requests must come back
  byte-for-byte the same.
- Non-goal: the one location with no county (it appears unfiltered, and no `county=`
  matches it).

## Approaches

- **Groups.** (a) `Location.Group` `TextChoices` plus `TYPE_GROUPS` in
  `camp/apps/regions/models.py`, served as `location_groups` and a `group` per type,
  matching `Monitor.GradeGroup` / `monitor_groups` (chosen: one pattern for clients,
  grouping lives on the model). (b) A mapping in the endpoint only: rejected, the
  grouping is a property of the type. (c) Nested types under groups: rejected, it
  would change `location_types`' shape.
- **Valley-wide.** (a) No area params and no bbox means the valley (chosen: matches
  `pesticides/place/`, where no place is the valley). (b) An explicit `all=1` flag:
  rejected, an extra parameter for the only case that is a 400 today.

## Design

- `Location.Group`: `school` ("Schools"), `child_care` ("Child care"), translated;
  keys permanent; order is the enum order. `Location.TYPE_GROUPS`: `public_school`
  and `private_school` → `school`, `child_care` → `child_care`.
- `regions/meta/`: new top-level `location_groups`:
  `{school: {key, label, order: 0}, child_care: {key, label, order: 1}}`; each
  `location_types` row gains `group`. `regions/meta/` isn't response-cached (only the
  per-type counts are, under `META_COUNT_CACHE_KEY`), so no cache change.
- `pesticides/locations/`: when neither `region` nor `lat`/`lng` nor a non-blank
  `bbox` is given, no spatial filter is applied. Rows, ordering, `type`/`county`
  handling and caching (`CachedEndpointMixin`, 24 h, `cache_key_version` 3) are
  unchanged; the shape doesn't change, so no version bump. Size on the local stack:
  2,782 rows, 1.5 MB uncompressed, ~195 KB gzipped (GZipMiddleware is on), ~0.8 s
  uncached.
- Explorer pin: capture an explorer-style bbox response from the base code, assert it
  byte-for-byte after the change, and prove the pin fails when the base file is
  restored with a deliberate change.
- `CLAUDE.md`: document both next to the existing `regions/meta/` and location
  entries; fix the doubled "the" in "Bulk monitor type".
- Production: no migration, cache step or backfill.

## Left to the builder

Test names and placement, exact `CLAUDE.md` wording, and docstring updates.
