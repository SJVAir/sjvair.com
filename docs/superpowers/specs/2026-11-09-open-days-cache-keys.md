# Open days: JSON-safe cache keys (spec and plan)

## Problem

With the Django debug toolbar on (`DEBUG` only), the first request to a monitor
open-days endpoint (`monitors/<id>/summaries/<type>/daily/open/`,
`monitors/<type>/summaries/daily/open/`) after each 60 s cache expiry is a 500.

The toolbar's cache panel records the raw arguments of every cache call and
JSON-encodes them. `cached_open_rows` calls `cache.set(key, {owner_pk: [rows]})`.
Monitor pks are `SmallUUID`s, and `json.dumps` accepts only str, int, float, bool
or None as dict keys; the toolbar encoder's `str()` fallback covers values, not
keys. Region pks are ints, so region endpoints are unaffected, and the unsaved
rows in the values encode through the fallback. A cache hit only calls `get`,
whose return value isn't recorded, so a retry within 60 s succeeds.

## Fix

- `cached_open_rows` caches `{str(pk): rows}` and maps the cached value back to
  the caller's own `owner_ids` on the way out. Its return value is unchanged
  (`{owner_pk: [rows]}`, owners without rows absent), so `build_open_rows`, the
  four callers in `camp/api/v2/summaries/endpoints.py` and the response shape
  stay as they are.
- The cache-key prefix becomes `open_days:v2:`, so an entry cached in the old
  shape is never read back (a `SmallUUID` and its str don't match as dict keys,
  which would answer empty for up to 60 s after a deploy).
- No settings, migrations or toolbar configuration change.

## Plan

1. Test first (`camp/apps/summaries/test_open_days.py`, `CachedOpenRowsTests`):
   on a monitor cache miss, capture the value passed to `cache.set` and
   `json.dumps` it with an encoder that falls back to `str()` for values, like
   the toolbar's. Fails before the fix with the same `TypeError`.
2. Implement the fix and the prefix bump in `camp/apps/summaries/open_days.py`.
3. Run the open-days tests, the summaries endpoint tests, then the full suite.
