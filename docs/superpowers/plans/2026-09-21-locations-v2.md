# Locations v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** A generic `regions.Location` with county/city/zipcode/school-district links resolved from its point; CDE's authoritative public and private school datasets imported without manual downloads; district pages that group their schools and show who goes to school there.

**Spec:** `docs/superpowers/specs/2026-09-21-locations-v2-design.md` (read fully; "Global constraints" bind).

## Global Constraints
See the spec. Worktree `/home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+pesticides-explorer` only; stage by name; no AI attribution; do not push; Django TestCase + plain assert; `invoke styles` for Sass.

---

### Task 1: Location model rework
**Files:** `camp/apps/regions/models.py`, new migration (RenameField `district`→`school_district`, AddField `city`, `zipcode`, `city_name`; keep the old `related_name` off — use the spec's), `camp/apps/regions/admin.py`, `camp/apps/regions/tests/test_locations.py`, plus every caller of `.district`/`district_for`: `camp/apps/regions/locations.py`, `camp/api/v2/pesticides/locations.py` (+ tests: rename properties per spec §4 and add `city`, `enrollment`), `camp/apps/pesticides/places.py` (`schools_nearby` filter), `camp/templates/pesticides/place.html`/`includes/schools-table.html`, `assets/js/pesticides/section-map.js` (`school_district_url`), existing tests in `camp/apps/pesticides/tests/test_places.py`, `camp/api/v2/pesticides/tests.py`, `camp/apps/regions/tests/test_import_locations.py`.
**Interfaces produced:** `Location.resolve_regions()`, point-change-aware `save()`, accessors per spec §1, `Location.school_district`.
- [ ] Failing tests: resolve_regions sets all four FKs from fixture geometry (create a city, a CDP overlapping it, a zipcode, two overlapping districts — unified preferred); save() re-resolves when the point moves and not when only the name changes (assert query counts); accessors; API property names.
- [ ] Implement; `makemigrations regions` (exclude the unrelated commodities drift).
- [ ] `docker compose run --rm test pytest camp/apps/regions camp/api/v2/pesticides camp/apps/pesticides -q` green. Commit `refactor(regions): Location links to county, city, ZIP and school district from its point`.

### Task 2: CDE sources via CKAN, `import_schools`
**Files:** `camp/apps/regions/locations.py` (new `parse_cde_public` for the 2025-26 point CSV, new `parse_cde_private` for the 2024-25 CSV incl. EPSG:3857 → 4326 via `django.contrib.gis.geos.Point(x, y, srid=3857).transform(4326)`; both sources get `ckan_dataset` and drop `--path`-only status; public-school district cross-check per spec §2), `camp/apps/regions/management/commands/import_locations.py` (help text), new `camp/apps/regions/management/commands/import_schools.py` (calls `call_command('import_school_districts')` then `import_source('cde-public')`), sample files `camp/apps/regions/tests/data/cde-public-sample.csv` (real header, 8 fictional rows: 5 keepers across two counties incl. a charter run by another district, 1 Closed, 1 exclusively virtual, 1 non-SJV) and `cde-private-sample.csv` (real header, 4 rows: 3 keepers incl. one with a failed geocode Status, 1 enrollment 3), `camp/apps/regions/tests/test_import_locations.py` (replace the old CDE tests), `CLAUDE.md` is NOT touched (deploy notes go in the PR).
- [ ] Failing tests first (filters, metadata shape per spec, coordinates transform, geocode fallback patched, district cross-check tally, idempotence, `import_schools` order via `call_command` patching).
- [ ] Implement; run the real imports against the dev DB: `import_schools`, then `import_locations --source cde-private`, then `--source cdss-ccl`; put the printed counts in the report (expect ~1,500 public schools, a few hundred private, ~1,140 child care).
- [ ] Tests green; commit `feat(regions): CDE public and private schools from data.ca.gov; import_schools`.

### Task 3: district pages
**Files:** `camp/apps/pesticides/places.py` (`schools_nearby` returns two groups: `run_by` and `others`, per spec §3, with the demographics dict from the district Region's metadata), `camp/templates/pesticides/place.html` + `includes/schools-table.html` (two grouped tables with per-group cap/"Show all"; the "Who goes to school here" stat strip using `stat-row` idiom; `title_case_name` only when `location.source == 'cdss-ccl'`), `camp/apps/pesticides/tests/test_places.py`.
- [ ] Failing tests: grouping by administering district code; demographics strip values from fixture district metadata; empty states per group; cdss names title-cased, CDE names verbatim.
- [ ] Implement; `invoke styles` if Sass changes; verify a real district page on :8002 (Clovis Unified, Fresno Unified).
- [ ] Tests green; commit `feat(pesticides): district pages group their schools and show who goes to school there`.
