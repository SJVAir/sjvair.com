# Location Groups and Valley-wide Locations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `regions/meta/` gains `location_groups` and a `group` per location type, and `pesticides/locations/` with no area and no bbox returns every current location.

**Architecture:** The grouping is a `Location.Group` `TextChoices` plus a `Location.TYPE_GROUPS` mapping on the model, served by `RegionMetaEndpoint` the way `monitors/meta/` serves `monitor_groups`. `LocationListBase.get` skips the spatial filter when it gets neither an area nor a non-blank bbox. Everything else stays as it is.

**Tech Stack:** Django, django-resticus, PostGIS, pytest.

**Spec:** `docs/superpowers/specs/2026-11-22-location-groups-design.md`

## Global Constraints

- Additive only: existing `regions/meta/` keys and values don't change; `location_types` keys stay the type ids.
- Group keys are permanent: `school`, `child_care`. Labels are "Schools" and "Child care", wrapped in `gettext_lazy` (`_`) like `Location.SHORT_TYPES`. Order is the enum order (0, 1).
- `pesticides/locations/` requests that work today must return byte-for-byte the same bodies. Only the no-area, no-bbox case (a 400 today) changes. `cache_key_version` stays 3.
- No migration. `TextChoices` added to a model class without a field change produce no migration. Check with `makemigrations --check`.
- No Claude/AI attribution in commits. No `Co-Authored-By` or `Claude-Session` lines. Commits are GPG-signed. On "No passphrase given", stop and ask the user. Never commit unsigned.
- Never use `git stash`. Stage by path.
- Tests run in a private PostGIS container, never on the shared Postgres (see Test Commands).

## Test Commands

One-time setup, from the worktree `/home/alex/workspace/sjvair/sjvair.com/.worktrees/location-groups`:

```bash
podman network create locgroups-net
podman run -d --name locgroups-db --network locgroups-net --network-alias db \
  -e POSTGRES_USER=sjvair -e POSTGRES_PASSWORD=changeme -e POSTGRES_DB=sjvair \
  docker.io/postgis/postgis:17-3.5
```

Run tests (`<target>` is a path or node id):

```bash
podman run --rm --network locgroups-net --env-file .env.test -e BAM_MIRROR_ENABLED=0 -e TWILIO_AUTH_TOKEN=test-token -v /home/alex/workspace/sjvair/sjvair.com/.worktrees/location-groups:/app:z -w /app sjvair-com-test:latest pytest <target> -v
```

A single "fatal: not a git repository" line is harmless. Teardown at the end: `podman rm -f locgroups-db && podman network rm locgroups-net`.

## Review Focus

- An empty `bbox=` (as a form might send) should mean the valley, not a 400. Pinned in Task 2's valley test.
- `county=` alone (no bbox) should return that county's sites. It was a 400 before. Pinned in Task 2.
- A retired location must stay out of the valley-wide list, just as it does with a bbox. Pinned in Task 2.
- A bad area (`region=nope`, bad lat) must still be a 400 and not fall through to the valley. Covered by the existing `test_a_bad_area_is_a_bad_request`.
- The valley answer is cached apart from bbox answers. The cache key is the query string, and the existing `test_cached` pattern is pinned for the no-params case in Task 2.

---

### Task 1: Location groups in `regions/meta/`

**Files:**
- Modify: `camp/apps/regions/models.py` (in `class Location`, after `SHORT_TYPES`, ~line 363)
- Modify: `camp/api/v2/regions/endpoints.py` (`RegionMetaEndpoint`, ~lines 393–409)
- Test: `camp/api/v2/regions/tests.py` (`RegionMetaTests`, ~line 109)
- Modify: `CLAUDE.md` (the "Regions" bullet that describes `regions/meta/`, ~line 410, plus the doubled "the" in "Bulk monitor type", ~lines 423–425)

**Interfaces:**
- Produces: `Location.Group` (`TextChoices`: `SCHOOL = 'school'`, `CHILD_CARE = 'child_care'`) and `Location.TYPE_GROUPS: dict[Location.Type, Location.Group]`. Also `RegionMetaEndpoint.get_location_groups() -> dict`.

- [ ] **Step 1: Write the failing test.** Replace `test_location_types` and add `test_location_groups`:

