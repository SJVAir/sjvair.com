# TEMPO CMR Version Resolution Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix a live-discovered correctness bug in `camp/apps/tempo/client.py`'s `find_granule` (it can silently return an older NASA algorithm version instead of the newest one for historical dates that have been reprocessed), and use the fix to make `sync_granule` skip downloading entirely when nothing has changed — which also unblocks the weekly reprocessing-sync task that was deferred in the original ingestion plan.

**Architecture:** `TempoClient.find_granule` resolves the specific newest-available CMR *collection* for a product (each NASA algorithm version is a separate collection with its own `concept_id`), rather than searching an unversioned short name whose cross-version tie-break is undocumented and was confirmed non-deterministic by direct testing. This also gives `find_granule` a version string *before* any download happens, so `sync_granule` can decide whether to replace the stored `Granule` before fetching anything from Harmony — not just before writing to the database, as it did before.

**Tech Stack:** Same as the original ingestion plan (`docs/superpowers/plans/2026-07-11-tempo-ingestion.md`) — this plan modifies `camp/apps/tempo/client.py` and `camp/apps/tempo/sync.py` (both already implemented and reviewed) and adds to `camp/apps/tempo/tasks.py`.

## Global Constraints

- Tests use plain `assert` statements, not `self.assertFoo()`; use `pytest.raises` for exceptions.
- Timezone is always America/Los_Angeles; use `camp/utils/datetime.py` helpers rather than hand-rolling tz math.
- This plan modifies existing, already-reviewed files — preserve their existing conventions (docstring style, type hints) rather than introducing new patterns.

## Background (why this plan exists)

While revisiting the previously-blocked Task 9 (weekly reprocessing-sync, from the original ingestion plan), a live CMR query found that `find_granule`'s `_search_collection` — which searches by `short_name` alone — is ambiguous for any historical date that NASA has reprocessed to a newer algorithm version. Confirmed directly: for 2023-09-01 (which has both a V03 and V04 granule with identical `time_start`), a `short_name`-only search with `sort_key=-start_date, page_size=1` returned the **older V03 granule**, not V04. NASA mints a separate CMR collection (its own `concept_id`) per algorithm version under the same short name — confirmed via a live collections search: `TEMPO_NO2_L3` has `C2930763263-LARC_CLOUD` (V03) and `C3685896708-LARC_CLOUD` (V04) as distinct collections.

This is a real bug in already-implemented, already-reviewed code (not yet merged to `main` — still on the open PR branch), independent of Task 9. It also happens to be exactly what Task 9 needed: once `find_granule` resolves a specific collection and returns its version, `sync_granule` can compare versions *before* downloading anything, making both routine syncing and the weekly reprocessing re-check cheap in the common (unchanged) case.

---

### Task 1: Fix `client.py` — resolve a specific collection instead of searching by short name

**Files:**
- Modify: `camp/apps/tempo/client.py`
- Modify: `camp/apps/tempo/tests/test_client.py`

**Interfaces:**
- Produces: `TempoClient._resolve_collections(short_name: str) -> list[dict]` — each dict is `{'concept_id': str, 'version_id': str}`, sorted newest-first.
- Changes: `find_granule`'s return dict now includes a `'version': str` key (the resolved collection's `version_id`) alongside the existing `concept_id`/`granule_id`/`collection_concept_id`/`is_final` keys.
- Renames: `_search_collection(short_name, timestamp, bbox)` → `_search_granule_in_collection(collection_concept_id, timestamp, bbox)` (now takes a specific collection, not a short name).

- [ ] **Step 1: Write the failing tests**

Replace the contents of `camp/apps/tempo/tests/test_client.py`'s `FindGranuleTests` class and add a new `ResolveCollectionsTests` class. The `FetchGranuleBytesTests` class at the bottom of the file is unaffected by this task — leave it as-is.

