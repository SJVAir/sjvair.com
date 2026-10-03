# Emissions Phases 2 and 3: Schools Near a Facility, CalEnviroScreen on Region Pages

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two small, separable additions to the Facility Emissions Explorer. **Phase 2 (Tasks 1–4):** every facility page with a trustworthy map point lists the schools and licensed child-care centers within 1,000 ft and within ¼ mile, with distances, and draws them on the facility map; to know which points are trustworthy, `Facility` records where its point came from. **Phase 3 (Tasks 5–8):** every region and near-me page gets a "Community" card summarising the CalEnviroScreen tracts it covers (SB 535 disadvantaged-community share, top-25% tract count, percentile range), tract pages show their own scores, facility pages say which tract percentile they sit in, and the admin coverage reports stop averaging in the −999 "no score" tracts.

**Architecture:**
- **Point provenance (Phase 2).** `Facility.point_source` (`census` / `carb` / `maptiler` / `legacy` / blank) is written by everything that writes `Facility.point`: `geocode.resolve_batch` now yields which geocoder answered, `import_ceidars` records it, `import_carb_locations` records which of `locations.choose_point`'s candidates won, `clean_facility_points` blanks it, `Facility.geocode()` (the admin action) records it. A migration stamps every existing point `legacy`. Only `census` and `carb` are trusted.
- **Proximity (Phase 2).** `camp/apps/emissions/schools.py` is one pure query module: `near(facility)` returns two distance-ordered groups of `regions.Location` rows (serialisable dicts, cached a day per facility) or `None` when the block is hidden. The view passes the result to the template card and, as GeoJSON, to `facility_map_config(nearby=…)`; `facility-map.js` gets a `nearby` source (small dots) and a `nearby-ring` source (a dashed ¼-mile circle) that read from the container's `data-nearby` / `data-ring-miles`.
- **CES summary (Phase 3).** `camp/apps/ces/stats.py` owns the model picker (`current_model()`, moved out of `reports/views.ces_tracts`), the membership rule (centroid inside, or ≥ 10% of the tract's area, in California Albers) and `tract_summary(geometry)` / `tract_record(tract_region)`. `reports/panels.tract_stats` becomes a thin adapter over `tract_summary` keeping its keys. The emissions pages consume it through one include, `emissions/includes/community-card.html`; `areas.RadiusArea` gains a `geometry` for the near-me circle.
- **No new downloads, no new tasks, no new API endpoints.** Phase 2 has one migration; Phase 3 has none.

**Tech Stack:** Django 5 / GeoDjango + PostGIS (`Centroid`, `Area`, `Intersection`, `Transform`, `Distance`, `distance_lte` on geodetic geometry), django-vanilla-views, MapTiler SDK on the map core (`window.SJVAirMaps`, `assets/js/maps/`), Bulma, humanize.

**Spec:** `docs/superpowers/specs/2026-09-28-emissions-data-expansion-design.md`, sections "Phase 2" (lines 289–355) and "Phase 3" (lines 357–437). Research: `.superpowers/research/oilgas-ces-schools.md` Parts B and C.

## Global Constraints

- **Where to work.** Worktree `/home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer` (`<worktree>` below), on the NEW branch the controller names, stacked on `feature/ceidars-explorer` after the dairy region pages plan (`docs/superpowers/plans/2026-09-28-dairy-region-pages.md`) has landed. Use absolute paths and `git -C <worktree>` for every git command. After each commit, verify with `git -C <worktree> log --oneline -1`.
- **Phase 2 and Phase 3 are separate PRs.** Tasks 1–4 are Phase 2, Tasks 5–8 are Phase 3. Nothing in 5–8 imports anything from 1–4; each half must leave the site whole on its own. If the controller ships them on two branches, start Phase 3's branch from the same base, not from Phase 2's tip.
- **Tests** use `django.test.TestCase` with plain `assert`; fixtures `regions.yaml`, `emissions.yaml` (Phase 3 adds `calenviroscreen.yaml`). Existing helpers: `camp/apps/emissions/tests/test_areas.py` (`make`, `AROUND_PLANT`), `test_areas_pages.py` (`map_data`).
- **Test command** (`$TEST <paths>` below):
  `docker compose -f /home/derek/dev/ccac/sjvair.com/docker-compose.yml --project-directory /home/derek/dev/ccac/sjvair.com run --rm -T -e DATABASE_URL=postgis://sjvair:changeme@db:5432/sjvair_phase23 -v /home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer:/app test pytest <paths> -q -p no:cacheprovider --create-db`
  `fatal: not a git repository` in its output is harmless.
- **Asset rebuild** (`$ASSETS` below): the same prefix without `-e`, service `web`, `invoke vendor bundle styles`:
  `docker compose -f /home/derek/dev/ccac/sjvair.com/docker-compose.yml --project-directory /home/derek/dev/ccac/sjvair.com run --rm -T -v /home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer:/app web invoke vendor bundle styles`
  Run `node --check` on any JS touched. `$MANAGE <args>` is the same prefix with `web python manage.py <args>`.
- **Smoke:** `/home/derek/.claude/jobs/d44a9b36/tmp/venv/bin/python scripts/emissions_map_smoke.py --base http://localhost:8003`. The dev server's container is `docker ps --filter publish=8003`; never stop it.
- **Commits:** explicit paths only (`git -C <worktree> add <new files>`, then `git -C <worktree> commit -m "…" -- <every path>`). Never `git add -A`, never `git stash`, never push, no AI attribution or Co-Authored-By trailers. Message style: `feat(emissions): …`, `feat(ces): …`, `refactor(reports): …`, `test(…): …`.
- **Style:** match the surrounding code's comment density and naming. New models/fields: verbose names use `_()` as the first positional arg; don't align `=`. Any new model would use `sqid = SqidsField(alphabet=shuffle_alphabet('emissions.ModelName'))` (these phases add no model). JS is plain ES2017 IIFE, `var`, `'use strict'`.
- **Deploy notes go in the PR description, not CLAUDE.md.** Phase 2: `migrate`, then a one-off `import_carb_locations` (network: Census + CARB PMT) so existing facilities get a real `point_source`; until it runs every existing point is `legacy` and the schools card is hidden everywhere. Phase 3: nothing to run; re-run `import_ces5` when CalEPA finalises the DAC list (existing command).
- **Copy, verbatim from the spec** (quoted in the tasks). The schools caveat paragraph and the CES caveat paragraph go on the About page word for word.
- **Refinements made while planning** (the spec is otherwise followed as written):
  1. The spec's Phase 2 "Model change" says `clean_facility_points` applies `locations.choose_point`. It doesn't: `import_carb_locations` does (`camp/apps/emissions/management/commands/import_carb_locations.py`), and `clean_facility_points` only clears points. So `import_carb_locations` writes `census` / `carb` / keeps the current value, and `clean_facility_points` blanks `point_source` when it clears a point. The Phase 2 deploy step is therefore `import_carb_locations`, not `clean_facility_points`.
  2. The two groups don't overlap: `within_1000ft` is 0–1,000 ft and `within_quarter_mile` is 1,000 ft–¼ mile (1,320 ft). The card's headings are "Within 1,000 ft" and "1,000 ft to ¼ mile"; the empty-state copy is the spec's "None within ¼ mile".
  3. `geocode.resolve_batch` yields `(address, point, source)` triples instead of pairs (its only caller is `import_ceidars`). `source` is `'census'`, `'maptiler'`, or `''` when there's no point.
  4. `tract_summary` also returns `highest` / `lowest` (the scored rows at the two ends of the range, for the card's links), `top` (the five highest scored rows, for county pages) and `label` (the model's verbose name, "CalEnviroScreen 5.0"), and `tract_record(region)` is added for the tract page and the facility line. Percentiles are shown as ordinals ("89th percentile") via humanize's `ordinal` on `floatformat:"0"`.
  5. `containing` is used on a page when `count == 0`: the card then reads "Inside census tract X, at the Nth percentile", which is what a small place or a 1-mile near-me circle gets.

## Review Focus

- **The hidden rules come before any query** (`schools.near`). A facility with `point_source='maptiler'` or `'legacy'`, no point, sector `oil-gas` or `refining-fuels`, or a "various locations" address must return `None`, and the page must render neither the card nor `data-nearby`. Pinned by `HiddenTests` (Task 3) and `test_hidden_for_an_untrusted_point` (Task 4).
- **Distances must be feet on a sphere, not degrees.** `Location.point` is a geodetic geometry (SRID 4326), so Django's `Distance`/`distance_lte` use `ST_DistanceSphere`; if the facility point ever lacks an SRID the numbers come back as degrees. Pinned by the 850–950 ft range asserts in Task 3.
- **The 10% membership rule and −999.** A tract touching a city on a shared border (intersects, overlap 0) must not count; a −999 tract counts toward `count`, `dac_tracts` and population but never toward `scored`, `min_p`, `max_p`, `mean_p`, `top25_tracts`. Pinned by `TractSummaryTests` (Task 5) and `test_no_score_tracts_are_left_out_of_the_average` (Task 6).
- **`reports.tract_stats` keeps its keys and its containing-tract population fallback**; the reports suite must still pass unchanged apart from the one new test. Pinned by running `camp/apps/reports/tests.py` in Task 6.
- **A near-me page's circle** comes from `RadiusArea.geometry` (buffered in California Albers). A 1-mile circle inside one tract must fall to `containing`; a 3-mile circle must count it. Pinned by `test_near_me_card` (Task 7).
- **Templates and `None`.** `ci_score_p` is `None` for −999 rows; every template branch that formats it must guard with `{% if … is not None %}` or the page 500s on `floatformat`.

---

## Part A — Phase 2: Schools and child care near a facility

### Task 1: `Facility.point_source`

**Files:**
- Modify: `camp/apps/emissions/models.py` (`Facility`, lines 46–178)
- Create: `camp/apps/emissions/migrations/0007_facility_point_source.py`
- Modify: `camp/apps/emissions/admin.py` (`FacilityAdmin.list_display` / `list_filter`, lines 93–94; `regeocode_selected`, lines 176–185)
- Modify: `fixtures/emissions.yaml` (the three facilities)
- Test: `camp/apps/emissions/tests/test_models.py`

**Interfaces:**
- Produces: `Facility.PointSource` (TextChoices: `CENSUS='census'`, `CARB='carb'`, `MAPTILER='maptiler'`, `LEGACY='legacy'`), `Facility.TRUSTED_POINT_SOURCES = (PointSource.CENSUS, PointSource.CARB)`, field `Facility.point_source` (`CharField(max_length=16, choices, blank=True, default='')`), property `Facility.has_trusted_point -> bool`, `Facility.geocode()` now sets `point_source` too.

- [ ] **Step 1: Write the failing tests**

Append to `camp/apps/emissions/tests/test_models.py` (inside the existing `Facility` test class that has `test_geocode_sets_point_without_saving`):

```python
    def test_point_source_choices_and_trust(self):
        plant = Facility.objects.get(name='TEST PLANT')
        assert plant.point_source == Facility.PointSource.CENSUS
        assert plant.has_trusted_point
        cement = Facility.objects.get(name='TEST CEMENT')
        assert cement.point_source == Facility.PointSource.CARB and cement.has_trusted_point
        station = Facility.objects.get(name='TEST GAS STATION')
        assert station.point_source == Facility.PointSource.MAPTILER and not station.has_trusted_point
        station.point_source = Facility.PointSource.LEGACY
        assert not station.has_trusted_point
        station.point = None
        station.point_source = Facility.PointSource.CENSUS
        assert not station.has_trusted_point  # no point, whatever the source says
        assert Facility._meta.get_field('point_source').default == ''

    def test_geocode_records_the_geocoder(self):
        facility = Facility.objects.get(pk=2)
        point = Point(-119.0, 35.4, srid=4326)
        with patch('camp.utils.geocode.census', return_value=point):
            assert facility.geocode() is True
        assert facility.point_source == Facility.PointSource.CENSUS
        with patch('camp.utils.geocode.census', return_value=None):
            with patch('camp.utils.geocode.maptiler', return_value=point):
                assert facility.geocode() is True
        assert facility.point_source == Facility.PointSource.MAPTILER
```

- [ ] **Step 2: Run them and watch them fail**

`$TEST camp/apps/emissions/tests/test_models.py` — expect `AttributeError: ... PointSource` / `FieldDoesNotExist`.

- [ ] **Step 3: The field, the choices and the helpers**

In `camp/apps/emissions/models.py`, inside `class Facility`, after the `Sector` choices:

```python
    # Where the map point came from. Only a Census street match or CARB's own
    # coordinates (pmt.py) are trusted for anything that measures from the
    # point (the schools card): a MapTiler result can be a city centroid, and
    # `legacy` is a point from before this field existed, provenance unknown.
    class PointSource(models.TextChoices):
        CENSUS = 'census', _('Census street match')
        CARB = 'carb', _('CARB coordinates')
        MAPTILER = 'maptiler', _('MapTiler')
        LEGACY = 'legacy', _('Legacy (unknown)')

    TRUSTED_POINT_SOURCES = (PointSource.CENSUS, PointSource.CARB)
```

After `point = models.PointField(...)` (line 137):

```python
    point_source = models.CharField(_('Point source'), max_length=16, choices=PointSource.choices, blank=True, default='')
```

After `is_minor_source`:

```python
    @property
    def has_trusted_point(self):
        """A point we'd measure from: one that exists and came from Census or CARB."""
        return self.point is not None and self.point_source in self.TRUSTED_POINT_SOURCES
```

Replace `geocode()`:

```python
    def geocode(self):
        """
        Geocodes the facility address, trying Census first then MapTiler, and
        records which one answered in point_source. Sets self.point on success.
        Returns True/False. Does not save.
        """
        street = self.address.get('street', '')
        city = self.address.get('city', '')
        zipcode = self.address.get('zipcode', '')
        query = f'{street}, {city}, CA {zipcode}'
        for source, geocoder in ((self.PointSource.CENSUS, _geocode.census), (self.PointSource.MAPTILER, _geocode.maptiler)):
            point = geocoder(query)
            if point:
                self.point = point
                self.point_source = source
                return True
        return False
```

- [ ] **Step 4: The migration**

Create `camp/apps/emissions/migrations/0007_facility_point_source.py`:

```python
from django.db import migrations, models


def stamp_legacy(apps, schema_editor):
    """Every point that exists today has unknown provenance."""
    Facility = apps.get_model('emissions', 'Facility')
    Facility.objects.filter(point__isnull=False).update(point_source='legacy')


class Migration(migrations.Migration):
    dependencies = [
        ('emissions', '0006_alter_emissionsrecord_acetaldehyde_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='facility',
            name='point_source',
            field=models.CharField(
                blank=True,
                choices=[('census', 'Census street match'), ('carb', 'CARB coordinates'), ('maptiler', 'MapTiler'), ('legacy', 'Legacy (unknown)')],
                default='',
                max_length=16,
                verbose_name='Point source',
            ),
        ),
        migrations.RunPython(stamp_legacy, migrations.RunPython.noop),
    ]
```

Check for drift: `$MANAGE makemigrations emissions --check --dry-run` must print `No changes detected in app 'emissions'`.

- [ ] **Step 5: Admin and fixture**

`camp/apps/emissions/admin.py`: add `'point_source'` to `FacilityAdmin.list_display` after `'has_point'`, and `'point_source'` to `list_filter`. In `regeocode_selected`, `facility.save(update_fields=['point', 'point_source'])`.

`fixtures/emissions.yaml`: under each facility's `point:` line add `point_source: census` (TEST PLANT), `point_source: maptiler` (TEST GAS STATION), `point_source: carb` (TEST CEMENT).

- [ ] **Step 6: Run the tests**

`$TEST camp/apps/emissions/tests/test_models.py camp/apps/emissions/tests/test_locations.py camp/apps/emissions/tests/test_facility_page.py` — all pass.

- [ ] **Step 7: Commit**

```
git -C <worktree> add camp/apps/emissions/migrations/0007_facility_point_source.py
git -C <worktree> commit -m "feat(emissions): record where each facility's map point came from" -- camp/apps/emissions/models.py camp/apps/emissions/migrations/0007_facility_point_source.py camp/apps/emissions/admin.py fixtures/emissions.yaml camp/apps/emissions/tests/test_models.py
```

---

### Task 2: The point writers record the source

**Files:**
- Modify: `camp/utils/geocode.py` (`resolve_batch`, lines 182–199)
- Modify: `camp/apps/emissions/management/commands/import_ceidars.py` (lines 106–113, 151–162)
- Modify: `camp/apps/emissions/management/commands/import_carb_locations.py` (lines 33–76)
- Modify: `camp/apps/emissions/management/commands/clean_facility_points.py` (line 40)
- Test: `camp/apps/emissions/tests/test_import_ceidars.py`, `camp/apps/emissions/tests/test_pmt.py`, `camp/apps/emissions/tests/test_locations.py`

**Interfaces:**
- Changes: `geocode.resolve_batch(addresses, workers=5, strict=False)` yields `(address, point, source)`; `source` is `'census'`, `'maptiler'` or `''` (no point).
- `import_carb_locations` writes `point_source` alongside `point` (`bulk_update(..., ['point', 'point_source'])`).

- [ ] **Step 1: Write the failing tests**

`camp/apps/emissions/tests/test_import_ceidars.py`: change `geocode_all` and add a MapTiler variant:

```python
def geocode_all(addresses, **kwargs):
    return [(address, POINT, 'census') for address in addresses]


def geocode_maptiler(addresses, **kwargs):
    return [(address, POINT, 'maptiler') for address in addresses]
```

Add to `ImportCeidarsTests`:

```python
    def test_point_source_records_which_geocoder_answered(self):
        self.run_import(county='fresno')
        assert Facility.objects.get(county_code=10, facid=1).point_source == Facility.PointSource.CENSUS
        Facility.objects.all().delete()
        self.run_import(county='fresno', geocode=geocode_maptiler)
        assert Facility.objects.get(county_code=10, facid=1).point_source == Facility.PointSource.MAPTILER

    def test_no_point_means_no_source(self):
        self.run_import(county='fresno', geocode=lambda addresses, **kwargs: [])
        facility = Facility.objects.get(county_code=10, facid=1)
        assert facility.point is None and facility.point_source == ''
```

`camp/apps/emissions/tests/test_pmt.py`, in `ImportCarbLocationsTests`, add one assertion to each of the first three tests:

```python
    def test_census_street_match_beats_carb(self):
        self.run_command(census={'123 MAIN ST': self.CENSUS_PLANT})
        plant = Facility.objects.get(name='TEST PLANT')
        assert plant.point.equals_exact(self.CENSUS_PLANT, 1e-9)
        assert plant.point_source == Facility.PointSource.CENSUS

    def test_carb_beats_a_non_census_point(self):
        output = self.run_command()
        plant = Facility.objects.get(name='TEST PLANT')
        assert plant.point.equals_exact(Point(-119.79, 36.74, srid=4326), 1e-9)
        assert plant.point_source == Facility.PointSource.CARB
        assert 'Updated' in output

    def test_no_carb_point_keeps_the_current_one(self):
        Facility.objects.filter(name='TEST GAS STATION').update(point_source=Facility.PointSource.LEGACY)
        before = Facility.objects.get(name='TEST GAS STATION').point
        self.run_command()
        station = Facility.objects.get(name='TEST GAS STATION')
        assert station.point.equals_exact(before, 1e-9)
        assert station.point_source == Facility.PointSource.LEGACY  # kept, not upgraded
```

And a new one:

```python
    def test_a_source_change_alone_is_written(self):
        # Same point as CARB's, but stamped legacy: the source is corrected even though the point doesn't move.
        Facility.objects.filter(name='TEST PLANT').update(point=Point(-119.79, 36.74, srid=4326), point_source=Facility.PointSource.LEGACY)
        self.run_command()
        assert Facility.objects.get(name='TEST PLANT').point_source == Facility.PointSource.CARB
```

`camp/apps/emissions/tests/test_locations.py`, in `CleanFacilityPointsTests.test_clears_points_outside_the_county`, add after the existing `point is None` assert:

```python
        assert Facility.objects.get(name='TEST PLANT').point_source == ''
```

- [ ] **Step 2: Run them and watch them fail**

`$TEST camp/apps/emissions/tests/test_import_ceidars.py camp/apps/emissions/tests/test_pmt.py camp/apps/emissions/tests/test_locations.py`

- [ ] **Step 3: `geocode.resolve_batch` yields the source**

Replace the function in `camp/utils/geocode.py`:

```python
def resolve_batch(addresses, workers=5, strict=False):
    """
    Geocode a list of address dicts, yielding (address, point, source)
    triples. Census batch runs first; failures fall back to MapTiler
    concurrently. Results are yielded as they become available -- Census hits
    up front, MapTiler results as each finishes. `source` is 'census' or
    'maptiler', or '' when neither found the address (point is None).
    """
    if not addresses:
        return

    fallbacks = []
    for addr, point in census_batch(addresses):
        if point is not None:
            yield addr, point, 'census'
        else:
            fallbacks.append(addr)

    for addr, point in maptiler_batch(fallbacks, workers=workers, strict=strict):
        yield addr, point, 'maptiler' if point is not None else ''
```

- [ ] **Step 4: `import_ceidars` keeps it**

In `import_ceidars.py`, `positions` maps a key to `(point, source)`:

```python
            positions = {}  # (district, facid) -> (Point, source)
            if geocode_index:
                self.status(f'{label}: geocoding {len(geocode_index)} facilities...')
                area = locations.county_area(county)
                addr_to_key = {id(addr): key for key, addr in geocode_index}
                for addr, point, source in geocode.resolve_batch([addr for _, addr in geocode_index]):
                    if locations.plausible(point, area):
                        positions[addr_to_key[id(addr)]] = (point, source)
```

and the two places that assign `facility.point = positions.get(key)` become:

```python
                    facility.point, facility.point_source = positions.get(key, (None, ''))
```

(both the `if created:` branch and the `if regeocode:` branch; the `geocode_failures` counting stays as it is).

- [ ] **Step 5: `import_carb_locations` records which candidate won**

In its `handle()` loop, after `point = locations.choose_point(...)`:

```python
            if point is None:
                counts['none'] += 1
                source = ''
            elif point is census.get(facility.pk):
                counts['census'] += 1
                source = Facility.PointSource.CENSUS
            elif point is carb:
                counts['carb'] += 1
                source = Facility.PointSource.CARB
            else:
                counts['current'] += 1
                source = facility.point_source  # the point it had keeps the provenance it had

            if not self.same(point, facility.point) or source != facility.point_source:
                if not self.same(point, facility.point):
                    distance = self.distance(facility.point, point)
                    if distance is None or distance >= REPORT_METERS:
                        moved.append((facility, distance))
                facility.point = point
                facility.point_source = source
                changed.append(facility)
```

and `Facility.objects.bulk_update(changed, ['point', 'point_source'], batch_size=1000)`. Update the `help` string's last sentence to "Also records where each point came from (point_source). Safe to re-run; run it after import_ceidars."

- [ ] **Step 6: `clean_facility_points` blanks it**

Line 40: `Facility.objects.filter(pk__in=[...]).update(point=None, point_source='')`.

- [ ] **Step 7: Run the tests**

`$TEST camp/apps/emissions/tests/test_import_ceidars.py camp/apps/emissions/tests/test_pmt.py camp/apps/emissions/tests/test_locations.py camp/apps/emissions/tests/test_models.py` — all pass.

- [ ] **Step 8: Commit**

```
git -C <worktree> commit -m "feat(emissions): every point writer records its source" -- camp/utils/geocode.py camp/apps/emissions/management/commands/import_ceidars.py camp/apps/emissions/management/commands/import_carb_locations.py camp/apps/emissions/management/commands/clean_facility_points.py camp/apps/emissions/tests/test_import_ceidars.py camp/apps/emissions/tests/test_pmt.py camp/apps/emissions/tests/test_locations.py
```

---

### Task 3: `schools.near(facility)`

**Files:**
- Create: `camp/apps/emissions/schools.py`
- Create: `camp/apps/emissions/tests/test_schools.py`

**Interfaces:**
- Consumes: `regions.Location` (`point`, `name`, `type`, `short_type`, `sqid`), `Facility.has_trusted_point`, `locations.is_geocodable`.
- Produces (module `camp.apps.emissions.schools`):
  - Constants `NOTICE_FT = 1000`, `QUARTER_MILE_FT = 1320`, `FEET_PER_MILE = 5280`, `SHOWN = 10`, `HIDDEN_SECTORS = (Facility.Sector.OIL_GAS, Facility.Sector.REFINING_FUELS)`, `CACHE_TIMEOUT = 60 * 60 * 24`.
  - `shows_for(facility) -> bool`
  - `near(facility) -> dict | None`: `{'within_1000ft': [row…], 'within_quarter_mile': [row…]}`, each list ordered by distance, every row `{'sqid', 'name', 'type', 'type_label', 'feet', 'lat', 'lng'}` (`feet` an int). `None` when hidden. Cached per facility pk.
  - `geojson(near) -> dict`: a FeatureCollection of the first `SHOWN` rows of each group, `properties` = `name`, `type_label`, `feet`, `group` (`'notice'` / `'quarter'`).

- [ ] **Step 1: Write the failing tests**

Create `camp/apps/emissions/tests/test_schools.py`:

```python
from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.test import TestCase

from camp.apps.emissions import schools
from camp.apps.emissions.models import Facility
from camp.apps.regions.models import Location

# One degree of latitude is about 364,000 ft, so this places a point `feet` north of another to within ~0.3%.
FEET_PER_DEGREE_LAT = 364_000


def north_of(point, feet):
    return Point(point.x, point.y + feet / FEET_PER_DEGREE_LAT, srid=4326)


def location(name, point, type=Location.Type.PUBLIC_SCHOOL):
    return Location.objects.create(name=name, type=type, external_id=name, source='test', point=point)


class SchoolsTestCase(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.plant = Facility.objects.get(name='TEST PLANT')  # point_source census (trusted)
        self.near = location('NEAR ELEMENTARY', north_of(self.plant.point, 900))
        self.nearer = location('NEARER PRESCHOOL', north_of(self.plant.point, 300), Location.Type.CHILD_CARE)
        self.quarter = location('QUARTER MILE ACADEMY', north_of(self.plant.point, 1200), Location.Type.PRIVATE_SCHOOL)
        self.far = location('FAR HIGH', north_of(self.plant.point, 2000))


class NearTests(SchoolsTestCase):
    def test_two_groups_ordered_by_distance(self):
        result = schools.near(self.plant)
        assert [row['name'] for row in result['within_1000ft']] == ['NEARER PRESCHOOL', 'NEAR ELEMENTARY']
        assert [row['name'] for row in result['within_quarter_mile']] == ['QUARTER MILE ACADEMY']
        near = result['within_1000ft'][1]
        assert 850 < near['feet'] < 950 and isinstance(near['feet'], int)
        assert near['type_label'] == 'Public school' and near['sqid'] == self.near.sqid
        assert abs(near['lat'] - self.near.point.y) < 1e-9 and abs(near['lng'] - self.near.point.x) < 1e-9
        assert result['within_1000ft'][0]['type_label'] == 'Child care'
        assert 1150 < result['within_quarter_mile'][0]['feet'] < 1250

    def test_nothing_nearby(self):
        Location.objects.exclude(pk=self.far.pk).delete()
        assert schools.near(self.plant) == {'within_1000ft': [], 'within_quarter_mile': []}

    def test_cached_per_facility(self):
        schools.near(self.plant)
        location('LATECOMER', north_of(self.plant.point, 500))
        assert 'LATECOMER' not in [row['name'] for row in schools.near(self.plant)['within_1000ft']]
        cache.clear()
        assert 'LATECOMER' in [row['name'] for row in schools.near(self.plant)['within_1000ft']]

    def test_geojson_lists_the_shown_rows(self):
        collection = schools.geojson(schools.near(self.plant))
        assert collection['type'] == 'FeatureCollection'
        names = {feature['properties']['name']: feature for feature in collection['features']}
        assert set(names) == {'NEARER PRESCHOOL', 'NEAR ELEMENTARY', 'QUARTER MILE ACADEMY'}
        assert names['NEAR ELEMENTARY']['properties']['group'] == 'notice'
        assert names['QUARTER MILE ACADEMY']['properties']['group'] == 'quarter'
        assert names['NEAR ELEMENTARY']['geometry'] == {'type': 'Point', 'coordinates': [self.near.point.x, self.near.point.y]}

    def test_geojson_stops_at_the_shown_count(self):
        for i in range(12):
            location(f'CROWD {i}', north_of(self.plant.point, 400 + i))
        result = schools.near(self.plant)
        assert len(result['within_1000ft']) == 14
        assert len(schools.geojson(result)['features']) == schools.SHOWN + 1


class HiddenTests(SchoolsTestCase):
    def test_untrusted_or_missing_point(self):
        for source in (Facility.PointSource.MAPTILER, Facility.PointSource.LEGACY, ''):
            self.plant.point_source = source
            assert schools.near(self.plant) is None, source
        self.plant.point_source = Facility.PointSource.CENSUS
        self.plant.point = None
        assert schools.near(self.plant) is None

    def test_oil_gas_and_refining_sectors(self):
        for sector in (Facility.Sector.OIL_GAS, Facility.Sector.REFINING_FUELS):
            self.plant.sector = sector
            assert schools.near(self.plant) is None, sector
        self.plant.sector = Facility.Sector.GLASS
        assert schools.near(self.plant) is not None

    def test_ungeocodable_address(self):
        self.plant.address = {'street': 'VARIOUS LOCATIONS', 'city': 'FRESNO', 'zipcode': ''}
        assert schools.near(self.plant) is None
        self.plant.address = {}
        assert schools.near(self.plant) is None
```

- [ ] **Step 2: Run them and watch them fail**

`$TEST camp/apps/emissions/tests/test_schools.py` — `ModuleNotFoundError`.

- [ ] **Step 3: Write the module**

Create `camp/apps/emissions/schools.py`:

```python
"""
Schools and licensed child-care centers near a facility (regions.Location,
from import_locations), for the facility page's "Schools and child care
nearby" card and its map.

Two distances, each with a basis in state law (see the About page):
1,000 ft is where Health & Safety Code 42301.6 requires the district to
notify parents before permitting a source of hazardous air emissions;
1/4 mile is the distance school districts must review before siting a school
(Education Code 17213). Distances are straight lines between map points.

The block is hidden for a facility whose point can't be trusted to be the
site: no point, a point that isn't a Census street match or CARB's own
coordinates, an oil-gas or refining permit grouping (their addresses are
mailing addresses, not well or terminal locations), or an address that
isn't a place at all ("various locations").
"""

import math

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Polygon
from django.contrib.gis.measure import D
from django.core.cache import cache

from camp.apps.emissions import locations
from camp.apps.emissions.models import Facility
from camp.apps.regions.models import Location

NOTICE_FT = 1000
QUARTER_MILE_FT = 1320
FEET_PER_MILE = 5280
MILES_PER_DEGREE = 69.0
# Listed on the card per group; the rest is "and N more".
SHOWN = 10
HIDDEN_SECTORS = (Facility.Sector.OIL_GAS, Facility.Sector.REFINING_FUELS)
CACHE_VERSION = 1
CACHE_TIMEOUT = 60 * 60 * 24


def shows_for(facility):
    """Whether the facility's point is one worth measuring from."""
    if not facility.has_trusted_point:
        return False
    if facility.sector in HIDDEN_SECTORS:
        return False
    return locations.is_geocodable(facility.address or {})


def _bbox(point, miles):
    """A degree bbox around `point`, slightly generous: the GiST prefilter before the exact distance (see pesticides/places.point_area)."""
    dlat = miles / MILES_PER_DEGREE
    dlng = miles / (MILES_PER_DEGREE * max(math.cos(math.radians(point.y)), 0.01))
    box = Polygon.from_bbox((point.x - dlng, point.y - dlat, point.x + dlng, point.y + dlat))
    box.srid = 4326
    return box


def _rows(facility):
    point = facility.point
    if point.srid is None:
        point.srid = 4326
    # Location.point is a geodetic geometry, so Distance/distance_lte run on the
    # sphere and come back in metres; D(ft=...) converts the threshold.
    candidates = (
        Location.objects
        .filter(point__bboverlaps=_bbox(point, QUARTER_MILE_FT / FEET_PER_MILE), point__distance_lte=(point, D(ft=QUARTER_MILE_FT)))
        .annotate(distance=Distance('point', point))
        .order_by('distance', 'name')
    )
    rows = []
    for location in candidates:
        rows.append({
            'sqid': location.sqid,
            'name': location.name,
            'type': location.type,
            'type_label': str(location.short_type),
            'feet': int(round(location.distance.ft)),
            'lat': location.point.y,
            'lng': location.point.x,
        })
    return rows


def near(facility):
    """
    The schools and child care within 1,000 ft and from there to 1/4 mile of
    the facility's point, each list nearest first, or None when the block is
    hidden (shows_for). Cached a day per facility.
    """
    if not shows_for(facility):
        return None

    def compute():
        rows = _rows(facility)
        return {
            'within_1000ft': [row for row in rows if row['feet'] <= NOTICE_FT],
            'within_quarter_mile': [row for row in rows if row['feet'] > NOTICE_FT],
        }

    return cache.get_or_set(f'emissions:v{CACHE_VERSION}:schools:{facility.pk}', compute, CACHE_TIMEOUT)


def geojson(result):
    """The listed rows (the first SHOWN of each group) as a FeatureCollection for the facility map's `nearby` source."""
    features = []
    for group, key in (('notice', 'within_1000ft'), ('quarter', 'within_quarter_mile')):
        for row in result[key][:SHOWN]:
            features.append({
                'type': 'Feature',
                'geometry': {'type': 'Point', 'coordinates': [row['lng'], row['lat']]},
                'properties': {'name': row['name'], 'type_label': row['type_label'], 'feet': row['feet'], 'group': group},
            })
    return {'type': 'FeatureCollection', 'features': features}
```

If `location.distance` comes back as a plain float (no `.ft`), the facility point had no SRID: check `facility.point.srid` in the test data rather than converting degrees.

- [ ] **Step 4: Run the tests**

`$TEST camp/apps/emissions/tests/test_schools.py` — all pass.

- [ ] **Step 5: Commit**

```
git -C <worktree> add camp/apps/emissions/schools.py camp/apps/emissions/tests/test_schools.py
git -C <worktree> commit -m "feat(emissions): schools and child care within 1,000 ft and a quarter mile of a facility" -- camp/apps/emissions/schools.py camp/apps/emissions/tests/test_schools.py
```

---

### Task 4: The facility page card, the map overlay and the About paragraph

**Files:**
- Modify: `camp/apps/emissions/views.py` (`FacilityDetail.get_context_data`, lines 218–241; `facility_map_config`, lines 308–371)
- Modify: `camp/templates/emissions/facility-detail.html` (the `columns facility-cards` block, lines 29–46)
- Create: `camp/templates/emissions/includes/schools-card.html`
- Modify: `camp/templates/emissions/about.html` (a new `<h2 id="schools">` before `<h2 id="sources">`; two source list items)
- Modify: `assets/js/emissions/facility-map.js` (constants, constructor listeners, `addLayers`, `load`, `legend`, a new `showNearby`)
- Test: `camp/apps/emissions/tests/test_facility_page.py`

**Interfaces:**
- `facility_map_config(..., nearby=None)`: `nearby` is a FeatureCollection dict or `None`; the container gets `data-nearby` (JSON, or `''`) and `data-ring-miles` (`'0.25'`, or `''`).
- Template context: `nearby` (the `schools.near` result or `None`), `nearby_shown` (`schools.SHOWN`).
- JS reads `this.data.nearby` and `this.data.ringMiles`; sources `nearby`, `nearby-ring`; layers `nearby-ring` (line) and `nearby` (circle), drawn above `facilities` and below `outline-mask`.

- [ ] **Step 1: Write the failing tests**

Append to `camp/apps/emissions/tests/test_facility_page.py`:

```python
class SchoolsCardTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        from camp.apps.emissions.tests.test_schools import location, north_of
        self.plant = Facility.objects.get(name='TEST PLANT')
        location('NEAR ELEMENTARY', north_of(self.plant.point, 900))
        location('QUARTER MILE ACADEMY', north_of(self.plant.point, 1200))
        location('FAR HIGH', north_of(self.plant.point, 2000))

    def detail(self, facility):
        return self.client.get(facility.get_absolute_url()).content.decode()

    def test_card_groups_and_map_overlay(self):
        from camp.apps.emissions.tests.test_areas_pages import map_data
        content = self.detail(self.plant)
        card = content[content.index('card-header-title">Schools and child care nearby'):content.index('facility-map map-canvas')]
        assert card.index('Within 1,000 ft') < card.index('NEAR ELEMENTARY') < card.index('1,000 ft to ¼ mile') < card.index('QUARTER MILE ACADEMY')
        assert 'FAR HIGH' not in card
        assert re.search(r'NEAR ELEMENTARY.*?Public school · \d{3} ft', card, re.S)
        assert ' more</p>' not in card  # no "and N more" with one or two rows
        assert map_data(content, 'ring-miles') == '0.25'
        nearby = map_data(content, 'nearby')
        assert 'NEAR ELEMENTARY' in nearby and 'FAR HIGH' not in nearby and '&quot;FeatureCollection&quot;' in nearby
        assert 'href="/tools/emissions/about/#schools"' in card

    def test_none_within_a_quarter_mile(self):
        from camp.apps.regions.models import Location
        Location.objects.exclude(name='FAR HIGH').delete()
        content = self.detail(self.plant)
        assert 'None within ¼ mile.' in content
        assert 'Within 1,000 ft' not in content

    def test_and_n_more(self):
        from camp.apps.emissions.tests.test_schools import location, north_of
        for i in range(11):
            location(f'CROWD {i}', north_of(self.plant.point, 400 + i))
        content = self.detail(self.plant)
        assert 'and 2 more' in content  # 12 within 1,000 ft, 10 shown

    def test_hidden_for_an_untrusted_point(self):
        from camp.apps.emissions.tests.test_areas_pages import map_data
        content = self.detail(Facility.objects.get(name='TEST GAS STATION'))  # point_source maptiler
        assert 'Schools and child care nearby' not in content
        assert map_data(content, 'nearby') == '' and map_data(content, 'ring-miles') == ''

    def test_about_page_explains_the_distances(self):
        from django.urls import reverse
        content = self.client.get(reverse('emissions:about')).content.decode()
        assert '<h2 id="schools">' in content
        assert 'Health &amp; Safety Code 42301.6' in content and 'Education Code 17213' in content
        assert 'Child care covers licensed centers only, not family child-care homes.' in content
```

- [ ] **Step 2: Run them and watch them fail**

`$TEST camp/apps/emissions/tests/test_facility_page.py`

- [ ] **Step 3: The view**

In `camp/apps/emissions/views.py`, import: `from camp.apps.emissions import areas, dairies, schools, stats` and `import json` at the top. In `FacilityDetail.get_context_data`:

```python
        nearby = schools.near(facility)
        return super().get_context_data(
            facility=facility,
            ...
            nearby=nearby,
            nearby_shown=schools.SHOWN,
            map_config=facility_map_config(
                scope, mode='compact', highlight=facility,
                params=scope.params(year=shown_year, minor='1', county=None),
                nearby=schools.geojson(nearby) if nearby else None,
            ),
            **kwargs,
        )
```

In `facility_map_config`, add the keyword `nearby=None` to the signature and two entries to `config` after `'radius': radius,`:

```python
        # The facility page's schools and child care within 1/4 mile (a
        # FeatureCollection, JSON in the attribute) and the ring to draw.
        'nearby': json.dumps(nearby) if nearby else '',
        'ring_miles': schools.QUARTER_MILE_FT / schools.FEET_PER_MILE if nearby else '',
```

Update the docstring's first line to mention `nearby`. (`mapconfig.map_config` stringifies every value, so `0.25` becomes `'0.25'`; the template autoescapes the JSON's quotes to `&quot;`, which the browser decodes before `dataset` sees it.)

