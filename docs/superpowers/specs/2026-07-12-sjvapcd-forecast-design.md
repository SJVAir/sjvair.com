# SJVAPCD Daily Air Quality Forecast Integration

## Purpose

Ingest the San Joaquin Valley Air Pollution Control District's (SJVAPCD) daily
air quality forecast and expose it through the SJVAir API, both as a
general-purpose data source and to drive a forecast map layer on the
front end (counties shaded by forecast AQI category).

Source page: https://ww2.valleyair.org/air-quality-information/daily-air-quality-forecast/

## Data Source

SJVAPCD publishes an XML feed intended for exactly this purpose:

```
https://ww2.valleyair.org/aqinfo/airstatus.xml
```

- Format: RSS-like XML with custom `burnStatus:` and `AQI:` namespaced elements.
- Updated daily by ~4:30pm Pacific (`ttl` of 1440 minutes / 24h — not meant to
  be polled more often than daily).
- One `<item>` per forecast zone, each containing:
  - `<county>` — zone name (see "Zone mapping" below)
  - `<burnStatus:today>` / `<burnStatus:tomorrow>` — burn status, each with a
    `date` and `status` attribute, plus descriptive text content
  - `<AQI:today>` / `<AQI:tomorrow>` — AQI forecast, each with a `date` and
    `status` (color) attribute, and text content like
    `"101 Unhealthy for Sensitive Groups (O3)"` (value, category label,
    dominant pollutant)
  - `<airAlertStatus status="NO|YES" startDate="" endDate="">`
  - `<pubdate>` — when this item was published

Example item (abridged):

```xml
<item>
  <county>Fresno</county>
  <burnStatus:today date="2026-07-11T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:today>
  <AQI:today date="2026-07-11T00:00:00 -7:00" status="Orange">101 Unhealthy for Sensitive Groups (O3)</AQI:today>
  <burnStatus:tomorrow date="2026-07-12T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:tomorrow>
  <AQI:tomorrow date="2026-07-12T00:00:00 -7:00" status="Yellow">100 Moderate (O3)</AQI:tomorrow>
  <airAlertStatus status="NO" startDate="" endDate=""></airAlertStatus>
  <pubdate>2026-07-11T14:31:09 -7:00</pubdate>
</item>
```

### Zone mapping

> **Update (2026-07-13):** the section below describes the *original* plan.
> It's been superseded — see "Zone geometry update" after the Out of Scope
> section for what actually shipped. Kept here for history/context on why
> the original call was made.

The feed publishes 9 zones. 8 map 1:1 (after one alias) to the existing SJV
county `Region` records (`camp.apps.regions.managers.SJV_COUNTIES`); one does
not correspond to any `Region` and is dropped:

| Feed `<county>` value              | Region                  |
|-------------------------------------|--------------------------|
| San Joaquin, Stanislaus, Merced, Madera, Fresno, Kings, Tulare | matches `Region` name directly |
| `Kern (SJV Air Basin portion)`      | aliased to `Kern`        |
| `Sequoia National Park and Forest`  | **dropped** — no matching `Region`, not a county |

This was confirmed against the SJVAPCD's own published forecast map, which
draws Kern's zone clipped to the air-basin portion (not the full county) and
draws Sequoia National Park and Forest as its own separate shape. For this
pass we reuse the existing county `Region` boundaries as an approximation
(Kern rendered as the full county) rather than sourcing/importing accurate
forecast-zone geometry. This is a known, accepted simplification — a future
pass could import real zone boundaries if pixel-accurate map shading becomes
a requirement.

## Data Model

New app: `camp/apps/forecasts/`