```python
from unittest.mock import MagicMock, patch

import pytest
import requests

from django.test import TestCase, override_settings

from datetime import datetime, timezone as dt_timezone

from camp.apps.tempo.client import TempoClient, _collection_cache


def make_response(status_code=200, json_result=None, content=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_result
    response.content = content
    response.raise_for_status = MagicMock()
    return response


@override_settings(EARTHDATA_TOKEN='test-token')
class ResolveCollectionsTests(TestCase):
    def setUp(self):
        self.client = TempoClient()
        _collection_cache.clear()

    @patch.object(TempoClient, '_get')
    def test_sorts_newest_version_first(self, mock_get):
        mock_get.return_value = make_response(json_result={
            'feed': {'entry': [
                {'id': 'C-V03', 'version_id': 'V03'},
                {'id': 'C-V04', 'version_id': 'V04'},
            ]}
        })

        collections = self.client._resolve_collections('TEMPO_NO2_L3')

        assert [c['version_id'] for c in collections] == ['V04', 'V03']
        assert [c['concept_id'] for c in collections] == ['C-V04', 'C-V03']

    @patch.object(TempoClient, '_get')
    def test_caches_result_across_calls(self, mock_get):
        mock_get.return_value = make_response(json_result={
            'feed': {'entry': [{'id': 'C-V04', 'version_id': 'V04'}]}
        })

        self.client._resolve_collections('TEMPO_NO2_L3')
        self.client._resolve_collections('TEMPO_NO2_L3')

        assert mock_get.call_count == 1


@override_settings(EARTHDATA_TOKEN='test-token')
class FindGranuleTests(TestCase):
    def setUp(self):
        self.client = TempoClient()
        self.timestamp = datetime(2023, 8, 15, 18, 0, tzinfo=dt_timezone.utc)
        self.bbox = (-121.5, 34.9, -117.9, 38.0)

    @patch.object(TempoClient, '_search_granule_in_collection')
    @patch.object(TempoClient, '_resolve_collections')
    def test_returns_granule_from_newest_collection(self, mock_resolve, mock_search):
        mock_resolve.return_value = [
            {'concept_id': 'C-V04', 'version_id': 'V04'},
            {'concept_id': 'C-V03', 'version_id': 'V03'},
        ]
        mock_search.return_value = {'id': 'G1', 'collection_concept_id': 'C-V04'}

        granule = self.client.find_granule('no2', self.timestamp, self.bbox)

        assert granule == {
            'concept_id': 'G1',
            'granule_id': 'G1',
            'collection_concept_id': 'C-V04',
            'is_final': True,
            'version': 'V04',
        }
        mock_search.assert_called_once_with('C-V04', self.timestamp, self.bbox)

    @patch.object(TempoClient, '_search_granule_in_collection')
    @patch.object(TempoClient, '_resolve_collections')
    def test_falls_back_to_older_collection_when_newest_has_no_granule_yet(self, mock_resolve, mock_search):
        mock_resolve.return_value = [
            {'concept_id': 'C-V04', 'version_id': 'V04'},
            {'concept_id': 'C-V03', 'version_id': 'V03'},
        ]
        mock_search.side_effect = [None, {'id': 'G1', 'collection_concept_id': 'C-V03'}]

        granule = self.client.find_granule('no2', self.timestamp, self.bbox)

        assert granule['version'] == 'V03'
        assert granule['is_final'] is True
        assert mock_search.call_count == 2

    @patch.object(TempoClient, '_search_granule_in_collection')
    @patch.object(TempoClient, '_resolve_collections')
    def test_falls_back_to_nrt_when_no_standard_collection_has_a_granule(self, mock_resolve, mock_search):
        def resolve_side_effect(short_name):
            if short_name == 'TEMPO_NO2_L3':
                return [{'concept_id': 'C-V04', 'version_id': 'V04'}]
            return [{'concept_id': 'C-NRT-V02', 'version_id': 'V02'}]
        mock_resolve.side_effect = resolve_side_effect
        mock_search.side_effect = [None, {'id': 'G1', 'collection_concept_id': 'C-NRT-V02'}]

        granule = self.client.find_granule('no2', self.timestamp, self.bbox)

        assert granule['is_final'] is False
        assert granule['version'] == 'V02'

    @patch.object(TempoClient, '_search_granule_in_collection')
    @patch.object(TempoClient, '_resolve_collections')
    def test_o3tot_never_checks_nrt_since_none_exists(self, mock_resolve, mock_search):
        mock_resolve.return_value = [{'concept_id': 'C-V04', 'version_id': 'V04'}]
        mock_search.return_value = None

        granule = self.client.find_granule('o3tot', self.timestamp, self.bbox)

        assert granule is None
        mock_resolve.assert_called_once_with('TEMPO_O3TOT_L3')

    @patch.object(TempoClient, '_search_granule_in_collection')
    @patch.object(TempoClient, '_resolve_collections')
    def test_returns_none_when_nothing_found_anywhere(self, mock_resolve, mock_search):
        mock_resolve.return_value = [{'concept_id': 'C-V04', 'version_id': 'V04'}]
        mock_search.return_value = None

        granule = self.client.find_granule('no2', self.timestamp, self.bbox)

        assert granule is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/tempo/tests/test_client.py -v`