- [ ] **Step 4: The card**

Create `camp/templates/emissions/includes/schools-card.html`:

```django
{% load humanize %}
{% comment %}
The facility page's "Schools and child care nearby" card (camp.apps.emissions.schools).
Context: `nearby` (the two groups; the include is skipped when it's None) and
`nearby_shown` (rows listed per group before "and N more").
{% endcomment %}
<div class="card">
    <header class="card-header"><p class="card-header-title">Schools and child care nearby</p></header>
    <div class="card-content">
        {% if nearby.within_1000ft or nearby.within_quarter_mile %}
        {% for heading, rows, more in nearby_groups %}
        {% if rows %}
        <p class="heading{% if not forloop.first %} mt-3{% endif %} mb-1">{{ heading }}</p>
        <ul class="nearby-list">
            {% for row in rows|slice:nearby_shown %}
            <li>{{ row.name }} <span class="has-text-grey is-size-7">{{ row.type_label }} · {{ row.feet|intcomma }} ft</span></li>
            {% endfor %}
        </ul>
        {% if more %}<p class="is-size-7 has-text-grey">and {{ more|intcomma }} more</p>{% endif %}
        {% endif %}
        {% endfor %}
        {% else %}
        <p>None within ¼ mile.</p>
        {% endif %}
        <p class="is-size-7 has-text-grey mt-3">Straight-line distances between map points. <a href="{% url 'emissions:about' %}#schools">Why 1,000 ft and ¼ mile</a></p>
    </div>
</div>
```