```python
def test_location_types(self):
    response, content = self._fetch_region_meta()
    assert content['data']['location_types'] == {
        'public_school': {'type': 'public_school', 'label': 'Public school', 'source': 'cde-public', 'group': 'school'},
        'private_school': {'type': 'private_school', 'label': 'Private school', 'source': 'cde-private', 'group': 'school'},
        'child_care': {'type': 'child_care', 'label': 'Child care', 'source': 'cdss-ccl', 'group': 'child_care'},
    }

def test_location_groups(self):
    response, content = self._fetch_region_meta()
    groups = content['data']['location_groups']
    assert groups == {
        'school': {'key': 'school', 'label': 'Schools', 'order': 0},
        'child_care': {'key': 'child_care', 'label': 'Child care', 'order': 1},
    }
    # Every type's group is a listed group.
    assert {t['group'] for t in content['data']['location_types'].values()} == set(groups)
```

- [ ] **Step 2: Run the tests and confirm they fail.** Target: `camp/api/v2/regions/tests.py::RegionMetaTests`. Expected: the two tests FAIL (no `group` key, no `location_groups` key).

- [ ] **Step 3: Implement.**
  - Add `class Group(models.TextChoices)` to `Location`, with a comment that the keys are permanent and that it serves `regions/meta/` `location_groups`.
  - Add `TYPE_GROUPS`: `PUBLIC_SCHOOL` and `PRIVATE_SCHOOL` map to `SCHOOL`, and `CHILD_CARE` maps to `CHILD_CARE`.
  - In the endpoint, `get_location_types` adds `'group': Location.TYPE_GROUPS[location_type].value` to each row.
  - Add `get_location_groups()`, shaped like `get_monitor_groups` in `camp/api/v2/monitors/endpoints.py:207`, enumerating `Location.Group`.
  - `get()` adds `'location_groups': self.get_location_groups()`.

- [ ] **Step 4: Run the tests and confirm they pass.** Run the same target. Expected: all `RegionMetaTests` PASS.

- [ ] **Step 5: Confirm there's no migration.** Run `python manage.py makemigrations --check --dry-run` in the same container command. Replace `pytest <target> -v` with that command. Expected: "No changes detected".

- [ ] **Step 6: Update `CLAUDE.md`.**
  - In the "Regions" bullet, after the `buffers` sentence, document `location_groups` (`school` "Schools", `child_care` "Child care"; `{key, label, order}`; ids permanent; from `Location.Group`), and say each `location_types` row carries `group` (`Location.TYPE_GROUPS`).
  - Fix "(`?type=purpleair&type=airnow`, the / the catalog's" so "the" appears once, and re-wrap that line to the paragraph's width (≤ ~100 chars).

- [ ] **Step 7: Commit.**

```bash
git add camp/apps/regions/models.py camp/api/v2/regions/endpoints.py camp/api/v2/regions/tests.py CLAUDE.md
git commit -m "Regions meta: location groups"
```

### Task 2: Valley-wide `pesticides/locations/`

**Files:**
- Modify: `camp/api/v2/pesticides/locations.py` (`LocationListBase.get`, ~lines 63–77; module comment at ~line 18; `LocationList` docstring)
- Test: `camp/api/v2/pesticides/tests.py` (`LocationEndpointTests`, ~lines 1571–1745)
- Modify: `CLAUDE.md` (add a bullet for `pesticides/locations/` under Metadata Endpoints, after "Pesticide notices by day")

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: no new names. Behaviour only: with no area and a missing or blank `bbox`, no spatial filter is applied.

- [ ] **Step 1: Capture the explorer pin from the base code (not committed).**
  - Write `/tmp/claude-1000/-home-alex-workspace-sjvair-sjvair-com/c70b6f32-094f-4a49-af18-e5b8b569d6e1/scratchpad/pin/test_pin.py` (`<scratch>/pin` below). It defines `PinTests(LocationEndpointTests)`, and only `PinTests::test_capture` runs, selected by node id.
  - `test_capture` GETs each of these and writes `status` plus the raw `response.content` to `$PIN_OUT` as JSON lines:
    - `bbox=-119.9,36.6,-119.7,36.8`
    - `bbox=-120.0,35.0,-119.0,37.0&county=fresno`
    - `bbox=-123,33,-115,39&type=public_school,private_school`
    - `bbox=-127,30,-114,43`
    - `bbox=-119.9,36.6`
    - `bbox=-119.9,36.6,-119.7,36.8&type=nope`
    - `region=<county sqid>`
    - `lat=36.71&lng=-119.79&radius=1`
  - Mount the scratch dir at `/pin` and run on the base commit, before any edit: `... -v <scratch>/pin:/pin:z -e PIN_OUT=/pin/base.jsonl ... pytest /pin/test_pin.py::PinTests::test_capture -p no:cacheprovider`. The test DB is fresh each run, so pks and sqids are stable.

