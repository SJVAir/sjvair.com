# Region display names (`name_template`)

Release 1, step 3 follow-up (sjvair.com + sdk-js). Drafted 2026-11-05. Asked for by step 4
spec 2 (the dashboard's shared place picker). The SDK half is in sdk-js
`docs/superpowers/specs/2026-11-05-region-name-templates-design.md`.

## Why

The user decided (2026-11-05, step 4 spec 2) that a ZIP place reads "ZIP 93702" everywhere in
the SJVAir Dashboard (widget titles, tables, CSV, the picker), and that the wording comes from
server metadata, not from the client. Today a widget title reads "PM2.5 · 93702".

Some region names don't stand on their own (checked on the local stack, 2026-11-05):

- **Bare codes:** `zipcode` (237 regions, e.g. "93610") and `tract` (1,161, e.g.
  "06019000100").
- **Names shared across types:** 45 names are both a `city` and an `urban_area`, 5 are both a
  `cdp` and an `urban_area`, "Shafter" and "Stockton" are each an `ab617` community, a city
  and an urban area, and "Winton" is both a `cdp` and a `school_district`.

The problem shows after the picker: a widget title, CSV or shared dashboard that says
"Arvin" can't tell the reader it means the urban area, even when no city Arvin sits beside
it. (The picker itself can already tell same-named results apart: each row has `type`, and
`regions/meta/` has its label.)

## Decisions (the user, 2026-11-05)

- **Which types:** `zipcode`, `tract`, `urban_area` and `ab617`. Every other type keeps its
  plain `name`. A bare town name usually means the city, so the less common types say what
  they are; cities and CDPs stay plain.
- **Shape:** a per-type wording pattern in `regions/meta/`, not a field on every region row.
- **Tract wording:** the full code, "Census Tract 06019000100" (matches how CalEnviroScreen
  lists tracts). The Census Bureau's short form with the county ("Census Tract 1, Fresno
  County") is deferred: a pattern around `{name}` can't produce it, and the short number alone
  is ambiguous (274 short tract numbers repeat across the eight counties locally). Recorded in
  data-dashboard `DEFERRED.md`.

## The contract

Each entry of `regions/meta/` `types` gets one new key, `name_template`: a string holding the
literal placeholder `{name}` exactly once, or `null` when the type shows its plain name.

| type         | `name_template`             | example                            |
| ------------ | --------------------------- | ---------------------------------- |
| `zipcode`    | `"ZIP {name}"`              | ZIP 93702                          |
| `tract`      | `"Census Tract {name}"`     | Census Tract 06019000100           |
| `urban_area` | `"{name} Urban Area"`       | Arvin Urban Area                   |
| `ab617`      | `"{name} AB 617 Community"` | Arvin, Lamont AB 617 Community     |
| every other  | `null`                      | Fresno County, Arvin, Winton, ...  |

A client shows a region as the template with `{name}` replaced by the region's `name`, or as
`name` when the template is `null`. `{name}` is the only placeholder; nothing else in a
template is special.

Unchanged: region `name`, slug, `external_id`, ids, and every region row on every endpoint
(lists, search, lookup, by-code, GeoJSON, location rows' region refs). Retired regions use
their type's template like any other.

## Server changes (sjvair.com)

- `Region.TYPE_NAME_TEMPLATES` in `camp/apps/regions/models.py`, next to
  `TYPE_LABELS_PLURAL`: a dict holding only the four types above, each value wrapped in
  `gettext_lazy` like the labels (translating them is out of scope). Types not in the dict
  serve `null`.
- `RegionMetaEndpoint.get_types` (`camp/api/v2/regions/endpoints.py`) adds
  `'name_template': Region.TYPE_NAME_TEMPLATES.get(region_type)`, stringified when present.
- Tests in `camp/api/v2/regions/tests.py`:
  - `test_type_fields` (the full county dict) gains `'name_template': None`.
  - A new test pins the whole `{type: name_template}` map: the four templates above, `None`
    for every other type.
  - A new test checks every non-null template contains `{name}` exactly once.
- `CLAUDE.md` → "Metadata Endpoints" → **Regions**: add `name_template` to the list of keys
  `regions/meta/` types carry, with one line on its meaning and the fallback.

No migration, no data change, no new query: the templates are constants. Performance is
unaffected.

## SDK (sdk-js), summarized

`regionTypeMetaSchema` gains `name_template: string | null`, and a helper
`regionDisplayName(region: { type, name }, meta: Pick<RegionsMetaData, "types">): string`
returns the filled template, or `name` when the template is `null` or the type is unknown.
Every region shape the SDK returns carries `type` and `name`, location rows' region refs
included. A `CHANGELOG.md`
line goes under 5.0.0's betas. Details in the sdk-js spec. Publishing the beta (likely
`5.0.0-beta.4`, which also ships the merged sdk-js #48) needs the user's explicit yes.

## Non-goals

- Changing any region's `name`, slug, code or id.
- A `display_name` on region rows.
- The Census Bureau's short tract name (deferred, above).
- monitor-map and mobile (they can adopt the helper later); sjvair.com's own templates and
  admin.
- Translating the templates.
- Dashboard changes: data-dashboard-13 (step 4) adopts the helper in the picker and widgets.

## Rollout and coordination

- sjvair.com: branch `feature/region-name-templates` from `origin/develop`, PR into `develop`.
- sdk-js: branch `feature/region-name-templates` from `origin/release/5.0.0`, PR into it. The
  SDK release goes live with sjvair.com `develop` (no fallback for servers without the key).
- Nothing touches production; there's no deploy step beyond the normal release.
- Once the spec is approved, send the final shape (key name, tract wording, helper name and
  signature) to the coordinator (data-dashboard-b7) and data-dashboard-13; the beta version
  follows when it's published.