Expected: FAIL — `ResolveCollectionsTests` fails with `AttributeError: 'TempoClient' object has no attribute '_resolve_collections'`; `FindGranuleTests` fails because `_search_granule_in_collection` doesn't exist yet (the old `_search_collection` does, but nothing calls the new name).

- [ ] **Step 3: Implement**

Replace `camp/apps/tempo/client.py` in full:

```python
import time
from datetime import datetime
from typing import Optional

import requests

from django.conf import settings

CMR_GRANULE_SEARCH_URL = 'https://cmr.earthdata.nasa.gov/search/granules.json'
CMR_COLLECTION_SEARCH_URL = 'https://cmr.earthdata.nasa.gov/search/collections.json'
HARMONY_BASE_URL = 'https://harmony.earthdata.nasa.gov'

# NASA collection short names for each product's Level 3 product, standard
# (science-quality) and NRT variants. Confirmed via a live CMR collection
# search on 2026-07-11. o3tot has no NRT collection in NASA's catalog --
# its 'nrt' entry is None, and find_granule skips the fallback search
# rather than querying a nonexistent collection.
COLLECTION_SHORT_NAMES = {
    'no2':   {'standard': 'TEMPO_NO2_L3',   'nrt': 'TEMPO_NO2_L3_NRT'},
    'o3tot': {'standard': 'TEMPO_O3TOT_L3', 'nrt': None},
    'hcho':  {'standard': 'TEMPO_HCHO_L3',  'nrt': 'TEMPO_HCHO_L3_NRT'},
    'cldo4': {'standard': 'TEMPO_CLDO4_L3', 'nrt': 'TEMPO_CLDO4_L3_NRT'},
}

# Module-level (not per-instance) so the cache survives across the many
# short-lived TempoClient() instances that sync_granule() creates in a
# single task run -- fetch_tempo/fetch_tempo_final/import_tempo don't pass
# a shared client between calls. Collection versions change on the order
# of months; a short TTL just avoids pinning a stale list forever in a
# long-running Huey worker process.
_collection_cache: dict = {}
_COLLECTION_CACHE_TTL = 3600  # seconds


class TempoClient:
    def __init__(self, token=None):
        self.token = token or settings.EARTHDATA_TOKEN
        self.session = self._make_session()

    def _make_session(self):
        session = requests.Session()
        session.headers.update({'Authorization': f'Bearer {self.token}'})
        return session

    def _get(self, url, **kwargs):
        return self.session.get(url, **kwargs)

    def _resolve_collections(self, short_name: str) -> list:
        """
        Returns every CMR collection matching `short_name` -- NASA mints a
        separate collection (its own concept_id) per algorithm version
        under the same short name -- sorted by version_id descending
        (newest first). Cached in-process; see _collection_cache above.
        """
        now = time.monotonic()
        cached = _collection_cache.get(short_name)
        if cached is not None:
            expires_at, collections = cached
            if now < expires_at:
                return collections

        response = self._get(CMR_COLLECTION_SEARCH_URL, params={'short_name': short_name, 'page_size': 20})
        response.raise_for_status()
        entries = response.json().get('feed', {}).get('entry', [])
        collections = sorted(
            ({'concept_id': e['id'], 'version_id': e['version_id']} for e in entries),
            key=lambda c: c['version_id'],
            reverse=True,
        )
        _collection_cache[short_name] = (now + _COLLECTION_CACHE_TTL, collections)
        return collections

    def _search_granule_in_collection(self, collection_concept_id: str, timestamp: datetime, bbox: tuple) -> Optional[dict]:
        params = {
            'collection_concept_id': collection_concept_id,
            'temporal': f'{timestamp.isoformat()},{timestamp.isoformat()}',
            'bounding_box': ','.join(str(v) for v in bbox),
            'page_size': 1,
        }
        response = self._get(CMR_GRANULE_SEARCH_URL, params=params)
        response.raise_for_status()
        entries = response.json().get('feed', {}).get('entry', [])
        return entries[0] if entries else None

    def find_granule(self, product: str, timestamp: datetime, bbox: tuple) -> Optional[dict]:
        """
        Resolves the newest available collection for `product`'s standard
        tier and searches it for a granule at `timestamp`; falls back to
        older standard-tier collections (for historical dates NASA hasn't
        reprocessed yet), then to the NRT collection (if one exists --
        o3tot has none). An unversioned short-name search is deliberately
        NOT used here: confirmed via a live CMR query that it can return
        an older algorithm version for a date where multiple versions
        exist, since CMR's tie-break on identical timestamps is
        undocumented (and was non-deterministic-in-practice when tested).
        """
        names = COLLECTION_SHORT_NAMES[product]

        for collection in self._resolve_collections(names['standard']):
            entry = self._search_granule_in_collection(collection['concept_id'], timestamp, bbox)
            if entry is not None:
                return {
                    'concept_id': entry['id'],
                    'granule_id': entry['id'],
                    'collection_concept_id': collection['concept_id'],
                    'is_final': True,
                    'version': collection['version_id'],
                }

        if names['nrt'] is not None:
            for collection in self._resolve_collections(names['nrt']):
                entry = self._search_granule_in_collection(collection['concept_id'], timestamp, bbox)
                if entry is not None:
                    return {
                        'concept_id': entry['id'],
                        'granule_id': entry['id'],
                        'collection_concept_id': collection['concept_id'],
                        'is_final': False,
                        'version': collection['version_id'],
                    }

        return None

    def fetch_granule_bytes(self, granule: dict, bbox: tuple) -> bytes:
        """
        Requests a Harmony spatial subset of `granule`, clipped to `bbox`.
        For a single-granule request like this, Harmony resolves
        synchronously: the response is a redirect straight to the
        subsetted netCDF4 file (confirmed via a live request on
        2026-07-11), not an async job requiring polling.
        """
        collection_id = granule['collection_concept_id']
        url = f'{HARMONY_BASE_URL}/{collection_id}/ogc-api-coverages/1.0.0/collections/all/coverage/rangeset'
        params = {
            'granuleId': granule['granule_id'],
            'subset': [
                f'lat({bbox[1]}:{bbox[3]})',
                f'lon({bbox[0]}:{bbox[2]})',
            ],
            'format': 'application/x-netcdf4',
        }
        response = self._get(url, params=params, allow_redirects=True)
        response.raise_for_status()
        return response.content
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm test pytest camp/apps/tempo/tests/test_client.py -v`
Expected: 9 passed (2 `ResolveCollectionsTests` + 5 `FindGranuleTests` + the pre-existing 2 `FetchGranuleBytesTests` still passing untouched).