- [ ] **Step 2: Write the failing tests.** Replace `test_missing_bbox_is_a_400` with:

```python
def test_no_area_and_no_bbox_is_the_whole_valley(self):
    everyone = ['Alpha Elementary', 'Bravo Child Care', 'Charlie Academy']
    assert [f['properties']['name'] for f in self.features()] == everyone
    assert [f['properties']['name'] for f in self.features(bbox='')] == everyone

def test_valley_takes_type_and_county(self):
    assert [f['properties']['name'] for f in self.features(type='child_care')] == ['Bravo Child Care']
    assert [f['properties']['name'] for f in self.features(county='kern')] == ['Charlie Academy']

def test_valley_leaves_out_retired_locations(self):
    self.daycare.retire(timezone.localdate())
    assert [f['properties']['name'] for f in self.features()] == ['Alpha Elementary', 'Charlie Academy']

def test_valley_is_cached(self):
    assert len(self.features()) == 3
    Location.objects.all().delete()
    assert len(self.features()) == 3
```

- [ ] **Step 3: Run the tests and confirm they fail.** Target: `camp/api/v2/pesticides/tests.py::LocationEndpointTests`. Expected: the four new tests FAIL with a 400 "bbox is required". The rest PASS.

- [ ] **Step 4: Implement.**
  - In `LocationListBase.get`, when `area is None` and `params.get('bbox')` is falsy, leave `bbox = None` instead of returning the 400.
  - Apply `point__bboverlaps` only when `bbox` is set.
  - Keep the bbox parse, the size cap and every other path byte-identical.
  - Update the module comment: the cap is not about size, because the table is valley-only (2,782 rows locally).
  - Update the `LocationList` docstring: no area and no bbox returns every location; `type` and `county` still apply.

- [ ] **Step 5: Run the tests and confirm they pass.** Run the same target. Expected: all `LocationEndpointTests` PASS.

- [ ] **Step 6: Check the pin against the branch, and prove the pin works.**
  - Re-run Step 1's command with `PIN_OUT=/pin/branch.jsonl`, then `cmp base.jsonl branch.jsonl`. Expected: no output (identical).
  - Prove the pin can fail:
    - Copy the edited `locations.py` to `<scratch>/pin/locations.branch.py`.
    - Write the base file over it: `git show origin/develop:camp/api/v2/pesticides/locations.py > camp/api/v2/pesticides/locations.py`.
    - Run with `PIN_OUT=/pin/restored.jsonl`. `cmp` against `base.jsonl` must show no difference.
    - Change `'type_label': str(location.short_type)` to `'type_label': ''` and run with `PIN_OUT=/pin/broken.jsonl`. `cmp` against `base.jsonl` must report a difference.
  - Copy `locations.branch.py` back into place, then re-run Step 5.

- [ ] **Step 7: Update `CLAUDE.md`.** Add a bullet **Pesticide locations** for `pesticides/locations/`:
  - It takes `bbox` (≤ 12° a side), or `region` (+ `buffer`), or `lat`/`lng`/`radius`.
  - With none of these (a blank `bbox` counts as missing), it returns every current location: the whole valley, ~2,800 rows, ~1.5 MB uncompressed, ~195 KB gzipped.
  - `type` (comma list) and `county` (slug) always filter.
  - It's cached for 24 h per query string (`cache_key_version` 3).
  - Requests that send a bbox or an area are unchanged.

- [ ] **Step 8: Commit.**

```bash
git add camp/api/v2/pesticides/locations.py camp/api/v2/pesticides/tests.py CLAUDE.md
git commit -m "Pesticide locations: no area and no bbox is the whole valley"
```

### Task 3: Full suite, real numbers, PR

- [ ] **Step 1: Run the full suite.** Use the private container: `pytest -n 4 --dist loadscope`. Expected: all pass. Report the totals.
- [ ] **Step 2: Check the local stack, read-only (outside :40–:50).** This runs the shared checkout's code, so it only re-confirms the row count and size already in the spec. The shared stack is not switched to this branch.
- [ ] **Step 3: Push, then open a PR into `develop`.**
  - In the PR body, state both shapes and say there is no migration, cache step or backfill.
  - Note that the DEFERRED "doubled the" item is fixed and the command-examples item isn't touched.
  - No attribution line.
- [ ] **Step 4: Wait for CI, then tell `data-dashboard-62`.** Check `gh pr checks <n>`, then send the PR number and status to `data-dashboard-62`. Merging waits for the user's yes in this session.
- [ ] **Step 5: Tear down the private test container and network.**
