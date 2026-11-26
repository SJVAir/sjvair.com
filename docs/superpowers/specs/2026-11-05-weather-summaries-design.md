# Weather summaries for CIMIS stations

Release 1, step 3 follow-up (sjvair.com + sdk-js). Drafted 2026-11-05. Item 4 of the four
"Get data layers" additions asked for by step 4 spec 3 of the SJVAir Dashboard (the "Get
data" page, route `/workspace/data`). Items 1–3 are in
`2026-11-05-get-data-place-layers-design.md`; item 2 there (weather stations near a place) is
how a place finds the station whose summaries this item charts.

## Why

Get data charts a place over days and months through the summaries API. Weather today is raw
hourly only: the catalog lists every weather type as `['raw']`, because only particulates and
gases set `summarize = True` (`camp/apps/entries/models/base.py` defaults it to False).

**The user's framing (2026-11-05): extend the existing summaries; don't build a new system.**
The summaries app is already generic per entry type (`MonitorSummary` / `RegionSummary` with
the same stats for every type), so the dashboard can chart weather through the same API it
uses for air quality.

## Verified (develop 0a603d90)

- **`summarize` is per entry model, and models are shared.** CIMIS's Temperature and Humidity
  are the same models air sensors use (PurpleAir and others, reading inside the case). Setting
  `summarize = True` on them would summarize every air sensor's temperature and fan out
  region summaries for every region. So CIMIS-only needs a new switch.
- Everything that decides "is this type summarized" keys off the model flag:
  `get_summarizable_entry_models()` (`camp/apps/summaries/tasks.py`; used by the hourly monitor
  and region parents, the daily-and-longer rollups, backfill, and `rebuild_summaries`), the
  catalog (`camp/api/v2/meta/catalog.py`), and coverage (`require_summarized`,
  `is_summarized` in `camp/api/v2/meta/coverage.py`). 13 call sites in all.
- **Completeness:** CIMIS has `EXPECTED_INTERVAL = '1h'`, so an hourly row's `expected_count`
  is 1. Day-and-longer rows sum `expected_count` over the hourly rows that exist
  (`rollup_summaries`), so a missing hour adds to neither side: a day with 10 of 24 hours is
  "complete". True for every type today.
- **Grades and health** only weight region summaries; monitor summaries don't read them.
- **Totals aren't served:** `sum_value` is stored on every summary row but neither summary
  serializer returns it.
- **Late data:** the hourly monitor parent summarizes only the previous hour, once, at :45;
  `import_cimis_data` also runs at :45 for today's Pacific date, and `finalize_cimis_data`
  re-pulls yesterday at 12:00 UTC (4–5 AM Pacific), after the 01:00 Pacific daily rollup.
  Locally (2026-10-28 on, precipitation): ~51% of CIMIS readings were created under an hour
  after their stamp, ~17% at 1–2 h, ~32% later (partly the stack being off overnight). A
  reading that misses its one hourly run is never summarized. No QC revisions were seen
  locally (`modified` never moved).
- **Hour stamps:** `CIMIS.parse_timestamp` stamps CIMIS's hour-ending label (`1300` = noon to
  1 pm, `2400` = 00:00 next day) at the end of the hour and attaches `America/Los_Angeles`.
  Summaries treat a stamp as the start of its hour (`[hour, hour+1)`), so a summary day would
  hold the previous day's last hour and drop its own. CIMIS's day runs 01:00–24:00 hour-ending
  ([UC ANR](https://ucanr-igis.github.io/sketchbook/cimis_hour2day_investigation.html)).
  Whether CIMIS hours stay on PST through daylight saving is unconfirmed: not in the docs
  found, and local data around the 2026-11-01 change was too patchy to tell.
- **History:** CIMIS has been on `main` since July 2026 (commit a29c465d). Locally, CIMIS data
  starts 2026-10-26. 23 stations.
- CIMIS stores 12 types, all RAW: temperature, humidity, dew point, soil temperature, wind
  speed, wind direction, precipitation, solar radiation, net radiation, vapor pressure, ETo,
  ETr.

## Decisions (the user, 2026-11-05)

- **A per-monitor-type switch.** A monitor type can turn summaries on for specific entry types
  in its own config. CIMIS turns on **11 types: all but wind direction** (averaging angles is
  wrong; a circular mean is not planned). Air sensors' temperature and humidity stay off.
  Air-quality summaries don't change.
- **Monitor summaries only, no region rows for weather.** Region weighting is built on
  air-sensor grades and health checks, and a place gets its weather through item 2's station
  list. Region-level weather is deferred.
- **All resolutions** (hour, day, month, quarter, season, year) through the existing scheduled
  tasks.
- **Totals:** monitor summary rows gain `sum` (the stored `sum_value`), so precipitation, ETo
  and ETr chart as daily and monthly totals.
- **Summarize CIMIS when it arrives** (the user, after review, 2026-11-05). Each CIMIS import
  summarizes the hours it just wrote, and the daily finalize re-pull re-rolls yesterday's
  daily rows. Weather isn't tied to the air-quality :45 clock.
- **Fix CIMIS hour stamps first** (the user, after review, 2026-11-05). Stamp each reading at
  the start of its hour, confirm daylight-saving handling, and re-pull our stored range from
  CIMIS before the history rebuild.
- **`is_complete` stays as it is** (the user, after review, 2026-11-05). On day-and-longer rows
  it only counts hours that have rows, for every type; changing that would change air
  quality. The dashboard judges a partial total from `count` (hours with data) against the
  hours in the period.
- **History: summarize what we already store.** No CIMIS archive import, now or tracked for
  later.

## The design

### The switch

- In a monitor type's `ENTRY_CONFIG`, an entry type's config may set `'summarize': True`.
  CIMIS sets it on its 11 types.
- One helper is the single answer to "is (monitor type, entry type) summarized": true when the
  entry model's `summarize` is true (every monitor type, as today) **or** that monitor type's
  config turns it on. Every call site uses it; none reads `entry_model.summarize` directly
  after this change.
- A second answer, "is this entry type summarized for regions", stays the model flag alone.
  Types turned on only through a monitor type's config never get region rows.

### Where it applies

- **Hourly monitor parent:** for a switch-only type, only the monitor types that turn it on
  (so a PurpleAir's temperature is never summarized).
- **Hourly region parent, region rollups, region backfill, `rebuild_summaries` region work:**
  only region-summarized types (unchanged list).
- **Daily-and-longer monitor rollups:** they roll up existing hourly rows per (monitor, entry
  type); they must include switch-only types. The plan checks each rollup task's entry-type
  list.
- **`check_summary_integrity`:** its "monitor hourly rows but no region hourly rows" check
  must count only region-summarized types, or weather rows alone would raise false errors.
- **`repair_summaries`:** monitor-scoped repairs must cover switch-only types.
- **Catalog:** the weather dataset lists the 11 types with the summary resolutions
  (`SUMMARIZED`) and wind direction as `['raw']`, decided per (monitor type, entry type)
  through the helper. Air quality's list doesn't change.
- **Coverage:** unchanged. Weather coverage (`weather_span`, and `monitor_span`'s
  unpublished path for CIMIS) already reads the entries and works (my call after review).
- **Bulk monitor summaries** (`BulkMonitorSummaryList`): unchanged, air quality only
  (`get_public()` and `published_for()` drop CIMIS). The dashboard fetches one station's
  summaries at a time (my call after review).
- **Summaries API:** `MonitorSummarySerializer` gains `sum` (from `sum_value`), additive. The
  region serializer doesn't: a region's weighted sum isn't a total. Monitor summary requests
  for wind direction answer as they do today for any unsummarized type.

### Summarizing on arrival

- CIMIS ingest (`import_cimis_data`, `finalize_cimis_data`) records which (monitor, hour)
  pairs it created or changed, and enqueues the hourly monitor summaries for them (switch-on
  types only), then the daily rollup for any affected day that has already been rolled up.
  The plan picks the mechanism (collect during the import, or a trailing window over
  `modified`).
- The :45 hourly monitor parent may keep skipping CIMIS types or include them; the plan
  decides, avoiding double work.
- Interaction with the summary cache rule: a day re-rolled after its `SETTLE_MARGIN` would sit
  stale for up to a day in clients' caches. The plan checks `schedule.py` and either fits the
  re-roll inside the margin (the 12:00 UTC finalize is 4–5 AM Pacific) or widens the margin for
  these types, keeping the crontab-vs-margin test meaningful.
- Monthly and longer rows: re-rolled when a re-rolled day falls in an already-rolled period
  (the first days of a month), or left to `repair_summaries`; the plan decides.

### Fixing CIMIS hour stamps (before the rebuild)

- `parse_timestamp` stamps the start of the hour: `HHMM` hour-ending becomes `HH-1:00`, and
  `2400` becomes 23:00 the same date.
- Daylight saving: the plan confirms whether CIMIS hours are PST year-round (CIMIS API docs,
  or comparing a summer day's solar-radiation curve with solar noon on production-like data,
  or DWR). If PST year-round, attach a fixed UTC−8 offset instead of `America/Los_Angeles`.
- Stored history is re-stamped by re-pulling from the CIMIS API over our stored date range
  (the existing ingest, scoped by date and station), after deleting the old-stamp rows for
  that range, so no reading exists under two stamps. The plan writes a scoped command
  (`--station`/`--monitor`, dates, `--dry-run` counts) for it; locally run 1 → 3 → 23 stations
  with the coordinator's OK; production goes to the deploy entry, before the summary rebuild.
- `LatestEntry` rows for CIMIS follow the new stamps.
- Visible change: every CIMIS reading's `timestamp` in the entries API moves one hour earlier
  (and may shift again in summer). Clients and the coordinator are told before it merges.

### Load

23 stations × 11 types ≈ 250 hourly monitor tasks and rows per hour, ~6,000 rows a day,
~2.2 million a year. The hourly monitor parent enqueues one child per (monitor, type,
processor), so this adds ~250 children per hour. The plan measures the hourly parent's run
time locally before and after and says whether batching is needed.

### History rebuild

After the re-stamp above. `rebuild_summaries <start> <end> --monitor <id> --monitors-only`, from the first CIMIS entry to
now. Monthly and longer rows are only built for finished periods; the scheduled rollups fill
the rest as they finish.

- **Local:** one station, then 3, then all 23, each step with its row counts checked first.
  The shared local database is used by other sessions: ask the coordinator
  (`data-dashboard-b7`) before each write.
- **Production:** never run from this work. The same steps (scoped per station, counts first)
  go to the coordinator for the deploy entry in data-dashboard `DEFERRED.md`.

## SDK (sdk-js, `release/5.0.0`)

- `sum` (number, nullable) on the monitor summary schema.
- The CIMIS entry types in `monitorEntryTypeSchema`, shared with item 2 (whichever lands
  first adds them; the plan checks whether that list should come from metadata instead).
- No beta without the user's yes for that specific release.

## Deferred (data-dashboard `DEFERRED.md`)

- **Region-level weather summaries.** Region weighting is built on air-sensor grades; weather
  needs its own rule. Revisit when a place needs one blended weather value instead of a
  station's.
- **Wind direction summaries** (a circular mean). Revisit when a chart needs prevailing wind.

## Shipping

No migration (the switch is code config). Production steps, in order, recorded in the deploy
entry: the CIMIS re-stamp (re-pull our stored range), then the scoped history rebuild. The PR goes into `develop` only with the user's yes.
