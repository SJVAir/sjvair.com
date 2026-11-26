# Summary rollup findings (2026-11-03)

Found while drafting step 3 spec 2 (summary cache headers). Three problems with the
summary rollups, in order of confidence:

1. **The rollup tasks run on UTC, so every rollup above hourly lands late.** Monthly,
   quarterly and seasonal rollups land about one full period late, and seasonal rollups
   cover the wrong months. Confirmed in the code and in production data.
2. **Months, years and some seasons that start in standard time are stamped one hour
   early** (23:00 the day before, Pacific), so they show up under the previous day,
   month or year. Seen in production data; the cause isn't known yet.
3. **Region summaries are mostly missing on production.** Monitor summaries are fine.
   Seen in production data; the cause isn't known yet.

Every check below is a read-only GET against the public production API, or a read of the
code on `origin/main` (what production runs) and `origin/develop` (same code for all of
this). Results are as of 2026-11-03 ~21:40 PST. Later runs will differ slightly as new
rows land; the patterns should hold.

Setup for the requests:

```bash
B=https://www.sjvair.com/api/2.0
FRESNO=r6phe                    # Fresno County (region id)
KERN=nmup6                      # Kern County
KINGS=ecxum                     # Kings County
MON=oEsTybUIT8-nSOld5rzP_w      # an AirNow monitor that reports PM2.5
ts() { python3 -c "import sys,json; d=json.load(sys.stdin)['data']; print(len(d), [x['timestamp'] for x in d])"; }
```

---

## 1. Rollups run on UTC

### The code

- `camp/apps/summaries/tasks.py` schedules the rollups with `crontab(...)`. The hours
  are meant as Pacific: the daily job at `hour='1'`, so 01:00 after the day ends; monthly
  on `day='1'` at 01:15; and so on (lines 307–383).
- `camp/settings/base.py` `DJANGO_HUEY` (line 419) sets no `utc` option for any queue.
- Huey 3.3's `Huey.__init__` defaults to `utc=True`. With `utc=True`, Huey matches
  crontabs against `utcnow()`, not local time (`Huey._get_timestamp`). So
  `crontab(hour='1')` fires at **01:00 UTC = 17:00 PST / 18:00 PDT the previous day**.
- The tasks then pick their period from the **Pacific** date (`_yesterday()`,
  `_last_month_start()`, `_last_quarter_start()`, `_last_season_start()`, lines 275–303).
  At 01:00 UTC on the 1st it's still the last day of the previous month in Pacific, so
  "last month" means the month *before* the one that just ended.

Check the Huey default yourself:

```bash
podman exec sjvaircom_worker-summaries_1 python -c "
import inspect; from huey.api import Huey
print(inspect.signature(Huey.__init__))          # ... utc=True ...
print(inspect.getsource(Huey._get_timestamp))     # utcnow() if self.utc else now()
"
grep -n "utc" camp/settings/base.py camp/settings/heroku.py   # nothing for Huey
```

**Why a Heroku setting can't explain it:** with `utc=True`, Huey ignores the server's
timezone (`TZ`), so no dyno config changes when the crontabs fire. Only a `utc` option
in the code would, and there isn't one.

### What that does to each resolution

| Rollup    | Fires (UTC)                 | Fires (Pacific)             | Rolls up                                 | Lands             |
| --------- | --------------------------- | --------------------------- | ---------------------------------------- | ----------------- |
| daily     | 01:00 / 01:10               | ~17:00 the next day         | yesterday (correct day)                  | ~17 hours late    |
| monthly   | the 1st, 01:15 / 01:25      | the last day of the month   | the month *before* the one ending        | one month late    |
| quarterly | Jan/Apr/Jul/Oct 1, 01:30/35 | the quarter's last day      | the quarter *before* the one ending      | one quarter late  |
| seasonal  | Mar/Jun/Sep/Dec 1, 01:45/55 | last day of Feb/May/Aug/Nov | a 3-month window starting Nov/Feb/May/Aug: **not a real season** | never on schedule |
| yearly    | Jan 1, 02:00 / 02:05        | Dec 31 ~18:00               | the year *before* the one ending         | one year late     |

Seasons: `_last_season_start()` on Feb 28 (Pacific) has `end_month = 2` and returns
Nov 1 of the previous year. Real seasons start Dec/Mar/Jun/Sep (`higher_rollup_windows`
in `backfill.py`). So only backfills and `rebuild_summaries` ever write a correct season.
Reproduce the arithmetic:

```bash
python3 -c "
for end_month in (2, 5, 8, 11, 3):
    start = end_month - 3 if end_month > 3 else end_month + 9
    print(f'runs with Pacific month {end_month:2} -> season starts month {start}')
"
# 2->11, 5->2, 8->5, 11->8: wrong. 3->12 is what a correct (Pacific) run would give.
```

### Production evidence

**Monthly: October isn't there on Nov 3.** With correct timing it would have landed
Nov 1. With the bug it lands on Nov 30.

```bash
curl -s "$B/monitors/$MON/summaries/pm25/monthly/2026/" | ts
# 8 rows, the last is 2026-09-01 (September). No October.
```

