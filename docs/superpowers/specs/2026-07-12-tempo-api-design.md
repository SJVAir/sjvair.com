# TEMPO Query Utilities & API Design

**Date:** 2026-07-12
**Status:** Draft

## Overview

Finalizes the "Query Utilities" and "API" sections of `docs/superpowers/specs/2026-07-11-tempo-integration-design.md`, which were fully speced but explicitly deferred pending the ingestion pipeline landing first. This doc makes those sections concrete and buildable: exact function signatures, exact endpoint paths/params, and the specific existing codebase conventions they reuse. No architectural changes from the original doc -- this is detailing, not redesigning.

This closes both halves of the "make TEMPO data available" goal: `queries.py` for direct Python/notebook/data-tooling use, and `camp/api/v2/tempo/` for the frontend and any external API consumer. The API layer calls the same `queries.py` functions data-tooling scripts call directly, so there's exactly one place that knows how to read a value out of a `Granule`'s raster.

## Query Utilities -- `camp/apps/tempo/queries.py`

```python
class STValue(Func):
    function = 'ST_Value'
    output_field = FloatField()

class STClip(Func):
    function = 'ST_Clip'  # raster clipped to a polygon -- input to STSummaryStats for zonal aggregates

class STSummaryStats(Func):
    function = 'ST_SummaryStats'  # composite return, unpacked per-field
```

```python
def point_series(product: str, point: Point, start: datetime, end: datetime) -> list[dict]: ...
def region_series(product: str, polygon: Polygon, start: datetime, end: datetime) -> list[dict]: ...

def value_at_point(product: str, timestamp: datetime, point: Point) -> float | None: ...
def zonal_stats(product: str, timestamp: datetime, polygon: Polygon) -> dict | None: ...
```

`point_series`/`region_series` are the primitives -- everything else, including the API's range endpoints below, is built on them. `value_at_point`/`zonal_stats` are single-hour convenience wrappers kept for the common one-off case (e.g. "what was NO2 at this monitor's coordinates last Tuesday at 2pm"), implemented as `start = end = <snapped timestamp>` calls into the series functions with the single result unwrapped.

- **`point_series(product, point, start, end)`:** one entry per `Granule` with `product` and `timestamp` in `[start, end]` inclusive, ordered by timestamp: `{'timestamp': ..., 'is_final': ..., 'version': ..., 'value': float | None}`. `value` comes from `STValue('raster', 1, point)` (band 1); `None` means that pixel is masked/nodata, not that the hour is missing (a missing hour simply has no entry in the returned list at all -- callers distinguish "no data at this pixel" from "no granule for this hour" by whether the row exists).
- **`region_series(product, polygon, start, end)`:** same shape, but each row is `STSummaryStats(STClip('raster', polygon))` -- clips the raster to `polygon` before aggregating, so stats reflect only pixels inside the boundary: `{'timestamp': ..., 'is_final': ..., 'version': ..., 'count': int, 'sum': float, 'mean': float, 'stddev': float, 'min': float, 'max': float}`. All-`None` stats fields (not a missing row) mean the polygon produced zero valid pixels for that hour -- distinct from the hour being absent entirely.
- **No range cap in `queries.py`.** The 90-day cap described below (`TempoSeriesForm.MAX_RANGE`) is an API-layer concern protecting the live web endpoint from expensive ad-hoc requests -- it does not belong in these functions themselves. Direct Python/notebook callers (the actual "python tools" use case) are trusted to request whatever range they need; forcing a data-tooling script backfilling a year of comparison data to loop in 90-day chunks would be pure friction against its own audience.
- **Timestamp handling:** `value_at_point`/`zonal_stats` snap `timestamp` down to the top of the hour (`.replace(minute=0, second=0, microsecond=0)`) before delegating to the series functions -- matching how `Granule.timestamp` is always stored (ingestion always writes top-of-hour values; see the `2026-07-11` doc's Ingestion section). `point_series`/`region_series` take `start`/`end` as given -- callers passing off-hour bounds simply get whatever granules actually fall in that window, no snapping.
- **Product scope:** all four functions work against all four `Granule.Product` values, including `cldo4`. The "QA-only, not user-facing" note on `cldo4` in the original doc is a statement about the `products/` metadata endpoint (below), not about queryability -- QA/debugging tooling still needs to be able to pull cloud-fraction values directly.

## API -- `camp/api/v2/tempo/`

**Files:** `endpoints.py`, `serializers.py`, `forms.py`, `urls.py`, `tests/` -- wired into `camp/api/v2/urls.py` under `path('tempo/', include('camp.api.v2.tempo.urls', namespace='tempo'))`, following the exact structure of every other app in `camp/api/v2/`. No auth -- matches every other v2 endpoint (none currently apply `permission_classes`).

### Endpoints

| Method + Path | Description |
|---|---|
| `GET /api/2.0/tempo/` | User-facing product metadata: `key`, `label`, `units` (`"molecules/cm²"`), `legend` (color stops). Excludes `cldo4`. |
| `GET /api/2.0/tempo/{product}/granules/` | List of `Granule` rows for one product. Renamed from the original doc's `/grids/` to match the model name (`Granule`, chosen specifically for NASA's own terminology) -- every other app in this API names its list endpoint after its model (`hms/smoke/` → `Smoke`, `ces/` → `CES4`). |
| `GET /api/2.0/tempo/{product}/granules/latest/` | The single most recent `Granule` for one product -- not a paginated list. For the map's default overlay load, mirroring `monitors/{type}/current/`'s existing role for monitor map overlays. |
| `GET /api/2.0/tempo/{product}/point/?latitude=&longitude=&start=&end=` | Point value series via `point_series` -- one entry per hour in `[start, end]`. Renamed from `/value/` for symmetry with `/region/` below -- both endpoints are now named after the geometry parameter they take, not the computation they perform. |
| `GET /api/2.0/tempo/{product}/region/{region_id}/?start=&end=` | Zonal aggregate series over a community boundary via `region_series` -- one summary-stats entry per hour in `[start, end]`. Renamed from `/zonal/?region_id=` -- `region_id` is a required identifier, not an optional filter, so it belongs in the path like every other identifier lookup in this API (`MonitorDetail`'s `<monitor_id>`, `CES4Detail`'s `<tract>`), not as a query param. |

