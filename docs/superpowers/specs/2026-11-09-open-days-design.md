# Open days: today-so-far daily rows

Date: 2026-11-09. A follow-up to `2026-11-09-scale-averaging-design.md`, on a branch stacked
on `feature/scale-averaging`. The server side of data-dashboard step 4, spec 5 (calendars). The
SDK side will be in sdk-js.

## Why

Spec 5's calendar colors each day by its daily figure (`daily_statistic`: `mean_24h`,
`max_1h` or `max_8h`). Finished days are strict: a figure is `null` when the day fails EPA's
completeness rule. Two gaps remain:

- **Today**: the user (spec 5, "option A") wants today's cell colored by its figure "so far".
  Today has no daily row (rows are rolled up after midnight), and under the strict rules today
  would stay `null` until evening anyway.
- **Just after midnight**: yesterday has no daily row until the nightly rollup (01:00 monitors,
  01:10 regions), so the calendar can't tell "not rolled up yet" from "no data" without
  hardcoding rollup times.

The dashboard must be able to tell a final figure from one that can still change, and must not
compute rollup or settle timing itself.

## Decisions (the user's, 2026-11-09)

1. **Computed on request**, from stored hourly rows. No storage, no migration, no new job.
2. **Separate "open days" endpoints**, one next to each daily list (monitor, region, monitor
   bulk, region bulk), instead of computed rows mixed into the paged daily lists. The reasons
   (the user agreed): the stored lists stay pageable and cacheable for a day once settled; the
   computed rows have one job and one cache rule (60 s); the daily lists' behaviour doesn't
   change for other clients; the SDK hides the second request behind one helper.
3. **Open days are today, plus any earlier day whose daily row doesn't exist yet, capped at
   that day's settle time** (`is_settled('day', ...)`, normally 03:00 Pacific the next day). A
   missed nightly rollup therefore shows as no data after the cap. It stays visible and gets
   repaired (`repair_summaries`) instead of being masked by on-request rows.
4. **`is_final` on stored rows** means "this row can't change anymore": the settled rule
   `is_settled` already used by the cache, including the 28 h margin for 8-hour (CO) daily rows
   and the late margin for CIMIS types. Open-day rows are always `is_final: false`.
5. The dashboard's rule: `is_final: false` on today means "so far"; `false` on an earlier day
   means "not final yet"; a missing row means "no data".

## Design

### 1. `is_final` on every summary row

- `MonitorSummarySerializer` and `RegionSummarySerializer` gain `is_final`, computed per row as
  `is_settled(resolution, period_end(resolution, row.timestamp), late=..., peak_8h=...)`. Here
  `late` is true for the entry type when it's a switch type, and `peak_8h` is true when the
  entry type's `daily_statistic == 'max_8h'`. Every resolution gets it, not only daily
  (*my call*: one rule everywhere, cheap, no query).
- Computed at serialization from the request time. Responses are already cached by the
  settled rule, so a settled response never carries a stale `false`. An unsettled response
  (max-age 60) is at most a minute out of date.
- One instant per request (final review): `SummaryMixin.dispatch` reads the time once, and the
  cache rule, every row's `is_final` (bound through a context variable in the serializers
  module) and the open endpoints' open days all use it, so a request that straddles a settle
  time can't send `is_final: false` under a one-day max-age.

### 2. The open-day row

Built per series from that day's stored hourly rows, the same way the daily rollup builds a
daily row:

- Monitors: `rollup_summaries` over every hourly row that exists so far (complete or not, as
  the nightly rollup does), giving the monitor row's usual fields (`count`, `expected_count`,
  `sum`, `minimum`, `maximum`, `mean`, `stddev`, `p25`, `p75`, `is_complete`).
- Regions: `rollup_region_stats` over the day's region hourly rows, plus `station_count` as the
  max across those hours (as `rollup_region_summaries` does). Region rows have no `is_complete`,
  the same as stored region rows.
- `timestamp` is the day's Pacific midnight and `resolution` is `day`.
- `is_final: false`.
- The daily figures:
  - **Today** uses the "so far" rules. `mean_24h` is the mean of the hourly means so far;
    `max_1h` is the highest hourly mean so far; `max_8h` is the highest valid 8-hour window
    so far, where a window still needs at least 6 of its 8 hours and only windows starting
    today count. The 75% rule and the standard exception don't apply. "Has data" and the
    sentinel skip (<= -900) are as for stored rows.
  - **An earlier open day** (the day is over) uses the strict rules, so the row shows what the
    stored row will most likely say (*my call*). For CO that includes the provisional
    `max_8h`, whose next-day hours may still be arriving.
  - Only the field the scale's `daily_statistic` names is set; the others are `null`, as on
    stored rows.
- A series with no hourly rows for the day gets no open row ("no data").

### 3. Endpoints

Each mirrors its daily list's addressing and series selection, minus the date range:

- `monitors/<id>/summaries/<entry_type>/daily/open/` (`?processor=` as in the daily list,
  default `''`)
- `regions/<id>/summaries/<entry_type>/daily/open/`
- `monitors/<entry_type>/summaries/daily/open/`, with all of the monitor bulk daily list's
  scoping: `region`, `bbox`, the `MonitorFilter` query parameters, the published-series default,
  and an explicit `?processor=` override. There's no `start`/`end`.
- `regions/<entry_type>/summaries/daily/open/`, with the region bulk daily list's scoping (at
  least one `region`, as that list requires) and no dates.