Names are shown as the source gives them (CDE and CDSS already title-case them; no `|title`). The "and N more" count is computed in the view, not the template. Add to `views.py`, above `class FacilityDetail`:

```python
def nearby_groups(nearby):
    """(heading, rows, hidden count) per group of schools.near(), for the card's template."""
    if not nearby:
        return []
    return [
        (heading, rows, max(len(rows) - schools.SHOWN, 0))
        for heading, rows in (('Within 1,000 ft', nearby['within_1000ft']), ('1,000 ft to ¼ mile', nearby['within_quarter_mile']))
    ]
```

and pass `nearby_groups=nearby_groups(nearby)` in the context beside `nearby` and `nearby_shown` (`rows|slice:nearby_shown` works with an int: Django's `slice` filter stringifies its argument).

In `facility-detail.html`, inside `<div class="columns facility-cards">`, after the "Where" column's closing `</div>` (line 45) and before the block's closing `</div>` (line 46):

```django
    {% if nearby is not None %}
    <div class="column is-half">
        {% include 'emissions/includes/schools-card.html' %}
    </div>
    {% endif %}
```

- [ ] **Step 5: The About paragraph and sources**

In `camp/templates/emissions/about.html`, before `<h2 id="sources">`:

```django
<h2 id="schools">Schools and child care</h2>
<p>A facility's page lists the public and private schools and licensed child-care centers within 1,000 ft and within ¼ mile of it, from the California Department of Education's school directories and the Department of Social Services' child-care licensing list, and draws them on the facility's map.</p>
<p>Distances are straight lines from the school's map point to the facility's, not from property lines. 1,000 ft is the distance at which state law (Health &amp; Safety Code 42301.6) requires the air district to notify parents before permitting a source of hazardous air emissions; ¼ mile is the distance school districts must review before siting a school (Education Code 17213). Being nearby isn't a measure of exposure. Child care covers licensed centers only, not family child-care homes.</p>
<p>The list is left off a facility whose map point can't be trusted to be the site: oil and gas or refinery permit groupings (their addresses are offices, not wells or terminals) and facilities whose address couldn't be matched to a street.</p>
```

Add to the `<ul>` under `<h2 id="sources">`:

```django
    <li><a href="https://data.ca.gov/dataset/california-public-schools-2025-26">CDE public schools</a>, <a href="https://data.ca.gov/dataset/california-private-schools-2024-25">CDE private schools</a> and <a href="https://data.ca.gov/dataset/community-care-licensing-facilities1">CDSS licensed child-care facilities</a></li>
```

- [ ] **Step 6: The map overlay**

In `assets/js/emissions/facility-map.js`:

Constants (after `AREA_LINE_WIDTH`): `var NEARBY_COLOR = '#2f6f4e';`

Constructor, after the `areas-fill` listeners: `this.map.on('click', 'nearby', function (evt) { self.openNearbyPopup(evt.features[0], evt.lngLat); });` and change the cursor loop to `['facilities', 'areas-fill', 'nearby'].forEach(...)`.

`addLayers`, after the `facilities` layer and before `outline-mask`:

```js
    // The facility page's schools and child care within 1/4 mile: the ring,
    // then the dots (data-nearby / data-ring-miles; camp.apps.emissions.schools).
    this.shell.ensureSource('nearby-ring');
    this.shell.ensureSource('nearby');
    this.shell.ensureLayer({
      id: 'nearby-ring', type: 'line', source: 'nearby-ring',
      paint: { 'line-color': NEARBY_COLOR, 'line-width': 1.5, 'line-dasharray': [2, 2], 'line-opacity': 0.8 },
    });
    this.shell.ensureLayer({
      id: 'nearby', type: 'circle', source: 'nearby',
      paint: { 'circle-radius': 5, 'circle-color': NEARBY_COLOR, 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 1.5 },
    });
```

and at the end of `addLayers`, after `this.applyHighlight();`: `this.showNearby();`. In `load()`, add `this.showNearby();` after `this.loadOutline();` (an adopt re-reads the new page's attributes). New methods, after `showOutline`:

```js
  // The schools and child care listed on a facility page, from the
  // container's own attributes (no fetch): the dots and the 1/4-mile ring
  // around the page's centre. Empty on every other page.
  FacilityMap.prototype.showNearby = function () {
    var collection = M.EMPTY;
    if (this.data.nearby) {
      try { collection = JSON.parse(this.data.nearby); } catch (err) { logError('bad nearby JSON', err); }
    }
    var center = M.parseCenter(this.data.center);
    var miles = parseFloat(this.data.ringMiles);
    this.shell.setSourceData('nearby', collection);
    this.shell.setSourceData('nearby-ring', center && miles > 0
      ? { type: 'Feature', properties: {}, geometry: circle(center, miles) }
      : M.EMPTY);
  };

  FacilityMap.prototype.openNearbyPopup = function (feature, lngLat) {
    var p = feature.properties;
    this.shell.placePopup('<div class="facility-popup">' +
      '<p class="facility-popup-name">' + escapeHtml(p.name) + '</p>' +
      '<p>' + escapeHtml(p.type_label) + ' · ' + Number(p.feet).toLocaleString('en-US') + ' ft away</p>' +
      '</div>', lngLat);
  };
```

In `legend()`, the plain Facilities branch (the final `legend.innerHTML = ...` assignment): append a note when the page has nearby data:

```js
      '<p class="legend-empty"><span class="legend-ring"></span>None reported</p>' +
      (this.data.nearby ? '<p class="legend-note">Green dots: schools and child care within ¼ mile (dashed ring).</p>' : '');
```

Update the file's header comment: add one line under "Modes:" — `On a facility page the schools and child care within 1/4 mile are drawn as dots inside a dashed ring (data-nearby).`

Then: `node --check /home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer/assets/js/emissions/facility-map.js` and `$ASSETS`.

- [ ] **Step 7: Run the tests, then look at it**

`$TEST camp/apps/emissions/tests/test_facility_page.py camp/apps/emissions/tests/test_schools.py camp/apps/emissions/tests/test_views.py` — all pass.

Smoke: run the smoke script (`Global Constraints`); it must still pass. Then open `http://localhost:8003/tools/emissions/facilities/` on the dev server, pick a facility with a trusted point (after Task 2 the dev DB has `point_source` only where `import_carb_locations` has run: run `$MANAGE import_carb_locations` once against the dev DB, or `$MANAGE shell -c "from camp.apps.emissions.models import Facility; Facility.objects.filter(point__isnull=False).update(point_source='census')"` for a look-only stamp) and confirm the card, the dots and the ring render, and a dot's popup opens. Note in the PR that the stamp was look-only if you used it.

- [ ] **Step 8: Commit**

```
git -C <worktree> add camp/templates/emissions/includes/schools-card.html
git -C <worktree> commit -m "feat(emissions): schools and child care nearby on the facility page and its map" -- camp/apps/emissions/views.py camp/templates/emissions/facility-detail.html camp/templates/emissions/includes/schools-card.html camp/templates/emissions/about.html assets/js/emissions/facility-map.js camp/apps/emissions/tests/test_facility_page.py
```

Also commit the rebuilt bundle files if this repo tracks them (check `git -C <worktree> status --short` for changed files under `camp/static/` or wherever `invoke bundle` writes; add them by explicit path in a second commit `build(assets): rebuild the emissions map bundle` only if they're tracked).

**Phase 2 ends here.** PR description: what it shows, the hidden rules, the deploy steps (`migrate`; one-off `import_carb_locations`; until it runs every existing facility is `legacy` and the card is hidden).

---

## Part B — Phase 3: CalEnviroScreen on region pages

### Task 5: `ces.stats`: the model picker, tract membership and the summary

**Files:**
- Create: `camp/apps/ces/stats.py`
- Test: `camp/apps/ces/tests.py` (append)

**Interfaces:**
- Produces (module `camp.apps.ces.stats`):
  - `NO_SCORE = -999`, `MIN_OVERLAP = 0.10`, `TOP_PERCENTILE = 75`, `TOP_N = 5`, `CACHE_TIMEOUT = 60 * 60 * 24`, `CACHE_VERSION = 1`.
  - `current_model() -> (model, version) | (None, None)`: CES5 if it has rows, else CES4, each on its newest `boundary__version`.
  - `member_tracts(geometry, model, version) -> list[record]`: the tracts whose centroid is inside `geometry` or whose intersection covers ≥ `MIN_OVERLAP` of the tract's area (California Albers).
  - `tract_summary(geometry, *, model=None) -> dict | None` with keys `model` (class name), `version`, `label`, `tracts` (rows, highest score first, unscored last), `count`, `scored`, `dac_tracts`, `top25_tracts`, `population`, `dac_population`, `dac_share`, `min_p`, `max_p`, `mean_p`, `highest`, `lowest`, `top`, `containing`. A row is `{'region', 'ci_score_p', 'dac', 'population'}`; `ci_score_p` is `None` for −999/null. `None` when no CES data is loaded. Cached a day per (model, version, geometry hash).
  - `tract_record(region) -> dict | None`: `{'model', 'version', 'label', 'region', 'ci_score_p', 'pollution_p', 'popchar_p', 'dac', 'dac_category'}` for a tract region on the current model, else `None`. Cached a day.

- [ ] **Step 1: Write the failing tests**

Append to `camp/apps/ces/tests.py` (add the imports it needs at the top: `from django.contrib.gis.geos import MultiPolygon, Point, Polygon`, `from django.core.cache import cache`, `from camp.apps.ces import stats`, `from camp.apps.ces.models import CES4, CES5`, `from camp.apps.regions.models import Boundary, Region`):

```python
def bbox(west, south, east, north):
    return MultiPolygon(Polygon.from_bbox((west, south, east, north)), srid=4326)


def make_tract(geoid, west, east, **ces5_fields):
    """A 2020 tract between longitudes west..east, latitude 36.7..36.8 (like the fixture tracts), with a CES5 row."""
    region = Region.objects.create(name=f'Census Tract {geoid[-4:]}', slug=f'tract-{geoid}', type=Region.Type.TRACT, external_id=geoid)
    boundary = Boundary.objects.create(region=region, version='2020', geometry=bbox(west, 36.7, east, 36.8))
    region.boundary = boundary
    region.save(update_fields=['boundary'])
    CES5.objects.create(boundary=boundary, **ces5_fields)
    return region


class TractSummaryTests(TestCase):
    """Fixture tracts: 1.01 is -119.8..-119.7 (89.2, DAC, pop 4650); 1.02 is -119.7..-119.6 (51.0, not DAC, pop 3350)."""
    fixtures = ['regions.yaml', 'calenviroscreen.yaml']

    def setUp(self):
        cache.clear()

    def test_current_model_prefers_ces5_then_ces4(self):
        assert stats.current_model() == (CES5, '2020')
        CES5.objects.all().delete()
        assert stats.current_model() == (CES4, '2020')
        CES4.objects.all().delete()
        assert stats.current_model() == (None, None)
        assert stats.tract_summary(bbox(-119.8, 36.7, -119.6, 36.8)) is None

    def test_a_small_place_falls_to_its_containing_tract(self):
        # Inside tract 1.01 but clear of its centroid (-119.75, 36.75), and 4% of its area.
        summary = stats.tract_summary(bbox(-119.79, 36.71, -119.77, 36.73))
        assert summary['count'] == 0 and summary['tracts'] == [] and summary['scored'] == 0
        assert summary['containing']['region'].external_id == '06019000101'
        assert summary['containing']['ci_score_p'] == 89.2 and summary['containing']['dac'] is True
        assert summary['dac_share'] is None and summary['min_p'] is None

    def test_overlap_rule(self):
        # 5% of tract 1.01 (its centroid is outside): only 1.02 counts.
        summary = stats.tract_summary(bbox(-119.705, 36.7, -119.6, 36.8))
        assert [row['region'].external_id for row in summary['tracts']] == ['06019000102']
        # 40% of tract 1.01: both count, highest first.
        summary = stats.tract_summary(bbox(-119.74, 36.7, -119.6, 36.8))
        assert [row['region'].external_id for row in summary['tracts']] == ['06019000101', '06019000102']
        assert summary['highest']['region'].external_id == '06019000101' and summary['lowest']['region'].external_id == '06019000102'

    def test_a_shared_border_is_not_membership(self):
        # Exactly tract 1.01: 1.02 touches it along one edge (intersects, overlap 0).
        summary = stats.tract_summary(bbox(-119.8, 36.7, -119.7, 36.8))
        assert summary['count'] == 1 and summary['population'] == 4650

    def test_no_score_tracts_count_but_are_not_scored(self):
        make_tract('06019000103', -119.6, -119.5, population=1000, ci_score_p=-999, dac_sb535=True)
        summary = stats.tract_summary(bbox(-119.8, 36.7, -119.5, 36.8))
        assert summary['model'] == 'CES5' and summary['version'] == '2020' and summary['label'] == 'CalEnviroScreen 5.0'
        assert summary['count'] == 3 and summary['scored'] == 2
        assert summary['dac_tracts'] == 2 and summary['dac_population'] == 5650 and summary['population'] == 9000
        assert abs(summary['dac_share'] - 5650 / 9000) < 1e-9
        assert summary['min_p'] == 51.0 and summary['max_p'] == 89.2 and abs(summary['mean_p'] - 70.1) < 1e-9
        assert summary['top25_tracts'] == 1
        assert summary['tracts'][-1]['ci_score_p'] is None  # the unscored tract sorts last
        assert [row['region'].external_id for row in summary['top']] == ['06019000101', '06019000102']

    def test_cached_per_geometry(self):
        geometry = bbox(-119.8, 36.7, -119.6, 36.8)
        assert stats.tract_summary(geometry)['count'] == 2
        CES5.objects.filter(boundary__region__external_id='06019000102').delete()
        assert stats.tract_summary(geometry)['count'] == 2
        cache.clear()
        assert stats.tract_summary(geometry)['count'] == 1

    def test_ces4_when_asked(self):
        summary = stats.tract_summary(bbox(-119.8, 36.7, -119.6, 36.8), model=CES4)
        assert summary['model'] == 'CES4' and summary['max_p'] == 87.9


class TractRecordTests(TestCase):
    fixtures = ['regions.yaml', 'calenviroscreen.yaml']

    def setUp(self):
        cache.clear()

    def test_the_tracts_own_row(self):
        tract = Region.objects.get(external_id='06019000101', type=Region.Type.TRACT)
        record = stats.tract_record(tract)
        assert record['ci_score_p'] == 89.2 and record['pollution_p'] == 83.0
        assert record['dac'] is True and record['dac_category'] == 'Top 25% CES overall score'
        assert record['label'] == 'CalEnviroScreen 5.0' and record['region'] == tract

    def test_not_a_tract_or_no_data(self):
        fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        assert stats.tract_record(fresno) is None
        assert stats.tract_record(None) is None
        tract = Region.objects.get(external_id='06019000101', type=Region.Type.TRACT)
        CES5.objects.all().delete()
        CES4.objects.all().delete()
        assert stats.tract_record(tract) is None
```

- [ ] **Step 2: Run them and watch them fail**

`$TEST camp/apps/ces/tests.py` — `ModuleNotFoundError`.

- [ ] **Step 3: Write the module**

Create `camp/apps/ces/stats.py`:

```python
"""
CalEnviroScreen figures for an area: which tracts a geometry covers and what
they add up to. Shared by the emissions explorer's region, near-me, tract and
facility pages and the admin coverage reports (reports.panels.tract_stats).

OEHHA scores census tracts and ranks them against the rest of California.
Anything here for a city, ZIP or county is SJVAir's summary of the tracts
inside it, not an OEHHA score, and the pages say so.
"""

import hashlib
from statistics import mean

from django.contrib.gis.db.models.functions import Area, Centroid, Intersection, Transform
from django.core.cache import cache

from camp.apps.ces.models import CES4, CES5
from camp.apps.regions.models import Region
from camp.utils.gis import EPSG_CALIFORNIA_ALBERS

# OEHHA's "no score" marker in ci_score_p: tracts with too few people or
# missing indicators. They're real tracts with real populations, so they
# count toward populations and DAC figures, never toward percentile figures.
NO_SCORE = -999
# A tract belongs to a geometry when its centroid is inside it, or when the
# geometry covers at least this share of the tract's area. The centroid rule
# alone drops small places inside big rural tracts (Lost Hills, Arvin).
MIN_OVERLAP = 0.10
TOP_PERCENTILE = 75
TOP_N = 5
CACHE_VERSION = 1
CACHE_TIMEOUT = 60 * 60 * 24


def current_model():
    """(model, tract version) for the newest CES data present: CES5, else CES4, each on its newest tract vintage; (None, None) with none loaded."""
    for model in (CES5, CES4):
        version = (
            model._base_manager.order_by('-boundary__version')
            .values_list('boundary__version', flat=True).first()
        )
        if version:
            return model, version
    return None, None


def _sq_m(value):
    """An Area annotation as square metres (a measure on PostGIS; a bare number elsewhere; None for no row)."""
    if value is None:
        return 0.0
    return float(getattr(value, 'sq_m', value))


def _score(value):
    """A percentile, or None for OEHHA's no-score marker or a null."""
    if value is None or value <= NO_SCORE:
        return None
    return float(value)


def _row(record):
    return {
        'region': record.boundary.region,
        'ci_score_p': _score(record.ci_score_p),
        'dac': record.dac_sb535,
        'population': record.population or 0,
    }


def member_tracts(geometry, model, version):
    """The tracts `geometry` covers (see MIN_OVERLAP), as CES records with their boundary and region loaded."""
    if not geometry.valid:
        geometry = geometry.buffer(0)
    albers = geometry.transform(EPSG_CALIFORNIA_ALBERS, clone=True)
    candidates = (
        model.objects.filter(boundary__version=version, boundary__geometry__intersects=geometry)
        .annotate(
            centroid=Centroid('boundary__geometry'),
            tract_sq_m=Area(Transform('boundary__geometry', EPSG_CALIFORNIA_ALBERS)),
            overlap_sq_m=Area(Intersection(Transform('boundary__geometry', EPSG_CALIFORNIA_ALBERS), albers)),
        )
    )
    members = []
    for record in candidates:
        tract_area = _sq_m(record.tract_sq_m)
        share = _sq_m(record.overlap_sq_m) / tract_area if tract_area else 0
        if geometry.contains(record.centroid) or share >= MIN_OVERLAP:
            members.append(record)
    return members


def _summary(geometry, model, version):
    rows = [_row(record) for record in member_tracts(geometry, model, version)]
    rows.sort(key=lambda row: (row['ci_score_p'] is None, -(row['ci_score_p'] or 0)))
    scored_rows = [row for row in rows if row['ci_score_p'] is not None]
    scores = [row['ci_score_p'] for row in scored_rows]
    population = sum(row['population'] for row in rows)
    dac_population = sum(row['population'] for row in rows if row['dac'])
    containing = None
    if not rows:
        record = model.objects.filter(boundary__version=version, boundary__geometry__contains=geometry.centroid).first()
        if record is not None:
            containing = _row(record)
    return {
        'model': model.__name__,
        'version': version,
        'label': str(model._meta.verbose_name),
        'tracts': rows,
        'count': len(rows),
        'scored': len(scored_rows),
        'dac_tracts': sum(1 for row in rows if row['dac']),
        'top25_tracts': sum(1 for score in scores if score >= TOP_PERCENTILE),
        'population': population,
        'dac_population': dac_population,
        'dac_share': dac_population / population if population else None,
        'min_p': min(scores) if scores else None,
        'max_p': max(scores) if scores else None,
        # Unweighted: population weighting waits for block population.
        'mean_p': mean(scores) if scores else None,
        'highest': scored_rows[0] if scored_rows else None,
        'lowest': scored_rows[-1] if scored_rows else None,
        'top': scored_rows[:TOP_N],
        'containing': containing,
    }


def tract_summary(geometry, *, model=None):
    """
    The CES tracts a geometry covers and what they add up to (see the module
    docstring for the keys), or None when no CES data is loaded. `model`
    defaults to current_model(); passing one uses its newest tract vintage.
    Cached a day per model, vintage and geometry.
    """
    if model is None:
        model, version = current_model()
    else:
        version = (
            model._base_manager.order_by('-boundary__version')
            .values_list('boundary__version', flat=True).first()
        )
    if model is None or not version:
        return None
    digest = hashlib.md5(geometry.ewkb).hexdigest()
    key = f'ces:v{CACHE_VERSION}:summary:{model.__name__}:{version}:{digest}'
    return cache.get_or_set(key, lambda: _summary(geometry, model, version), CACHE_TIMEOUT)


def tract_record(region):
    """One tract's own row on the current model, or None for anything that isn't a scored tract region."""
    if region is None or region.type != Region.Type.TRACT or not region.boundary_id:
        return None
    model, version = current_model()
    if model is None:
        return None

    def compute():
        record = model.objects.filter(boundary_id=region.boundary_id).first()
        if record is None:
            return None
        return {
            'model': model.__name__,
            'version': version,
            'label': str(model._meta.verbose_name),
            'region': region,
            'ci_score_p': _score(record.ci_score_p),
            'pollution_p': _score(record.pollution_p),
            'popchar_p': _score(record.popchar_p),
            'dac': record.dac_sb535,
            'dac_category': str(record.get_dac_category_display()) if record.dac_category else None,
        }

    return cache.get_or_set(f'ces:v{CACHE_VERSION}:tract:{model.__name__}:{region.boundary_id}', compute, CACHE_TIMEOUT)
```

Notes for the implementer: passing the GEOS `albers` geometry straight into `Intersection(...)` is fine — GeoDjango wraps a `GEOSGeometry` argument in a `Value` with a `GeometryField(srid=…)` and transforms it to the first argument's SRID if they differ. `cache.get_or_set` with a `None` result: Django caches `None` only if the default callable returns `None`… it stores it, and `get_or_set` returns the stored `None` on later calls — fine here.

- [ ] **Step 4: Run the tests**

`$TEST camp/apps/ces/tests.py` — all pass.

- [ ] **Step 5: Commit**

```
git -C <worktree> add camp/apps/ces/stats.py
git -C <worktree> commit -m "feat(ces): tract membership and a CalEnviroScreen summary for any geometry" -- camp/apps/ces/stats.py camp/apps/ces/tests.py
```

---

### Task 6: The admin reports use it (and stop averaging −999)

**Files:**
- Modify: `camp/apps/reports/views.py` (`ces_tracts`, lines 188–196; imports line 17)
- Modify: `camp/apps/reports/panels.py` (`tract_stats`, lines 19–43; imports lines 7, 12–15)
- Test: `camp/apps/reports/tests.py` (`CommunityPanelTests`)

**Interfaces:**
- `reports.views.ces_tracts()` keeps its signature `(model, version, queryset) | (None, None, None)` and delegates to `ces.stats.current_model()`.
- `reports.panels.tract_stats(geometry)` keeps its keys (`tracts`, `dac_tracts`, `population`, `dac_population`, `avg_percentile`, `max_percentile`) over `ces.stats.tract_summary`.

- [ ] **Step 1: Write the failing test**

In `camp/apps/reports/tests.py`, `CommunityPanelTests`, add:

```python
    def test_no_score_tracts_are_left_out_of_the_average(self):
        # A -999 ("no score") tract whose centroid is inside Testville: it counts
        # and its people count, but it must not drag the average to -455.
        from camp.apps.ces.models import CES5
        region = Region.objects.create(name='Census Tract 1.03', slug='tract-06019000103', type=Region.Type.TRACT, external_id='06019000103')
        boundary = Boundary.objects.create(region=region, version='2020', geometry=MultiPolygon(Polygon.from_bbox((-119.8, 36.7, -119.75, 36.8))))
        region.boundary = boundary
        region.save(update_fields=['boundary'])
        CES5.objects.create(boundary=boundary, population=1000, ci_score_p=-999, dac_sb535=False)
        context = self.panel(self.testville)
        assert context['tracts']['tracts'] == 2
        assert context['tracts']['population'] == 5650
        assert context['tracts']['avg_percentile'] == 89.2
        assert context['tracts']['max_percentile'] == 89.2
```

(Check the file already imports `Boundary`, `MultiPolygon`, `Polygon` — `make_place` uses them — and that `self.panel` exists in this class; it does at line ~683.)

- [ ] **Step 2: Run it and watch it fail**

`$TEST camp/apps/reports/tests.py -k no_score` — expect `avg_percentile == -454.9`.

- [ ] **Step 3: `ces_tracts` delegates**

In `camp/apps/reports/views.py`, add `from camp.apps.ces import stats as ces_stats` and replace `ces_tracts`:

```python
def ces_tracts():
    """(model, version, tract queryset) for the newest CES data present (ces.stats.current_model), or (None, None, None)."""
    model, version = ces_stats.current_model()
    if model is None:
        return None, None, None
    return model, version, model._base_manager.filter(boundary__version=version)
```

Keep the `CES4, CES5` import only if something else in the file still uses it (grep; if not, remove it).

- [ ] **Step 4: `tract_stats` becomes the adapter**

In `camp/apps/reports/panels.py`, add `from camp.apps.ces import stats as ces_stats` and replace `tract_stats`:

```python
def tract_stats(geometry):
    """
    CES tracts the geometry covers (ces.stats.tract_summary: centroid inside,
    or a tenth of the tract's area), as the panel templates read them. A
    geometry too small to cover a tract reports the population of the tract
    it sits in. -999 "no score" tracts count but aren't averaged.
    """
    empty = {'tracts': 0, 'dac_tracts': 0, 'population': 0, 'dac_population': 0,
             'avg_percentile': None, 'max_percentile': None}
    summary = ces_stats.tract_summary(geometry)
    if summary is None:
        return empty
    population = summary['population']
    if not summary['count'] and summary['containing']:
        population = summary['containing']['population']
    return {
        'tracts': summary['count'],
        'dac_tracts': summary['dac_tracts'],
        'population': population,
        'dac_population': summary['dac_population'],
        'avg_percentile': round(summary['mean_p'], 1) if summary['mean_p'] is not None else None,
        'max_percentile': round(summary['max_p'], 1) if summary['max_p'] is not None else None,
    }
```

Then prune imports that are now unused in `panels.py` (`Avg`, `Max`, `Q`, `Sum`, `Count`, `ces_tracts`, `Centroid` — grep each name in the file before removing it; keep any still used).

- [ ] **Step 5: Run the whole reports suite**

`$TEST camp/apps/reports/tests.py camp/apps/ces/tests.py` — all pass. If a `CoverageCommunityTests` or `CountyPanelTests` expectation changes, stop: the membership rule changed something the spec didn't anticipate; report it rather than editing the assertion.

- [ ] **Step 6: Commit**

```
git -C <worktree> commit -m "refactor(reports): CES tract stats come from ces.stats and ignore no-score tracts" -- camp/apps/reports/views.py camp/apps/reports/panels.py camp/apps/reports/tests.py
```

---

### Task 7: The Community card on region, near-me and tract pages

**Files:**
- Modify: `camp/apps/emissions/areas.py` (`RadiusArea`, lines 226–261; a `METERS_PER_MILE` constant)
- Modify: `camp/apps/emissions/views.py` (`AreaPage.get_context_data`, `RegionPage.get_context_data`, `NearMe.get_context_data`)
- Create: `camp/templates/emissions/includes/community-card.html`
- Modify: `camp/templates/emissions/area.html` (section nav, line 12–16; a new include after the stat row, line 31)
- Test: `camp/apps/emissions/tests/test_areas.py` (one test), new `camp/apps/emissions/tests/test_community_card.py`

**Interfaces:**
- `areas.RadiusArea.geometry -> Polygon` (WGS84): the circle, buffered in California Albers.
- Context on every area page: `community` (a `tract_summary` dict or `None`), `tract_ces` (a `tract_record` dict or `None`, tract pages only), `show_top_tracts` (`True` on county pages).
- The include renders whichever of `community` / `tract_ces` is set; it renders nothing when both are `None`.

- [ ] **Step 1: Write the failing tests**

Append to `camp/apps/emissions/tests/test_areas.py`:

```python
class RadiusGeometryTests(TestCase):
    def test_a_mile_is_a_mile(self):
        area = areas.RadiusArea(36.75, -119.75, 1)
        geometry = area.geometry
        assert geometry.srid == 4326 and geometry.contains(area.point)
        sq_miles = geometry.transform(areas.EPSG_CALIFORNIA_ALBERS, clone=True).area / areas.SQ_METERS_PER_SQ_MILE
        assert abs(sq_miles - area.sq_miles) / area.sq_miles < 0.01
```

Create `camp/apps/emissions/tests/test_community_card.py`:

```python
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.ces.models import CES4, CES5
from camp.apps.emissions.models import Facility
from camp.apps.emissions.tests.test_areas import make
from camp.apps.regions.models import Region

# The fixture tracts: 1.01 is -119.8..-119.7 (89.2, DAC, pop 4650); 1.02 is -119.7..-119.6 (51.0, not DAC, pop 3350).
# TEST PLANT (-119.787, 36.737) is inside 1.01.
TWO_TRACTS = 'MULTIPOLYGON(((-119.74 36.7, -119.6 36.7, -119.6 36.8, -119.74 36.8, -119.74 36.7)))'


class CommunityCardTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml', 'calenviroscreen.yaml']

    def setUp(self):
        cache.clear()
        self.fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        self.tract = Region.objects.get(type=Region.Type.TRACT, external_id='06019000101')
        self.other = Region.objects.get(type=Region.Type.TRACT, external_id='06019000102')

    def get(self, url, params=None):
        response = self.client.get(url, params or {})
        assert response.status_code == 200, response.status_code
        return response.content.decode()

    def card(self, content):
        assert 'id="community"' in content
        start = content.index('id="community"')
        return content[start:content.index('</div>', content.index('</ul>', start))]

    def test_county_card(self):
        card = self.card(self.get(self.fresno.get_emissions_url(), {'year': '2024'}))
        assert '<strong>58%</strong> of residents live in state-designated disadvantaged communities (SB 535)' in card
        # Template literals aren't HTML-escaped, so the apostrophe is a plain one.
        assert "<strong>1 of 2</strong> census tracts are in California's most burdened 25% (CalEnviroScreen 5.0)" in card
        assert f'<a href="{self.other.get_emissions_url()}">51st</a> to <a href="{self.tract.get_emissions_url()}">89th</a>' in card
        # A county page lists its highest tracts.
        assert 'Highest tracts' in card and card.index('Census Tract 1.01') < card.index('Census Tract 1.02')
        # And the section nav gains a Community link.
        assert '<a href="#community">Community</a>' in self.get(self.fresno.get_emissions_url())

    def test_community_card_without_the_top_list(self):
        place = make(Region.Type.CDP, 'Plantville', TWO_TRACTS)
        card = self.card(self.get(place.get_emissions_url()))
        assert '1 of 2</strong> census tracts' in card and 'Highest tracts' not in card

    def test_near_me_card(self):
        # (-119.78, 36.73) is inside tract 1.01 near TEST PLANT, clear of the tract's centroid (-119.75, 36.75):
        # a 1-mile circle covers ~8% of the tract and neither contains its centroid, so it falls to `containing`;
        # a 3-mile circle reaches the centroid, so the tract counts. (A 302 here means the point fell outside the
        # fixture's Fresno County boundary -- nudge it toward TEST PLANT at (-119.787, 36.737), staying off the centroid.)
        url = reverse('emissions:near-me')
        content = self.get(url, {'lat': '36.73', 'lng': '-119.78', 'radius': '1'})
        card = content[content.index('id="community"'):]
        assert f'Inside census tract <a href="{self.tract.get_emissions_url()}">Census Tract 1.01</a>, at the 89th percentile (CalEnviroScreen 5.0)' in card
        assert 'SB 535 disadvantaged community' in card
        content = self.get(url, {'lat': '36.73', 'lng': '-119.78', 'radius': '3'})
        assert '1 of 1</strong> census tract is in' in content

    def test_tract_page_shows_its_own_scores(self):
        content = self.get(self.tract.get_emissions_url())
        card = content[content.index('id="community"'):]
        assert 'Overall: <strong>89th percentile</strong>' in card
        assert 'Pollution burden: <strong>83rd percentile</strong>' in card
        assert 'SB 535 disadvantaged community (Top 25% CES overall score)' in card
        assert 'https://oehha.ca.gov/calenviroscreen' in card
        assert 'of residents live' not in card

    def test_no_ces_data_no_card(self):
        CES5.objects.all().delete()
        CES4.objects.all().delete()
        for url in (self.fresno.get_emissions_url(), self.tract.get_emissions_url()):
            assert 'id="community"' not in self.get(url)
        assert 'id="community"' not in self.get(reverse('emissions:near-me'), {'lat': '36.73', 'lng': '-119.78'})
```

- [ ] **Step 2: Run them and watch them fail**

`$TEST camp/apps/emissions/tests/test_community_card.py camp/apps/emissions/tests/test_areas.py`

- [ ] **Step 3: `RadiusArea.geometry`**

In `camp/apps/emissions/areas.py`, add `METERS_PER_MILE = 1609.344` beside `MILES_PER_DEGREE`, and to `RadiusArea`:

```python
    @property
    def geometry(self):
        """The circle as a polygon in WGS84, buffered in California Albers so a mile is a mile (for CES tract membership)."""
        albers = self.point.transform(EPSG_CALIFORNIA_ALBERS, clone=True)
        return albers.buffer(self.radius * METERS_PER_MILE).transform(EPSG_LATLON, clone=True)
```

(Check `EPSG_CALIFORNIA_ALBERS` and `EPSG_LATLON` are already imported at the top of `areas.py`; `RegionArea.sq_miles` and `RadiusArea.point` use them.)

- [ ] **Step 4: The views**

In `camp/apps/emissions/views.py`, add `from camp.apps.ces import stats as ces_stats`. In `AreaPage.get_context_data`, after `kwargs.setdefault('within', None)`:

```python
        # The Community card (CalEnviroScreen): a summary of the tracts the
        # area covers, or on a tract page the tract's own row. Subclasses set
        # them; None hides the card.
        kwargs.setdefault('community', None)
        kwargs.setdefault('tract_ces', None)
        kwargs.setdefault('show_top_tracts', False)
```

In `RegionPage.get_context_data`, before `return super()...`:

```python
        if region.type == Region.Type.TRACT:
            extra['tract_ces'] = ces_stats.tract_record(region)
        elif region.boundary_id:
            extra['community'] = ces_stats.tract_summary(region.boundary.geometry)
            extra['show_top_tracts'] = region.type == Region.Type.COUNTY
```

In `NearMe.get_context_data`, add `community=ces_stats.tract_summary(self.near.geometry),` to the `super().get_context_data(...)` call.

- [ ] **Step 5: The include**

Create `camp/templates/emissions/includes/community-card.html`:

```django
{% load humanize emissions_explorer %}
{% comment %}
The Community card (camp.apps.ces.stats) on an area page. Context: `community`
(tract_summary: a region or near-me page) or `tract_ces` (tract_record: a tract
page); `show_top_tracts` lists the five highest tracts (county pages). Renders
nothing when both are None. Percentiles are OEHHA's for tracts; anything for a
larger area is SJVAir's summary of the tracts inside it.
{% endcomment %}
{% if tract_ces %}
<div class="box community-card" id="community">
    <p class="heading mb-2">Community · {{ tract_ces.label }}</p>
    <ul>
        <li>Overall: {% if tract_ces.ci_score_p is not None %}<strong>{{ tract_ces.ci_score_p|floatformat:"0"|ordinal }} percentile</strong> of California's census tracts{% else %}<strong>no score</strong> (OEHHA doesn't score tracts with too few people or missing data){% endif %}</li>
        {% if tract_ces.pollution_p is not None %}<li>Pollution burden: <strong>{{ tract_ces.pollution_p|floatformat:"0"|ordinal }} percentile</strong></li>{% endif %}
        {% if tract_ces.popchar_p is not None %}<li>Population characteristics: <strong>{{ tract_ces.popchar_p|floatformat:"0"|ordinal }} percentile</strong></li>{% endif %}
        <li>{% if tract_ces.dac %}SB 535 disadvantaged community{% if tract_ces.dac_category %} ({{ tract_ces.dac_category }}){% endif %}{% else %}Not on the SB 535 disadvantaged-community list{% endif %}</li>
    </ul>
    <p class="is-size-7 has-text-grey mb-0"><a href="https://oehha.ca.gov/calenviroscreen">OEHHA's CalEnviroScreen</a> scores and ranks every California census tract; the SB 535 list shown is CalEPA's 2026 draft until it is final. <a href="{% url 'emissions:about' %}#calenviroscreen">About</a></p>
</div>
{% elif community %}
<div class="box community-card" id="community">
    <p class="heading mb-2">Community · {{ community.label }}</p>
    {% if community.count %}
    <ul>
        {% if community.dac_share is not None %}<li><strong>{{ community.dac_share|percent }}</strong> of residents live in state-designated disadvantaged communities (SB 535).</li>{% endif %}
        {% if community.scored %}
        <li><strong>{{ community.top25_tracts|intcomma }} of {{ community.scored|intcomma }}</strong> census tract{{ community.scored|pluralize }} {% if community.scored == 1 %}is{% else %}are{% endif %} in California's most burdened 25% ({{ community.label }}).</li>
        {% if community.scored > 1 %}<li>Tract percentiles run from <a href="{{ community.lowest.region.get_emissions_url }}">{{ community.min_p|floatformat:"0"|ordinal }}</a> to <a href="{{ community.highest.region.get_emissions_url }}">{{ community.max_p|floatformat:"0"|ordinal }}</a>.</li>{% endif %}
        {% endif %}
    </ul>
    {% if show_top_tracts and community.top %}
    <p class="heading mt-3 mb-1">Highest tracts</p>
    <ul>
        {% for row in community.top %}<li><a href="{{ row.region.get_emissions_url }}">{{ row.region.name }}</a> <span class="has-text-grey is-size-7">{{ row.ci_score_p|floatformat:"0"|ordinal }} percentile{% if row.dac %} · SB 535{% endif %}</span></li>{% endfor %}
    </ul>
    {% endif %}
    {% elif community.containing %}
    <ul>
        <li>Inside census tract <a href="{{ community.containing.region.get_emissions_url }}">{{ community.containing.region.name }}</a>{% if community.containing.ci_score_p is not None %}, at the {{ community.containing.ci_score_p|floatformat:"0"|ordinal }} percentile{% endif %} ({{ community.label }}){% if community.containing.dac %} · SB 535 disadvantaged community{% endif %}.</li>
    </ul>
    {% else %}
    <p class="has-text-grey">No CalEnviroScreen tracts here.</p>
    {% endif %}
    <p class="is-size-7 has-text-grey mb-0">Percentiles are OEHHA's, for census tracts, ranked against all of California; figures for this area are SJVAir's summary of the tracts inside it, not an OEHHA score. <a href="{% url 'emissions:about' %}#calenviroscreen">About</a></p>
</div>
{% endif %}
```

In `camp/templates/emissions/area.html`: after the `stat-row` box's closing `</div>` (line 31) and before the facility-map include, add `{% include 'emissions/includes/community-card.html' %}`. In the section nav (lines 12–16, whatever the dairy plan's Task 6 left there), extend the condition to `{% if dairy_block.has_dairies or within.any or community or tract_ces %}` and add ` · <a href="#community">Community</a>` right after the Facilities link when `community or tract_ces`:

```django
        <a href="#facilities">Facilities</a>{% if community or tract_ces %} · <a href="#community">Community</a>{% endif %}{% if dairy_block.has_dairies %} · <a href="#dairies">Dairies</a>{% endif %}{% if within.any %} · <a href="#in-and-around">In and around</a>{% endif %}
```

The links in the card carry no `scope_qs`: a tract page's scope is the tract, and the CES figures don't change with year or pollutant.

- [ ] **Step 6: Run the tests**

`$TEST camp/apps/emissions/tests/test_community_card.py camp/apps/emissions/tests/test_areas.py camp/apps/emissions/tests/test_areas_pages.py camp/apps/emissions/tests/test_dairies_pages.py` — all pass. Open a county page, a city page, a tract page and a near-me page on the dev server (`:8003`; the dev DB has CES5 loaded) and read the card: the numbers should be plausible (Fresno County's DAC share is well above half; Lost Hills falls to its containing tract).

- [ ] **Step 7: Commit**

```
git -C <worktree> add camp/templates/emissions/includes/community-card.html camp/apps/emissions/tests/test_community_card.py
git -C <worktree> commit -m "feat(emissions): a CalEnviroScreen Community card on region, near-me and tract pages" -- camp/apps/emissions/areas.py camp/apps/emissions/views.py camp/templates/emissions/includes/community-card.html camp/templates/emissions/area.html camp/apps/emissions/tests/test_areas.py camp/apps/emissions/tests/test_community_card.py
```

---

### Task 8: The facility page's tract line and the About paragraph

**Files:**
- Modify: `camp/apps/emissions/views.py` (`FacilityDetail.get_context_data`)
- Modify: `camp/templates/emissions/facility-detail.html` (the "Where" card, after "Counted in", line 42)
- Modify: `camp/templates/emissions/about.html` (a new `<h2 id="calenviroscreen">` before `<h2 id="sources">`; a source list item)
- Test: `camp/apps/emissions/tests/test_community_card.py` (append)

**Interfaces:**
- Context: `facility_ces` (a `tract_record` dict for the tract the facility's point is in, or `None`).

- [ ] **Step 1: Write the failing tests**

Append to `camp/apps/emissions/tests/test_community_card.py`:

```python
class FacilityTractLineTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml', 'calenviroscreen.yaml']

    def setUp(self):
        cache.clear()
        self.tract = Region.objects.get(type=Region.Type.TRACT, external_id='06019000101')

    def test_the_where_card_names_the_tract_percentile(self):
        content = self.client.get(Facility.objects.get(name='TEST PLANT').get_absolute_url()).content.decode()
        where = content[content.index('card-header-title">Where'):content.index('facility-map map-canvas')]
        assert f'In <a href="{self.tract.get_emissions_url()}">a tract at the 89th percentile</a> (CalEnviroScreen 5.0) · SB 535 disadvantaged community' in where

    def test_no_tract_no_line(self):
        # TEST CEMENT's point is in no fixture tract.
        content = self.client.get(Facility.objects.get(name='TEST CEMENT').get_absolute_url()).content.decode()
        assert 'a tract at the' not in content
        CES5.objects.all().delete()
        CES4.objects.all().delete()
        content = self.client.get(Facility.objects.get(name='TEST PLANT').get_absolute_url()).content.decode()
        assert 'a tract at the' not in content

    def test_about_page(self):
        content = self.client.get(reverse('emissions:about')).content.decode()
        assert '<h2 id="calenviroscreen">' in content
        assert "SB 535 disadvantaged-community list shown is CalEPA's 2026 draft until it is final" in content
```

- [ ] **Step 2: Run them and watch them fail**

`$TEST camp/apps/emissions/tests/test_community_card.py`

- [ ] **Step 3: The view and template**

In `FacilityDetail.get_context_data`, replace `area_links=area_links(areas.facility_areas(facility)),` with:

```python
        facility_regions = areas.facility_areas(facility)
        tract = next((region for region in facility_regions if region.type == Region.Type.TRACT), None)
        ...
            area_links=area_links(facility_regions),
            facility_ces=ces_stats.tract_record(tract),
```

(`facility_regions` computed before the `return`; `facility_ces=` inside the call.)

In `facility-detail.html`, inside the "Where" card's `card-content`, after the `{% endif %}` that closes the `area_links` block (line 42):

```django
                {% if facility_ces %}
                <p class="heading mt-4 mb-1">Community</p>
                <p>In <a href="{{ facility_ces.region.get_emissions_url }}">a tract {% if facility_ces.ci_score_p is not None %}at the {{ facility_ces.ci_score_p|floatformat:"0"|ordinal }} percentile{% else %}OEHHA doesn't score{% endif %}</a> ({{ facility_ces.label }}){% if facility_ces.dac %} · SB 535 disadvantaged community{% endif %}</p>
                {% endif %}
```

- [ ] **Step 4: The About paragraph and source**

In `camp/templates/emissions/about.html`, before `<h2 id="sources">` (after the Phase 2 `schools` section if it's there, else after Dairies):

```django
<h2 id="calenviroscreen">CalEnviroScreen</h2>
<p>Region pages and facility pages show figures from <strong>CalEnviroScreen</strong>, the Office of Environmental Health Hazard Assessment's screening tool that ranks every California census tract by pollution burden and population vulnerability, and from the state's list of <strong>SB 535 disadvantaged communities</strong>, which CalEPA designates from those scores.</p>
<p>CalEnviroScreen percentiles are OEHHA's, for census tracts, and rank tracts against the rest of California. Figures for a city, ZIP or county are SJVAir's summary of the tracts inside it, not an OEHHA score. The SB 535 disadvantaged-community list shown is CalEPA's 2026 draft until it is final.</p>
<p>A tract counts toward an area when its centre is inside the area or the area covers at least a tenth of the tract; a place too small to do either is described by the tract it sits in. Tracts OEHHA leaves unscored (too few people, or missing data) count toward populations but not toward percentiles.</p>
```

Add to the sources list: `<li><a href="https://oehha.ca.gov/calenviroscreen">OEHHA CalEnviroScreen</a> and <a href="https://calepa.ca.gov/envjustice/ghginvest/">CalEPA SB 535 disadvantaged communities</a></li>`.

- [ ] **Step 5: Run everything both phases touch, then smoke**

`$TEST camp/apps/emissions camp/apps/ces camp/apps/reports` — all pass. Then the smoke script (`Global Constraints`) against `:8003`; it must pass.

- [ ] **Step 6: Commit**

```
git -C <worktree> commit -m "feat(emissions): the facility page names its tract's CalEnviroScreen percentile" -- camp/apps/emissions/views.py camp/templates/emissions/facility-detail.html camp/templates/emissions/about.html camp/apps/emissions/tests/test_community_card.py
```

**Phase 3 ends here.** PR description: what the card says and where, the membership rule and the −999 fix (which changes the admin coverage panels' averages and, for small places, their tract counts), the draft-DAC caveat, and that there is nothing to run on deploy.

---

## Self-review

- **Spec coverage.** Phase 2: `point_source` and its writers (Tasks 1–2), `near()` with the four hidden rules and the two groups (Task 3), the card with "and N more" / "None within ¼ mile", the ring and markers in `facility_map_config`, the About paragraph (Task 4). Nothing on region pages or the main map, as specified. Phase 3: `tract_summary` with the centroid-or-10% rule, −999 handling, unweighted `mean_p`, `containing`, a day's cache, the picker moved into `ces/stats.py` with reports importing it, `tract_stats` as a thin adapter (Tasks 5–6); the card on region and near-me pages with the county top-five, the tract page block with a link to OEHHA, the facility line, the About paragraph (Tasks 7–8). No map layer, as specified.
- **Spec tests, mapped.** Phase 2: 900/1,200/2,000 ft fixtures, the groups, ordering, the six hidden cases, `point_source` from the import and from the point chooser, the card and the map config → Tasks 3, 2, 4. Phase 3: containing rule, 5%/40% overlap, −999, DAC share, top-25, CES4 fallback, `tract_stats` keys and −999, the card on county, city and near-me, the tract block, the facility line → Tasks 5, 6, 7, 8.
- **Separability.** Tasks 5–8 touch `views.py`, `facility-detail.html`, `area.html` and `about.html`, which Tasks 4 and 7/8 also touch, but never the same lines and never each other's symbols; either half applies cleanly on the shared base.
- **Deviations from the spec are listed under "Refinements made while planning"** (the `clean_facility_points` → `import_carb_locations` correction is the one that changes a deploy step).