- [ ] **Step 5: Commit**

```bash
git add camp/apps/tempo/client.py camp/apps/tempo/tests/test_client.py
git commit -m "fix(tempo): resolve a specific CMR collection instead of an ambiguous short-name search"
```

---

### Task 2: Fix `sync.py` — skip the download entirely when nothing has changed

**Files:**
- Modify: `camp/apps/tempo/sync.py`
- Modify: `camp/apps/tempo/tests/test_sync.py`

**Interfaces:**
- Consumes: `find_granule`'s new `'version'` key (Task 1) — `_should_replace` is now checked using `granule_meta['version']`, before `client.fetch_granule_bytes`/`parse_granule` are ever called, rather than after.
- `_should_replace`'s own logic (tier-first, then version-string comparison) is unchanged.

- [ ] **Step 1: Write the failing tests**

Replace the contents of `camp/apps/tempo/tests/test_sync.py` in full:

```python
from datetime import datetime, timezone as dt_timezone
from unittest.mock import MagicMock, patch

from django.test import TestCase

from camp.apps.tempo.models import Granule
from camp.apps.tempo.parsing import GranuleData
from camp.apps.tempo.sync import sync_granule


FIXED_BBOX = (-121.5, 34.9, -117.9, 38.0)


def make_granule_data(version='V03'):
    import numpy as np
    return GranuleData(
        array=np.array([[1.0e16, 2.0e16], [3.0e16, 4.0e16]]),
        lon_min=-120.0, lat_min=36.96, lon_max=-119.96, lat_max=37.0,
        version=version,
    )


def make_granule_meta(concept_id='G1', collection_id='C1', is_final=True, version='V03'):
    return {
        'concept_id': concept_id, 'granule_id': concept_id,
        'collection_concept_id': collection_id, 'is_final': is_final, 'version': version,
    }


@patch('camp.apps.tempo.sync.load_region_geometry')
class SyncGranuleTests(TestCase):
    def setUp(self):
        self.timestamp = datetime(2023, 8, 15, 18, 0, tzinfo=dt_timezone.utc)

    def _mock_geometry(self, mock_load_region_geometry):
        geometry = MagicMock()
        geometry.bounds = FIXED_BBOX
        mock_load_region_geometry.return_value = geometry

    @patch('camp.apps.tempo.sync.parse_granule')
    def test_creates_new_granule(self, mock_parse, mock_load_region_geometry):
        self._mock_geometry(mock_load_region_geometry)
        mock_parse.return_value = make_granule_data(version='V03')

        client = MagicMock()
        client.find_granule.return_value = make_granule_meta(is_final=False, version='V03')
        client.fetch_granule_bytes.return_value = b'raw-bytes'

        result = sync_granule('no2', self.timestamp, client=client)

        assert result is not None
        assert Granule.objects.filter(product='no2', timestamp=self.timestamp).count() == 1
        assert result.version == 'V03'
        assert result.is_final is False

    def test_returns_none_when_nasa_has_no_granule(self, mock_load_region_geometry):
        self._mock_geometry(mock_load_region_geometry)

        client = MagicMock()
        client.find_granule.return_value = None

        result = sync_granule('no2', self.timestamp, client=client)

        assert result is None
        assert Granule.objects.count() == 0
        client.fetch_granule_bytes.assert_not_called()

    @patch('camp.apps.tempo.sync.parse_granule')
    def test_skips_without_fetching_when_already_up_to_date(self, mock_parse, mock_load_region_geometry):
        self._mock_geometry(mock_load_region_geometry)
        mock_parse.return_value = make_granule_data(version='V03')

        client = MagicMock()
        client.find_granule.return_value = make_granule_meta(is_final=True, version='V03')
        client.fetch_granule_bytes.return_value = b'raw-bytes'

        sync_granule('no2', self.timestamp, client=client)  # first sync: creates V03
        result = sync_granule('no2', self.timestamp, client=client)  # second sync: still V03

        assert result is None
        assert Granule.objects.filter(product='no2', timestamp=self.timestamp).count() == 1
        # The whole point of CMR-based version resolution: the second call
        # already knows from find_granule() alone that nothing has changed,
        # so it never downloads or parses anything.
        assert client.fetch_granule_bytes.call_count == 1
        assert mock_parse.call_count == 1

    @patch('camp.apps.tempo.sync.parse_granule')
    def test_replaces_when_nasa_version_is_newer(self, mock_parse, mock_load_region_geometry):
        self._mock_geometry(mock_load_region_geometry)

        client = MagicMock()
        client.fetch_granule_bytes.return_value = b'raw-bytes'

        client.find_granule.return_value = make_granule_meta(is_final=True, version='V03')
        mock_parse.return_value = make_granule_data(version='V03')
        sync_granule('no2', self.timestamp, client=client)

        client.find_granule.return_value = make_granule_meta(is_final=True, version='V04')
        mock_parse.return_value = make_granule_data(version='V04')
        result = sync_granule('no2', self.timestamp, client=client)

        assert result is not None
        assert result.version == 'V04'
        assert Granule.objects.filter(product='no2', timestamp=self.timestamp).count() == 1
        assert client.fetch_granule_bytes.call_count == 2

    @patch('camp.apps.tempo.sync.parse_granule')
    def test_standard_replaces_nrt_regardless_of_version_numbers(self, mock_parse, mock_load_region_geometry):
        self._mock_geometry(mock_load_region_geometry)

        client = MagicMock()
        client.fetch_granule_bytes.return_value = b'raw-bytes'

        client.find_granule.return_value = make_granule_meta(is_final=False, version='V02')
        mock_parse.return_value = make_granule_data(version='V02')
        sync_granule('no2', self.timestamp, client=client)

        client.find_granule.return_value = make_granule_meta(is_final=True, version='V01')  # lower version string, but standard tier
        mock_parse.return_value = make_granule_data(version='V01')
        result = sync_granule('no2', self.timestamp, client=client)

        assert result is not None
        assert result.is_final is True
        assert result.version == 'V01'

    @patch('camp.apps.tempo.sync.parse_granule')
    def test_nrt_never_replaces_existing_standard_data(self, mock_parse, mock_load_region_geometry):
        self._mock_geometry(mock_load_region_geometry)

        client = MagicMock()
        client.fetch_granule_bytes.return_value = b'raw-bytes'

        client.find_granule.return_value = make_granule_meta(is_final=True, version='V03')
        mock_parse.return_value = make_granule_data(version='V03')
        sync_granule('no2', self.timestamp, client=client)

        client.find_granule.return_value = make_granule_meta(is_final=False, version='V99')  # even a "higher" NRT version must not win
        result = sync_granule('no2', self.timestamp, client=client)

        assert result is None
        stored = Granule.objects.get(product='no2', timestamp=self.timestamp)
        assert stored.is_final is True
        assert stored.version == 'V03'
        assert client.fetch_granule_bytes.call_count == 1  # only the first (accepted) sync ever fetched
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/tempo/tests/test_sync.py -v`
Expected: FAIL — `test_skips_without_fetching_when_already_up_to_date` and `test_nrt_never_replaces_existing_standard_data` fail on `assert client.fetch_granule_bytes.call_count == 1` (currently 2, since the existing code always fetches before checking the version).

