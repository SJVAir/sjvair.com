# Monitor groups and pollutant help text in `monitors/meta/`

Date: 2026-11-12. Small change.

## Why

map-sdk part 5's shared options toolbar (`@sjvair/map-sdk` `0.1.0-beta.13`) shows group headings
in the Monitors row and a help line in the Pollutant row. monitor-map hardcodes both today
(`MonitorsMenu.svelte`, `PollutantMenu.svelte`). The data dashboard can't: metadata is its source of
truth, and map-sdk's `monitorsOptions` reads both straight from the meta object the host passes.
So `GET /api/2.0/monitors/meta/` has to carry them.

## Goals

- Each monitor type says which group it belongs to, with a stable id and a display label.
- Each air-quality pollutant has a short, plain help line.

## Non-goals

- Renaming bam1022 to "SJVAir" (held; see Deferred).
- Help text for weather entry types or `particulates`.
- Translating monitor type labels (`Meta.verbose_name` stays a plain string).
- Any v1 API change.

## Response shape

Additions only; nothing existing changes.

```json
{
  "data": {
    "monitor_groups": {
      "reference": {"key": "reference", "label": "Reference-grade", "order": 0},
      "low-cost":  {"key": "low-cost",  "label": "Low-cost sensors", "order": 1}
    },
    "monitors": {
      "airnow": {"label": "AirNow", "type": "airnow", "group": "reference", "...": "..."}
    },
    "entries": {
      "pm25": {"label": "PM2.5", "description": "Fine particles from smoke, dust, and vehicle exhaust.", "...": "..."},
      "temperature": {"label": "Temperature", "description": null, "...": "..."}
    }
  }
}
```

- `monitor_groups`: keyed by group id, each `{key, label, order}`. Same pattern as `stages` and
  `processors`. Clients sort headings by `order`, not by JSON key order.
- `monitors[type].group`: a `monitor_groups` key, or `null` for a type with no `GRADE`.
- `entries[type].description`: a string, or `null`.
- Group ids `reference` and `low-cost` are permanent (clients key on them); labels may change.

### Groups

| Group | Types |
|---|---|
| `reference` (Reference-grade) | airnow, aqlite, aqview, bam1022 |
| `low-cost` (Low-cost sensors) | airgradient, purpleair, vozbox |

Taken from monitor-map's `REFERENCE_GRADE_TYPES` and `LOW_COST_TYPES`; these are exactly the
types whose `GRADE` is `fem` and `lcs` today.

### Help text (wording approved by the user)

| Entry type | Label | `description` |
|---|---|---|
| `pm25` | PM2.5 | Fine particles from smoke, dust, and vehicle exhaust. |
| `o3` | Ozone | Ground-level gas that forms in sunlight on hot days. |
| `pm10` | PM1.0 | The smallest particles, mostly from smoke and vehicle exhaust. |
| `pm100` | PM10.0 | Coarser particles from dust, farming, and road traffic. |
| `no2` | Nitrogen Dioxide | Gas from vehicle and engine exhaust, highest near busy roads. |
| `so2` | Sulfur Dioxide | Gas from burning fuels that contain sulfur, mostly from industry. |
| `co` | Carbon Monoxide | Colorless, odorless gas from vehicle exhaust and burning fuel. |
| `co2` | Carbon Dioxide | Gas from breathing and burning fuel; high levels indoors mean a room needs fresh air. |

Every other entry type (weather, `particulates`) is `null`.

## Where the values live

- `Monitor.GradeGroup` choices class (`models.TextChoices`, `gettext_lazy` labels), nested in `Monitor`
  next to `Monitor.Grade` (not `Group`: the app already has a `Group` model); `order` is the
  member's declaration index.
- The group is derived from the existing `GRADE`, not a new per-type attribute (the user,
  2026-11-12): `FEM` and `FRM` are `reference`, `LCS` is `low-cost`. `GRADE` already matches
  monitor-map's lists exactly, and a second attribute could disagree with it. A type whose grade
  maps to no group (CIMIS: `None`) has `group: null`; CIMIS isn't in the meta anyway.
- `description = _('...')` class attribute on the 8 entry models, next to `label`;
  `BaseEntry.description = None`.
- The endpoint serializes lazy strings with `str()`, as `get_stages` does.

## Approaches considered

- **A. `group` id per monitor type + top-level `monitor_groups` map** (picked). Matches `stages` and
  `processors`; each label in one place; explicit `order` for headings.
- B. Inline `group: {key, label}` per type. Repeats the label and has nowhere for heading order.
- C. A list of groups naming their types. Order built in, but each type's group is stated twice
  (list and model) and they can disagree.

Where the group comes from: a separate `group` attribute per type was dropped for deriving it
from `GRADE`, which already carries the same split. If a group that doesn't follow certification is
ever wanted, add an override then.

Help-text scope: the user picked all 8 air-quality pollutants over PM2.5 and ozone only (publishing
a new pollutant stays a fixture-only change, and dashboard widgets can reuse the text) and over all
24 entry types (weather isn't on the map).

## Tests

- Meta response has `monitor_groups` with both groups, keys, labels and orders as above.
- Every enabled monitor type that has a `GRADE` has a `group` that is a `monitor_groups` key
  (fails when a new type is enabled with a grade that maps to no group); the 7 current types map
  as in the table.
- A type with no `GRADE` stays in the meta with `group: null` (the user, 2026-11-12; map-sdk lists
  it flat with no heading). Possible when `MONITOR_ENABLED_TYPES` is empty, which enables every
  type, CIMIS included. Not left out: the meta's other fields still serve it.
- The grade mapping: FEM and FRM give `reference`, LCS gives `low-cost`, `None` gives `None`.
- The 8 pollutants' `description` match the table; every other entry type is `null`.

## Deferred

- **bam1022 shown as "SJVAir".** Renaming `verbose_name` would also change the admin's monitor-type
  choices (which should keep saying "BAM 1022": SJVAir may run other reference monitors) and every
  BAM's `device` fallback. If wanted later, add a public label used only by the meta and leave
  `verbose_name` alone. Revisit when SJVAir branding for BAMs is wanted on the map or dashboard.

## After merge

`@sjvair/sdk` types the new fields on `release/5.0.0` (its zod schema strips unknown keys), then
`5.0.0-beta.10` with the user's yes for that publish; map-sdk part 5's Monitors and Pollutant tasks
wait on it.

## Left to the builder

Test file placement.