```python
from django.contrib.gis.db import models  # not needed unless geometry added later; use django.db.models
from django.db import models
from django.utils.translation import gettext_lazy as _
from django_sqids import SqidsField, shuffle_alphabet
from model_utils.models import TimeStampedModel


class Forecast(TimeStampedModel):
    class Pollutant(models.TextChoices):
        OZONE = 'O3', _('Ozone')
        PM25 = 'PM2.5', _('PM2.5')

    sqid = SqidsField(alphabet=shuffle_alphabet('forecasts.Forecast'))

    region = models.ForeignKey('regions.Region', on_delete=models.CASCADE, related_name='forecasts')
    zone_name = models.CharField(_('zone name'), max_length=64)  # raw <county> label, for audit/debugging

    forecast_date = models.DateField(_('forecast date'))  # date this forecast is FOR
    issued_date = models.DateField(_('issued date'))       # Pacific date this forecast was pulled
    published_at = models.DateTimeField(_('published at'))  # feed's own <pubdate>

    aqi_value = models.PositiveSmallIntegerField(_('AQI value'))
    aqi_category = models.CharField(_('AQI category'), max_length=32)  # via camp.utils.aqi.aqi_label
    pollutant = models.CharField(_('pollutant'), max_length=16, choices=Pollutant.choices)

    burn_status = models.CharField(_('burn status'), max_length=32, blank=True)
    burn_status_text = models.CharField(_('burn status text'), max_length=255, blank=True)

    air_alert = models.BooleanField(_('air alert'), default=False)
    air_alert_start = models.DateField(_('air alert start'), null=True, blank=True)
    air_alert_end = models.DateField(_('air alert end'), null=True, blank=True)

    class Meta:
        ordering = ('-issued_date', 'region__name')
        indexes = [
            models.Index(fields=['region', 'forecast_date']),
            models.Index(fields=['issued_date']),
        ]
```

Notes:
- `pollutant` uses `TextChoices` since the feed only ever reports `O3` or
  `PM2.5` as the dominant pollutant for this forecast program. Ingestion does
  **not** call `full_clean()`, so an unrecognized future value is still
  stored as free text rather than breaking the daily task.
- `burn_status` / `burn_status_text` stay plain `CharField` — the full set of
  possible status values (`Discouraged`, presumably `Allowed`/`Prohibited`)
  hasn't been observed yet.
- **Full history is kept.** Every daily pull writes 2 new rows per zone (one
  for `forecast_date == issued_date` ["today"], one for
  `forecast_date == issued_date + 1` ["tomorrow"]) rather than upserting a
  single latest-forecast row. This lets us later compare a "tomorrow"
  prediction against the "today" actual pulled the next day for the same
  calendar date.
- `forecast_date` is parsed from each element's own `date="..."` attribute
  (authoritative from the feed), not assumed from `issued_date` arithmetic.

## Ingestion Task

`camp/apps/forecasts/tasks.py`, following the `camp.apps.hms` pattern
(external feed → periodic task → idempotent delete-and-recreate):

```python
FEED_URL = 'https://ww2.valleyair.org/aqinfo/airstatus.xml'
ZONE_ALIASES = {'Kern (SJV Air Basin portion)': 'Kern'}
AQI_TEXT_RE = re.compile(r'^(\d+)\s+.+?\(([^)]+)\)$')  # "101 ... (O3)" -> (101, 'O3')

@db_periodic_task(crontab(minute='45', hour='23,0,1,2'), priority=50)
def fetch_forecasts():
    issued_date = timezone.now().astimezone(settings.DEFAULT_TIMEZONE).date()
    response = requests.get(FEED_URL, timeout=30)
    root = ET.fromstring(response.content)

    with transaction.atomic():
        Forecast.objects.filter(issued_date=issued_date).delete()
        for item in root.iter('item'):
            zone_name = item.findtext('county').strip()
            region = Region.objects.county.filter(
                name=ZONE_ALIASES.get(zone_name, zone_name)
            ).first()
            if region is None:
                continue  # unmapped zone (Sequoia National Park and Forest)

            published_at = parse_pubdate(item.findtext('pubdate'))
            for horizon in ('today', 'tomorrow'):
                # parse AQI:<horizon>, burnStatus:<horizon>, airAlertStatus
                # via the burnStatus:/AQI: namespace map
                Forecast.objects.create(
                    region=region,
                    zone_name=zone_name,
                    forecast_date=...,   # from element's date= attribute
                    issued_date=issued_date,
                    published_at=published_at,
                    aqi_value=value,
                    aqi_category=aqi_label(value),
                    pollutant=pollutant,
                    burn_status=...,
                    burn_status_text=...,
                    air_alert=...,
                    air_alert_start=...,
                    air_alert_end=...,
                )
```