- [ ] **Step 3: Implement**

In `camp/apps/tempo/sync.py`, move the `_should_replace` check to before the fetch, and use `granule_meta['version']` instead of `parsed.version` for it:

```python
def sync_granule(product: str, timestamp: datetime, client: Optional[TempoClient] = None) -> Optional[Granule]:
    """
    Finds the best-available NASA granule for (product, timestamp) and
    compares its version against what's stored -- without downloading
    anything yet, since find_granule()'s CMR-based version resolution
    (see client.py) makes this comparison possible before any Harmony
    fetch. Only downloads and replaces the Granule row if NASA's version
    is actually newer than what we have. Returns the Granule if it was
    created/updated, or None if NASA has no granule for that hour, or if
    what's stored is already up to date.
    """
    client = client or TempoClient()
    bbox = load_region_geometry().bounds  # (lon_min, lat_min, lon_max, lat_max)

    granule_meta = client.find_granule(product, timestamp, bbox)
    if granule_meta is None:
        return None

    existing = Granule.objects.filter(product=product, timestamp=timestamp).first()
    if not _should_replace(existing, granule_meta['is_final'], granule_meta['version']):
        return None

    raw_bytes = client.fetch_granule_bytes(granule_meta, bbox)
    parsed = parse_granule(raw_bytes, product)

    raster = build_raster(parsed.array, parsed.lon_min, parsed.lat_min, parsed.lon_max, parsed.lat_max)
    bounds = Polygon.from_bbox((parsed.lon_min, parsed.lat_min, parsed.lon_max, parsed.lat_max))
    preview_bytes = render_preview(parsed.array, product)

    granule, _created = Granule.objects.update_or_create(
        product=product,
        timestamp=timestamp,
        defaults={
            'version': parsed.version,
            'is_final': granule_meta['is_final'],
            'raster': raster,
            'bounds': bounds,
        },
    )
    granule.preview.save(
        f'{product}_{timestamp:%Y%m%dT%H%M}.png',
        ContentFile(preview_bytes),
        save=True,
    )
    return granule
```