The bulk forms are date-less variants of `BulkMonitorSummaryForm` / `BulkRegionSummaryForm`,
built by splitting their scoping fields from the inherited `start`/`end`; the existing forms keep
their behaviour.

The response is shaped like the list it sits next to (`data` rows; bulk nests rows under each
monitor or region). The single-owner endpoints aren't paginated: at most 2 open days, so at
most 2 rows per series. **The bulk open endpoints are paginated by owner, 100 owners per page**
(*my call*). Without it, an unscoped request (every public PurpleAir for PM2.5) would build every
monitor's rows, with t-digest merges for `p25`/`p75`, in one response every 60 s. Paging keeps
each request bounded and the rows complete, like the bulk lists.

**The bulk open endpoints list only owners with an hourly row of the series since the first
open day** (final review). An EXISTS on the summary table (served by its unique index, or the
`(resolution, timestamp)` index) runs in the owner query, so an unscoped request pages through
active owners, not every idle one, and pages stay full. For monitors the series is the one in
use: `?processor=`, or the published series per monitor type. An owner whose only such hours
are yesterday's, with yesterday stored, is still listed with `summaries: []`.

Caching: `private, max-age=60` with an ETag, like an unsettled daily list. Errors `no-cache`.
**Server side**, the built rows are cached for 60 s (`cached_open_rows`, Django cache) under a
key of the kind, entry type, series filter, the sorted owner ids (hashed) and the open-day set,
so every client polling the same page in the same minute shares one build. The cached value is
the unsaved row instances (they pickle). A new owner set or the next open-day set (midnight,
yesterday's settle) misses. Open rows skip building the merged t-digest
(`rollup_summaries(..., with_tdigest=False)`; `p25`/`p75` are kept); the nightly rollup's
output is unchanged.

Performance: a new grouped read, not the writer's. The writer's read is driven by existing
daily rows and selects only `mean`, while open days have no daily row and the rollup needs
every stats column. One query per request (single owner) or per page of owners (bulk) selects
the open days' hourly rows with all the columns the rollup reads (`count`, `expected_count`,
`sum_value`, `sum_of_squares`, `minimum`, `maximum`, `tdigest`, `mean`, plus `is_complete` for
monitors and `weight`/`station_count` for regions). The `is_complete` and sentinel filters
apply in Python to the figures only. One more query per request or page checks which (owner,
series, day) already have a stored daily row. That's at most about 48 hours of hourly rows per
series, plus the 7 h tail `max_8h` needs for an earlier open day.

### 4. Where the code lives

A new module `camp/apps/summaries/open_days.py`:
- `open_days(now) -> list[datetime]`: the day starts that may be open: today, plus yesterday
  while `is_settled('day', end_of_yesterday, now=now)` is false. That's the plain day margin
  for every entry type (*my call*): the cap is about whether the nightly rollup should have
  written the row. The 28 h CO margin is about the figure changing, and that's `is_final`'s
  job, so it doesn't widen the cap. So there are at most 2 open days.
- `build_open_rows(kind, owner_ids, entry_model, now, processor_q=None) -> {owner: [rows]}`:
  unsaved `MonitorSummary`/`RegionSummary` rows. `cached_open_rows` (same arguments) wraps it
  in the 60 s cache; the endpoints call that.

It reuses `peaks.py` (`day_hours`, the figure functions with a "so far" switch, the sentinel
filter), `aggregators.py` (`rollup_summaries`, `rollup_region_stats`), `periods.py` and
`schedule.is_settled`. A stored daily row's existence is checked in the same grouped query.

Every entry type the daily list serves is served here too. Types with no `daily_statistic`
(temperature, the CIMIS weather types) get rows whose three figures are `null`.

## Non-goals

- Open rows for other resolutions (an open month or year). Only daily.
- Storing provisional rows.
- Changing the daily lists' paging, filtering or caching.
- Repairing missed rollups automatically.

## Testing

- `is_final`: a settled daily row is true. Yesterday is false at 02:59 and true at 03:00. A CO
  daily row is false until end + 28 h. Hourly, monthly and CIMIS rows follow their own margins.
- Open days at 00:30: today and yesterday are both open when yesterday has no stored row. At
  00:30 with a stored yesterday row, only today is open. At 03:00 with no stored yesterday row,
  only today is open (the cap).
- Today's figures so far: 3 hours of O3 give `max_1h` = their max (no 75% rule). PM's
  `mean_24h` is the mean of the means so far. CO's `max_8h` is `null` until a window has 6
  hours. A sentinel hour is skipped.
- An earlier open day uses the strict rules (17 of 24 hours → `null`).
- Each endpoint: shape, processor/series selection, scoping (bulk: `MonitorFilter`, `processor`,
  region required for region bulk), the 60 s cache headers, 404s like the daily list, and no
  rows when there's no hourly data. Bulk pages by owner (100). A temperature series gets rows
  with null figures.
- Region open rows carry `station_count` (the max across hours) and no `is_complete`.
- Bulk query count stays bounded across many owners.
- Bulk lists only owners with open-window hourly rows of the series in use (an owner whose only
  rows are another series, or older, is absent).
- The server-side cache: a second identical call does no query; a different owner set, series
  filter, entry type or open-day set misses.
- One instant per request: a request straddling a settle time keeps `is_final` and the cache
  rule consistent.

## Docs

CLAUDE.md: a short bullet on `is_final`, the open-days endpoints, the cap, and the
dashboard's reading rule.

## Left to the builder

- Function names and the exact grouped query.
- How the bulk open endpoints share code with the bulk lists' scoping forms.
