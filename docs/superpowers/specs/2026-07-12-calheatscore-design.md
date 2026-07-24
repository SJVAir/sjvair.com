# CalHeatScore Integration — Design

**Branch:** `feature/calheatscore`
**Status:** Draft, approved for planning

## Summary

Integrate [CalHeatScore](https://calheatscore.calepa.ca.gov/), CalEPA's public ZIP-code-level
heat risk index (0–4 scale, 7-day rolling forecast), so SJVAir can enrich monitor/region views
with heat risk data. Modeled on the existing `ces` app (dedicated app + API namespace for
region-scoped external data) and the `hms`/`airnow` apps (external API client + periodic Huey
ingestion task).

## Data Source

Public, unauthenticated ArcGIS Feature Service:

```
https://services1.arcgis.com/PCHfdHz4GlDNAhBb/arcgis/rest/services/CalHeatScore_Live_Data_for_API_Use/FeatureServer/0/query
```

- No API key required.
- Query params: `where`, `outFields`, `returnGeometry=false`, `f=json` (standard ArcGIS REST query syntax).
- Response is a 7-day rolling forecast per ZIP in wide format: `ZIP_CODE`, `DATE` (as-of date),
  `CHS_Day_0` .. `CHS_Day_6` (scores 0–4, returned as strings — must cast to int).
- Max 2,000 records per response; statewide dataset is ~1,721 ZIP codes. Data refreshes at
  5:00am and 8:00am Pacific daily.
- Fair-use rate limits apply (no published threshold); recommended to keep concurrent requests
  low, request only needed fields, and cache/fetch once per day.
- Score labels (from CalHeatScore's own interpretation table): 0 Low, 1 Mild, 2 Moderate,
  3 High, 4 Severe.

## App Location

New app: `camp/apps/calheatscore/`. Not folded into `regions` (which stays a generic geography
utility) and not merged into `ces` (a different, unrelated dataset) — consistent with how `ces`,
`hms`, and `ceidars` each get their own app for a distinct external data source.

## Data Model

One row per (ZIP region, calendar date), upserted in place as the forecast refines. No
forecast-revision history is kept — only the latest known score for a given date is stored, per
explicit product decision (heat scores rarely change so dramatically that revision tracking is
worth the complexity). Because the source API never returns past dates, once a date has passed
its row is never touched again, so historical actuals accumulate as a natural side effect of the
daily forecast pulls.

```python
class CalHeatScore(models.Model):
    sqid = SqidsField(alphabet=shuffle_alphabet('calheatscore.CalHeatScore'))
    region = models.ForeignKey(
        'regions.Region',
        verbose_name=_('ZIP Code'),
        on_delete=models.CASCADE,
        related_name='heat_scores',
        limit_choices_to={'type': Region.Type.ZIPCODE},
    )
    date = models.DateField(_('Date'))
    score = models.IntegerField(_('Score'), choices=Score.choices)
    updated_at = models.DateTimeField(_('Updated At'), auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['region', 'date'], name='unique_calheatscore_region_date'),
        ]
        ordering = ['-date']
```

`limit_choices_to={'type': Region.Type.ZIPCODE}` restricts the admin/form dropdown to ZIP
regions. This is **not** a hard database constraint — Django doesn't enforce
`limit_choices_to` outside of forms/admin, and no existing model in this codebase (e.g.
`ceidars.EmissionsRecord.zipcode`) enforces FK-type restrictions at the DB or `clean()` level
either. This follows that same established (loose) convention rather than introducing new
enforcement machinery.

`Score` is an `IntegerChoices`:

```python
class Score(models.IntegerChoices):
    LOW = 0, _('Low')
    MILD = 1, _('Mild')
    MODERATE = 2, _('Moderate')
    HIGH = 3, _('High')
    SEVERE = 4, _('Severe')
```

## Ingestion

**Fetch scope:** Restricted to SJV ZIP codes, not the full statewide dataset — matches how
`airnow`/`cimis` scope their ingestion to SJV counties. Computed as:

```python
sjv_geometry = Region.objects.counties().combined_geometry()
zip_regions = Region.objects.filter(type=Region.Type.ZIPCODE).intersects(sjv_geometry)
```

**Client** (`camp/apps/calheatscore/client.py`): thin wrapper around the ArcGIS query endpoint,
following the `AirNowClient` pattern (a `requests.Session` with retry adapter, JSON body
handling). Builds a single batched request per run:

```python
where = "ZIP_CODE IN ({})".format(','.join(f"'{z}'" for z in zip_codes))
params = {
    'where': where,
    'outFields': 'ZIP_CODE,DATE,CHS_Day_0,CHS_Day_1,CHS_Day_2,CHS_Day_3,CHS_Day_4,CHS_Day_5,CHS_Day_6',
    'returnGeometry': 'false',
    'f': 'json',
}
```

The response must be checked for an `error` property before processing (the service returns
HTTP 200 even on error). Confirmed via a live request: `DATE` is returned as a plain
`"YYYY-MM-DD"` string (not an epoch-millisecond integer, as some ArcGIS services use), so it
parses directly with `datetime.strptime(value, '%Y-%m-%d').date()`. `DATE` reflects the as-of
date the service last refreshed (`CHS_Day_0` = that date, `CHS_Day_N` = that date + N days) —
it lags behind the calendar date until the daily 5am/8am Pacific refresh has run.

**Task** (`camp/apps/calheatscore/tasks.py`): a `db_periodic_task` scheduled once daily
(~9:00am Pacific, after the source's 5am/8am refresh window), following the `hms`/`airnow`
periodic-task shape. For each returned row, `update_or_create`s up to 7 `CalHeatScore` rows
(`CHS_Day_0` through `CHS_Day_6`, mapped to `date` = as-of date + N days) keyed on
`(region, date)`. Rows for ZIP codes not present in the SJV region set are skipped.

## API

New namespace `camp/api/v2/calheatscore/`, following the `ces` app's endpoint/serializer/filter
structure but shaped as a time series (closer to how `entries` are listed per monitor) since
that's the natural shape of this data — a list of dates, not a single annual snapshot per
region.

- `GET /api/2.0/calheatscore/` — today's score for every SJV ZIP; filterable by `?date=`.
- `GET /api/2.0/calheatscore/<zip>/` — all stored dates (past actuals + forecast) for one ZIP,
  paginated, ordered by `-date`.

Serializer fields: ZIP (`region.external_id`), `date`, `score`, and the human-readable label
(`get_score_display()`).

## Admin

Register `CalHeatScore` in Django admin with list display (ZIP, date, score, updated_at) and
filtering by date/score, matching the lightweight admin registration pattern used by `CES4`.

## Testing

- Fixture `fixtures/calheatscore.yaml`: fake scores referencing the existing ZIP region fixture
  (Fresno `93728`, `regions.yaml` pk 11) — no new region fixtures needed.
- Client tests mock the `requests` call (same approach as other API-client tests in this
  codebase).
- Task tests use Huey's sync `.call_local()` per the existing test convention used elsewhere
  in this codebase (e.g. `hms`, `airnow` task tests).
- API tests follow the `ces` app's endpoint test patterns (list + detail-by-ZIP, date
  filtering).

## Out of Scope

- The historical monthly CSV archive (separate from the live API) — not imported; only the
  live 7-day forecast feed is ingested.
- Forecast-revision tracking (multiple stored values per date as the forecast approaches) —
  explicitly decided against; only the latest value per date is kept.
- Statewide ZIP coverage — only SJV-area ZIP codes are fetched and stored.
- Alerting/notifications on heat score thresholds — this integration only stores and exposes
  the data; alerting is a separate future effort.
- Fixup field on `MonitorSerializer` — a dedicated endpoint was chosen instead; can be added
  later without conflicting with this design.