- **Crontab window `minute=45, hour=23,0,1,2` (UTC)** covers roughly
  4:45pm–7:45pm Pacific regardless of DST, so the daily "by 4:30pm" update is
  reliably caught without hardcoding a DST-specific offset. Mirrors `hms`'s
  multi-run + idempotent-replace approach rather than `hms`'s separate
  "final re-fetch" task, since this feed is much cheaper to fetch than HMS
  shapefiles.
- **Idempotent**: deletes and recreates all rows for `issued_date` on every
  run, so repeated runs within the window (or manual re-runs) never
  duplicate data — same convention as `import_pur` and `hms.fetch_smoke`.
- Uses `defusedxml.ElementTree` (not stdlib `xml.etree.ElementTree`, which is
  vulnerable to XXE/billion-laughs by default) with a namespace map for the
  `burnStatus:`/`AQI:` prefixed elements. New dependency: `defusedxml`,
  added to `requirements/base.txt`. `requests` is already a project
  dependency.

### Management command

`camp/apps/forecasts/management/commands/fetch_forecasts.py`, following the
`hms.import_hms` pattern:

```python
class Command(BaseCommand):
    help = 'Fetch the SJVAPCD daily air quality forecast feed.'

    def handle(self, *args, **options):
        self.stdout.write('Fetching SJVAPCD forecasts...')
        fetch_forecasts.call_local()
        self.stdout.write(self.style.SUCCESS('Done.'))
```

No arguments — unlike `hms`'s per-date backfill, this task always ingests
"now" (the feed has no historical archive to backfill from).

## API

New versioned endpoint group at `/api/2.0/forecasts/`, mounted in
`camp/api/v2/urls.py`:

```python
path('forecasts/', include('camp.api.v2.forecasts.urls', namespace='forecasts')),
```

**Serializer** (`camp/api/v2/forecasts/serializers.py`) — embeds the full
`RegionSerializer` (including its boundary GeoJSON) so the frontend map layer
doesn't need a second request per zone:

```python
class ForecastSerializer(serializers.Serializer):
    fields = (
        ('id', lambda f: f.sqid),
        ('region', lambda f: RegionSerializer(f.region).serialize()),
        'zone_name', 'forecast_date', 'issued_date', 'published_at',
        'aqi_value', 'aqi_category', 'pollutant',
        'burn_status', 'burn_status_text',
        'air_alert', 'air_alert_start', 'air_alert_end',
    )
```

Accepted tradeoff: since both the "today" and "tomorrow" row for a zone
embed the same region, the boundary geometry is duplicated across the two
rows in a default list response. Simpler than restructuring the response
shape to dedupe; not worth optimizing unless it proves to be a real problem.

**Endpoints** (`camp/api/v2/forecasts/endpoints.py`), following the
`hms.SmokeList`/`SmokeDetail` pattern:

- `GET /api/2.0/forecasts/` — list. Defaults to `forecast_date >= today`
  (current + future forecasts only) when no `forecast_date` filter is given;
  explicit filters override the default.
- `GET /api/2.0/forecasts/{id}/` — single record detail.

**Filters** (`camp/api/v2/forecasts/filters.py`), following
`hms.SmokeFilter`/`FireFilter`:

- `region_id` — `Region.objects.get(sqid=...)` lookup, same as `hms`.
- `forecast_date` — `exact`/`lt`/`lte`/`gt`/`gte`.
- `issued_date` — `exact`/`lt`/`lte`/`gt`/`gte`.

```python
class ForecastList(ForecastMixin, generics.ListEndpoint):
    filter_class = ForecastFilter

    def get_queryset(self):
        qs = super().get_queryset()
        if 'forecast_date' not in self.request.GET:
            today = timezone.now().astimezone(settings.DEFAULT_TIMEZONE).date()
            qs = qs.filter(forecast_date__gte=today)
        return qs
```