**Quarterly: 2026 has only Q2.** Q1 should have landed Apr 1 and Q3 on Oct 1. With the
bug, the Sep 30 run rolled up Q2, and Q3 waits for Dec 31.

```bash
curl -s "$B/monitors/$MON/summaries/pm25/quarterly/2026/" | ts
# 1 ['2026-04-01T00:00:00-07:00']
```

**Seasonal: a row starts on May 1**, which is the scheduled job's misaligned window
(no real season starts in May).

```bash
curl -s "$B/monitors/$MON/summaries/pm25/seasonal/2026/" | ts
# 3 ['2026-02-28T23:00:00-08:00', '2026-05-01T00:00:00-07:00', '2026-06-01T00:00:00-07:00']
```

**Daily: about 17 hours late.** You can only tell in the window before ~17:00 Pacific.
Before 17:00 PST on any day, yesterday's daily row is missing. After about 17:15 it's
there. Correct timing would have it by ~01:15.

```bash
# Run on Nov 4 before 17:00 PST, then again after 17:15 PST:
curl -s "$B/monitors/$MON/summaries/pm25/daily/2026/11/" | ts
# Before: the last row is 2026-11-02. After: 2026-11-03 appears.
```

---

## 2. Standard-time period starts are stamped an hour early

Every monthly row whose month starts in standard time (Dec, Jan, Feb, Mar) is stamped
**23:00 the day before at -08:00**, which is midnight at the *summer* offset (-07:00).
Months that start in summer time are fine.

```bash
curl -s "$B/monitors/$MON/summaries/pm25/monthly/2025/" | ts
# 12 rows:
#   2025-01-31T23:00:00-08:00   <- February
#   2025-02-28T23:00:00-08:00   <- March
#   2025-04-01T00:00:00-07:00   ... through 2025-11-01T00:00:00-07:00 (correct)
#   2025-11-30T23:00:00-08:00   <- December
#   2025-12-31T23:00:00-08:00   <- January 2026
```

Effects:
- The `monthly/2025/` path returns January **2026** and not January 2025 (that row falls
  in 2024's Pacific range). The path filters by Pacific year boundaries (`get_date_filter`).
- Any client that groups by Pacific date files February under January, and so on.
- Same pattern for years and seasons:

```bash
curl -s "$B/monitors/$MON/summaries/pm25/yearly/" | ts
# 3 ['2023-12-31T23:00:00-08:00', '2024-12-31T23:00:00-08:00', '2025-12-31T23:00:00-08:00']
curl -s "$B/regions/$FRESNO/summaries/pm25/seasonal/2025/" | ts
# 4 [..., '2025-11-30T23:00:00-08:00']   <- the winter season, an hour early
```

The cause isn't known. `settings.DEFAULT_TIMEZONE` is `zoneinfo.ZoneInfo`, and the
scheduled tasks build period starts with `make_aware(datetime(...), tz)`, which is correct.
So the usual suspect (pytz `.replace()` keeping an old offset) is out. The next place to
look is how the rollups and backfills (`rollup_*_summaries`, `backfill.py`
`higher_rollup_windows`) compute or step period starts, e.g. adding a `timedelta` to an
aware datetime across a DST change. Production's rows may have come from backfills rather
than scheduled runs.

---

## 3. Region summaries are mostly missing on production

The same pattern in three counties: no hourly rows on recent days, and only 2 daily rows
for all of October, while the monitor above has a full set.

```bash
for R in $FRESNO $KERN $KINGS; do
  echo "$R hourly 11/2:"; curl -s "$B/regions/$R/summaries/pm25/hourly/2026/11/2/" | ts
  echo "$R daily 10:";    curl -s "$B/regions/$R/summaries/pm25/daily/2026/10/" | ts
  echo "$R daily 9:";     curl -s "$B/regions/$R/summaries/pm25/daily/2026/9/" | ts
done
# Each county: hourly 11/2 -> 0 rows; daily Oct -> 2 rows (Oct 27, Oct 29); daily Sep -> 17 rows.

# Compare with a monitor:
curl -s "$B/monitors/$MON/summaries/pm25/hourly/2026/11/2/" | ts   # 24 rows
curl -s "$B/monitors/$MON/summaries/pm25/daily/2026/10/" | ts      # 30 rows
```

`hourly_region_summaries` is scheduled on `main` (`crontab(hour='*', minute='50')`), so
the task exists in production's code. Not yet known: whether it runs and fails, or doesn't
run. Next steps: the summaries worker's logs on Heroku, whether that dyno is scaled, and
Sentry for `summarize_region_hour`.

---

## What happens next

- **Finding 1** (agreed 2026-11-03): fixed in step 3 spec 2, alongside the summary cache
  headers. The fix can't depend on the dyno's timezone. Each task works out its period
  in Pacific time, so the crontabs keep running on UTC. The fix also covers the seasonal
  window, and a scoped re-run of the periods the late schedule skipped.
- **Findings 2 and 3**: a separate follow-up investigation. Neither has a known cause, and
  both need production logs or data repair.