`{product}` is validated against all four `Granule.Product.values` (not just the three user-facing ones) via a `TempoProductMixin.product` cached property, mirroring `monitors/endpoints.py`'s `EntryTypeMixin` -- 404s on an unknown product key.

### `GET /tempo/` -- products metadata

Not queryset-backed -- a plain `generics.Endpoint` (like `camp/api/v2/endpoints.py`'s `CurrentTime`) whose `get()` builds a static list from `camp.apps.tempo.rendering.PRODUCT_COLOR_RANGES` and `Granule.Product.choices`, excluding `cldo4`. `legend` comes from `rendering._level_set_for(product)` -- the same `Level` objects (value/label/color) already used to render preview PNGs, so the API's legend and the map tiles' actual colors can never drift apart.

### `GET /tempo/{product}/granules/`

```python
class GranuleFilter(FilterSet):
    class Meta:
        model = Granule
        fields = {
            'date': ['exact', 'lt', 'lte', 'gt', 'gte'],   # requires annotating/casting timestamp -> date, see plan
            'timestamp': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'is_final': ['exact'],
            'version': ['exact', 'iexact'],
        }
```

Defaults to today's granules, falling back to yesterday if none exist yet -- reuses `hms/endpoints.py`'s `get_default_date_queryset` helper (already generic over any queryset with a `date`-filterable field) when no `date`/`timestamp` filter is present in the request. `paginate = True`, matching every other list endpoint.

Serializer fields: `sqid`, `timestamp`, `is_final`, `version`, `bounds` (GeoJSON, same automatic handling `hms`'s `geometry` field gets), `preview_url` (computed: `lambda g: g.preview.url if g.preview else None`). `raster` is never serialized -- same reasoning as the admin (`GranuleAdmin` already excludes it entirely): it's binary raster data, not meaningful in a JSON response, and PostGIS raster columns don't have a sane default JSON representation.

### `GET /tempo/{product}/granules/latest/`

```python
class GranuleLatest(GranuleMixin, generics.DetailEndpoint):
    def get_object(self):
        granule = self.get_queryset().first()  # queryset already default-to-today/yesterday + Granule.Meta.ordering = ('-timestamp',)
        if granule is None:
            raise Http404('No TEMPO data available yet for this product.')
        return granule
```

Shares `GranuleMixin`/`get_queryset()` (and therefore the same today/yesterday-fallback default and `GranuleSerializer`) with the list endpoint above -- the only difference is `.first()` instead of pagination. The 404 case is a real, if rare, possibility (a fresh environment before the first `fetch_tempo` run, or ingestion broken for more than a day) and the frontend should handle it as "no overlay available" rather than assume this endpoint always returns something.

Placed at `/granules/latest/`, not `/latest/`, so it reads as "the latest of the granules list" -- consistent with `{product}` being the only other thing in the path and avoiding a second top-level noun under `{product}/`.

### Range validation -- shared by `/point/` and `/region/{region_id}/`

```python
class TempoSeriesForm(forms.Form):
    start = forms.DateTimeField(required=False)
    end = forms.DateTimeField(required=False)

    MAX_RANGE = timedelta(days=90)  # matches sync_tempo_reprocessing's existing rolling-window convention

    def clean(self):
        cleaned_data = super().clean()
        start, end = cleaned_data.get('start'), cleaned_data.get('end')

        # Naive -> aware, same as MonitorAtForm.clean_timestamp
        if start is not None and timezone.is_naive(start):
            start = make_aware(start, tz=settings.DEFAULT_TIMEZONE)
        if end is not None and timezone.is_naive(end):
            end = make_aware(end, tz=settings.DEFAULT_TIMEZONE)

        # Only one bound given -> treat as a single-hour query (mirrors the
        # old single `timestamp=` param without a separate field for it).
        if start is None and end is not None:
            start = end
        elif end is None and start is not None:
            end = start

        if start is not None and end is not None:
            if start > end:
                raise forms.ValidationError('start must be before end.')
            if end - start > self.MAX_RANGE:
                raise forms.ValidationError(f'Maximum range is {self.MAX_RANGE.days} days.')

        cleaned_data['start'], cleaned_data['end'] = start, end
        return cleaned_data
```

If both `start` and `end` are omitted, the endpoint falls back to today (falling back to yesterday if today has no granules yet) -- the same default-to-today behavior as `/granules/`, applied directly in `get_queryset`/`get` rather than in the form, since "today" isn't a fixed value a form default can express. A 400 (`ValidationError`) is returned for a range over 90 days, not a silent truncation -- same pattern as `EntryExportForm.clean()`'s `MAX_EXPORT_RANGE` check.

**Not paginated** -- the 90-day cap already bounds the response to a small number of rows (at TEMPO's hourly-daylight cadence, roughly 90 x 11 ≈ 990 rows worst case), so pagination would add complexity without solving a real problem here.

### `GET /tempo/{product}/point/`

```python
class TempoPointForm(LatLonForm, TempoSeriesForm):  # camp.utils.forms.LatLonForm -- reused as-is
    pass
```

Uses `latitude`/`longitude`, not the original doc's `?lat=&lon=` shorthand -- `LatLonForm` is the established convention (already used by `monitors/endpoints.py`'s `ClosestMonitor`), and reusing it directly means this endpoint gets the same `-90..90`/`-180..180` validation for free.

A plain `generics.Endpoint` (not a `ListEndpoint` -- there's no `Granule` queryset+serializer here, just a list of dicts from `point_series`), whose `get()` validates the form, resolves the `start`/`end` default-to-today case if both are omitted, and returns `point_series(self.product, form.point, start, end)` directly (`self.product` from `TempoProductMixin`) -- resticus wraps a plain list/dict return the same way `CurrentTime` does.

Response: `[{"timestamp": ..., "is_final": ..., "version": ..., "value": float | null}, ...]`.

### `GET /tempo/{product}/region/{region_id}/`

`region_id` resolved via `Region.objects.select_related('boundary').get(sqid=region_id)`, raising `Http404` if missing or if the region has no boundary -- same manual-lookup-then-404 pattern as `monitors/endpoints.py`'s `MonitorsAt` region handling and `hms/filters.py`'s `filter_region_id`. Uses `TempoSeriesForm` directly (no subclass needed -- `region_id` comes from the URL path, not the query string, so there's nothing to add to it) for `start`/`end` validation and defaulting.

Response: `[{"timestamp": ..., "is_final": ..., "version": ..., "count": ..., "sum": ..., "mean": ..., "stddev": ..., "min": ..., "max": ...}, ...]`.

## Testing

Split the same way the rest of the codebase splits app-internal logic from its API layer:

- `camp/apps/tempo/tests/test_queries.py` -- `point_series`, `region_series`, `value_at_point`, `zonal_stats`. Lives alongside this app's existing `test_parsing.py`/`test_raster.py`/`test_rendering.py`, since `queries.py` is an app-internal module, not part of the API. Fixtures build `Granule` rows with a small known raster (e.g. a 3x3 grid with hand-picked values) so results are checked against hand-computed expected numbers, not merely "returned a float." Coverage explicitly includes: exact-hour match, off-hour timestamp snapping down correctly (single-hour wrappers), a multi-hour range returning entries in timestamp order, an hour with no granule simply absent from the list (vs. a masked-pixel `None` value/stats present in the list), point/polygon entirely outside the grid, and a polygon straddling masked and valid pixels.
- `camp/api/v2/tempo/tests/test_endpoints.py`, `test_serializers.py`, `test_forms.py` -- mirrors `hms`/`ces`'s test layout exactly. Covers HTTP-level concerns the query-utility tests don't: product-path 404s, the `/granules/` default-to-today fallback and its filters, the single-bound-mirrors-to-a-point-query form behavior, and the 400 raised for a >90-day range.

Plain `assert` throughout, no `self.assertFoo()`.

## Deferred (unchanged from the 2026-07-11 doc except where noted)

- ~~`GET /api/2.0/monitors/{id}/tempo/{product}/` (time-series comparison endpoint)~~ -- **no longer deferred.** `/tempo/{product}/point/` now returns a timestamp range directly, which covers this need; a dedicated monitor-scoped endpoint is still deferred (a caller with a monitor's lat/lon can already hit `/point/` directly), but the underlying capability this item was waiting on now exists.
- Feeding TEMPO into the `summaries` app -- still deferred, separate future decision.