## Admin

`camp/apps/forecasts/admin.py` — simple `ModelAdmin`:
- `list_display`: `zone_name`, `forecast_date`, `issued_date`, `aqi_value`,
  `aqi_category`, `burn_status`, `air_alert`
- `list_filter`: `aqi_category`, `burn_status`, `air_alert`
- `date_hierarchy`: `forecast_date`

## Testing

- `camp/apps/forecasts/tests.py` — task tests against a saved sample of the
  real XML feed (fixture file, not a live fetch):
  - parses correctly into `Forecast` rows
  - aliases `Kern (SJV Air Basin portion)` → `Kern` region
  - skips `Sequoia National Park and Forest` (no matching region)
  - re-running the task for the same `issued_date` is idempotent (no
    duplicate rows)
  - `aqi_category` is derived correctly via `camp.utils.aqi.aqi_label`
- `camp/api/v2/forecasts/tests.py`:
  - list defaults to `forecast_date >= today`
  - `region_id`, `forecast_date`, `issued_date` filters work
  - detail endpoint works
  - region boundary GeoJSON is present in the nested `region` field

## Out of Scope (this pass)

- ~~Accurate forecast-zone geometry (Kern air-basin clip, Sequoia zone) — using
  existing county boundaries as an approximation instead.~~ **Done — see
  "Zone geometry update" below.** Implemented in a follow-up pass on this same
  branch rather than deferred to a separate one.
- Notifications/alerts driven by forecast data (e.g. air alert push
  notifications) — considered and explicitly declined (not just deferred):
  SJVAPCD already runs its own notification system for this, and the
  decision was not to duplicate/compete with it. `air_alert` stays as
  read-only data with no notification wiring.
- Historical backfill — the feed has no archive; history only accumulates
  from when this integration starts running.

## Zone geometry update (2026-07-13)

The original plan (county boundaries as an approximation for Kern and a
dropped Sequoia zone) was superseded once real zone geometry became
available: the SJVAPCD forecast page renders its map as an inline SVG, whose
9 path shapes were saved locally (`datafiles/sjvapcd-forecast-areas.svg`,
cleaned of everything but the shape outlines) and used to derive accurate
lat/lon geometry for the 3 zones that don't map 1:1 to a county:

- **Kern (SJV Air Basin portion)** and **Tulare (SJV Valley portion)**: the
  real county `Region` boundary (already accurate) intersected with the
  SVG shape transformed into lat/lon — the real boundary supplies the outer
  edge, the SVG only supplies the internal dividing line.
- **Sequoia National Park and Forest**: verified (via exact-vertex-sequence
  matching in the raw SVG path data, then confirmed geometrically) to be
  carved entirely from Tulare's territory, not Kern's — defined as
  `real_Tulare − Tulare_zone` so the two tile the real county exactly, with
  no gap or overlap.

The SVG pixel space is georeferenced via an affine transform fit against the
6 zones that *do* map 1:1 to a county (used as ground-control points),
validated to IoU ≥ 0.98 against their real boundaries — sufficient because
the SJV's geographic extent is small enough that map-projection curvature is
negligible.

All 3 are stored as `Region(type=CUSTOM)` records (not a new `Region.Type`
— `CUSTOM` already exists as "catch-all for user-defined regions") with
`metadata` recording their derivation, imported via a new one-time command:
`camp.apps.regions.forecast_zones` (the parsing/fitting logic) +
`manage.py import_forecast_zones` (the command). This must be run once per
environment, after `import_counties`, before Kern/Tulare/Sequoia forecasts
will populate — see the updated CLAUDE.md import instructions.

Every zone in the feed now maps to a region (`ZONE_TO_REGION` in
`camp/apps/forecasts/tasks.py`), so a daily pull creates 18 `Forecast` rows
(9 zones × 2 horizons) instead of the original 16.
