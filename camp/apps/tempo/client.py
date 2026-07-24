import time
from datetime import datetime
from typing import Optional

import requests

from constance import config as constance_config

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
        self.token = token or constance_config.EARTHDATA_TOKEN or settings.EARTHDATA_TOKEN
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