Note `parsed.version` (from the downloaded file's own `processing_version` attribute) is still what gets stored in the database — `granule_meta['version']` (from CMR) is only used for the pre-download decision. They should normally agree; if they ever don't, the file's own version is the ground truth for what was actually ingested.

`_should_replace` itself does not change.

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm test pytest camp/apps/tempo/tests/test_sync.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add camp/apps/tempo/sync.py camp/apps/tempo/tests/test_sync.py
git commit -m "fix(tempo): skip download+parse when find_granule already shows nothing changed"
```

---

### Task 3: Implement the weekly reprocessing-sync task (previously blocked Task 9)

**Files:**
- Modify: `camp/apps/tempo/tasks.py`
- Modify: `camp/apps/tempo/tests/test_tasks.py`

**Interfaces:**
- Consumes: `sync_granule` (now cheap to call repeatedly per Task 2 above), `Granule.Product.choices`.

This was blocked in the original ingestion plan because `sync_granule` had no way to check NASA's version without downloading and parsing the full granule, which would have made a 90-day rolling weekly re-scan ~8,640 mostly-wasted Harmony downloads/week. Task 1 and Task 2 above resolve that: `find_granule` now returns a version from a lightweight CMR search, and `sync_granule` skips the download entirely when nothing has changed. This task is otherwise unchanged from what was originally planned for Task 9.

- [ ] **Step 1: Write the failing test**

Add to `camp/apps/tempo/tests/test_tasks.py`:

```python
from camp.apps.tempo.tasks import sync_tempo_reprocessing


class SyncTempoReprocessingTests(TestCase):
    @patch('camp.apps.tempo.tasks.sync_granule')
    def test_resyncs_rolling_90_day_window_for_every_product(self, mock_sync):
        sync_tempo_reprocessing.call_local()

        assert mock_sync.call_count == 90 * 24 * len(Granule.Product.choices)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm test pytest camp/apps/tempo/tests/test_tasks.py::SyncTempoReprocessingTests -v`
Expected: FAIL with `ImportError: cannot import name 'sync_tempo_reprocessing'`

- [ ] **Step 3: Implement**

Add to `camp/apps/tempo/tasks.py`:

```python
# Re-syncs a rolling 90-day window weekly to pick up NASA's non-chronological
# V03->V04 reprocessing. sync_granule() is cheap even when nothing has
# changed: find_granule() resolves the current best-available version via a
# lightweight CMR search and sync_granule() compares it against what's
# stored *before* deciding whether to download anything, so most of this
# 90-day window is a no-op check, not a Harmony fetch.
@db_periodic_task(crontab(day_of_week='0', hour='4', minute='0'), priority=30)
def sync_tempo_reprocessing():
    end = timezone.now().replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=90)
    timestamp = start
    while timestamp <= end:
        for product in PRODUCTS:
            sync_granule(product, timestamp)
        timestamp += timedelta(hours=1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm test pytest camp/apps/tempo/tests/test_tasks.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add camp/apps/tempo/tasks.py camp/apps/tempo/tests/test_tasks.py
git commit -m "feat(tempo): add weekly rolling-window reprocessing sync"
```

---

## Self-Review Notes

**Spec coverage:**
- CMR per-collection version resolution, replacing the ambiguous short-name search — Task 1. ✅
- `sync_granule` skips download when unchanged, using the new pre-download version — Task 2. ✅
- Weekly reprocessing-sync (previously blocked Task 9) — Task 3. ✅

**Placeholder scan:** no TBD/TODO markers; every step has complete, runnable code.

**Type consistency:** `find_granule`'s return dict (`concept_id`, `granule_id`, `collection_concept_id`, `is_final`, `version`) is produced in Task 1 and consumed in Task 2 with exactly those keys. `_resolve_collections`'s list-of-dicts shape (`concept_id`, `version_id`) is produced and consumed consistently within `client.py`. `sync_tempo_reprocessing` (Task 3) calls `sync_granule` with the same `(product, timestamp)` signature used throughout the rest of the app.

**Interaction with the existing PR:** this plan's three tasks all modify code from the original `docs/superpowers/plans/2026-07-11-tempo-ingestion.md` (Tasks 4 and 6) that is already committed on the open PR branch (not yet merged to `main`). No new files are created except test additions to already-existing test files; no migration changes.
