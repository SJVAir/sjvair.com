# Emissions Phase 8: Greenhouse Gases — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put each large emitter's reported greenhouse gases on the explorer: one `GHGReport` table filled from two programs — EPA's Greenhouse Gas Reporting Program (GHGRP, RY2023, via the Envirofacts API) and CARB's Mandatory GHG Reporting (MRR, 2024, one XLSX) — matched to CEIDARS facilities deterministically where EPA's FRS record carries the district's facility id, by a hand-curated crosswalk for the largest MRR emitters, and by a conservative name-and-place match otherwise. Matched reports show as a "Greenhouse gases" card on the facility page; every county page gets a "Largest greenhouse-gas reporters" table that includes the unmatched and basin-wide rows; the About page explains what the numbers are and aren't. No map layer, no list filter, no periodic task.

**Architecture:**
- **Model.** `GHGReport` (program × external id × year), with the facility FK, a `county` FK (added beyond the spec so unmatched rows have a county page to appear on), the four gas figures in metric tons (`co2e`, `co2e_biogenic`, `ch4`, `n2o`), the point (GHGRP only), `frs_id`, `basin_wide` and `match_method`. One migration, `0015_ghgreport`.
- **Matching** lives in `camp/apps/emissions/ghg.py` and is shared by both imports: `resolve()` tries the FRS `AIR` id (parsed by Phase 4's `icis.parse_pgm_sys_id`), then `ghg_crosswalk.py`, then the auto match (`name_key` + `difflib` ratio, candidates within 1 km of a trusted point for GHGRP, or in the same ZIP for MRR). The crosswalk can also pin an id to *no* facility (basin-wide rows, known false positives).
- **Imports.** `ghgrp.py` + `import_ghgrp --year` (Envirofacts: eight per-county facility calls, then one emissions and one FRS call per facility, ≈350 requests, one transaction per county). `mrr.py` + `import_mrr --year --path|--url` (openpyxl; the `<year> GHG Data` and `<year> Emissions by GHG` sheets; browser User-Agent for ww2.arb.ca.gov). Both upsert on `(program, external_id, year)`, delete that year's rows they no longer see, write a `SourceImport` row and call `stats.clear_caches()`.
- **Read side** (`ghg.py`): `facility_card(facility)`, `county_table(county)` (cached under `stats.prefix()`), `stamp(program)`. Two template includes, three context keys, one About section, two integrations entries.

**Tech Stack:** Django 5.2 / GeoDjango + PostGIS (`Distance`, `distance_lte` on geodetic geometry), django-vanilla-views, requests, openpyxl 3.1 (in `requirements/base.txt`), `difflib.SequenceMatcher`, Bulma. No JS or Sass changes.

**Spec:** `docs/superpowers/specs/2026-09-28-emissions-data-expansion-design.md` — read "Assumptions", "Shared: SourceImport", "Data model summary" and all of "Phase 8" before any task. Research: `.superpowers/research/ammonia-ghg.md`, section 2 (MRR traps, GHGRP/FRS join, match rates).

## Global Constraints

- **Where to work.** Worktree `/home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer` (`<worktree>` below). This phase is a **new branch stacked on Phase 7's branch** (the chain is phase 1 → 2 → 3 → 4 → 6 → 5 → 7 → 8 → 9): `git -C <worktree> switch -c feature/emissions-ghg <phase-7-branch>`. Use absolute paths and `git -C <worktree>` for every git command. Never edit or commit in `/home/derek/dev/ccac/sjvair.com` (the main checkout) or any other worktree. After each commit, verify it with `git -C <worktree> log --oneline -1`.
- **Plan against the code as the earlier phases leave it.** This plan reads Phase 1's `SourceImport` and `stats.prefix()` / `stats.clear_caches()` / `stats.CACHE_TIMEOUT`; Phase 2's `Facility.point_source`, `Facility.TRUSTED_POINT_SOURCES` and `Facility.has_trusted_point`; Phase 4's `camp/apps/emissions/icis.py` (`parse_pgm_sys_id`, `FIPS_TO_CARB`) and its `{% if compliance_card %}` include in `facility-detail.html`; Phase 7's `wells_block` include and the section-nav condition in `area.html`. **Do not redefine any of those; import them.** Migrations in the chain so far: 0007–0009 (Phase 1), 0010 (Phase 2), 0011 (Phase 4), 0012 (Phase 6), 0013 (Phase 5), 0014 (Phase 7); this phase's is `0015_ghgreport`. If the numbering differs when you start, use the next free number and point `dependencies` at the newest one. Where a step says "after X" in a template, find X by name, not by line number.
- **Tests** use `django.test.TestCase` with plain `assert` (never `self.assertX`), `pytest.raises` for exceptions; fixtures `regions.yaml`, `emissions.yaml`. Tests never hit the network: every fetch is behind one module-level function (`ghgrp.fetch_json`, `mrr.download`) that tests patch, and sample files are small checked-in files under `camp/apps/emissions/tests/data/` produced exactly as the steps say.
- **New models use sqids:** `sqid = SqidsField(alphabet=shuffle_alphabet('emissions.ModelName'))` (see `camp/apps/emissions/models.py`).
- **Verbose names** use `_()` as the first positional arg; don't align `=`.
- **Test command** (`$TEST` below; `<paths>` are container paths under `/app`):
  `docker compose -f /home/derek/dev/ccac/sjvair.com/docker-compose.yml --project-directory /home/derek/dev/ccac/sjvair.com run --rm -T -e DATABASE_URL=postgis://sjvair:changeme@db:5432/sjvair_ghg -v /home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer:/app test pytest <paths> -q -p no:cacheprovider --create-db`
- **Management commands against the worktree** (`$MANAGE` below): the same prefix without `-e`, service `web`, then `python manage.py <command>`. **Asset rebuild** (not needed by this plan: no JS or Sass changes): the same prefix, service `web`, `invoke vendor bundle styles`.
- **Smoke:** `/home/derek/.claude/jobs/d44a9b36/tmp/venv/bin/python scripts/emissions_map_smoke.py --base http://localhost:8003`. The dev server's container is `docker ps --filter publish=8003`; never stop it. Run commands in it with `docker exec $(docker ps --filter publish=8003 --format '{{.Names}}') python manage.py …`.
- **Commits:** explicit paths, never `git add -A`, never `git stash`, never push, no AI attribution or Co-Authored-By trailers.
- **Deploy notes go in the PR description, not CLAUDE.md.**

## Review Focus

- **Emitter-only.** An MRR row's `co2e` is column `Emitter CO2e from Non-Biogenic Sources…` and nothing else; fuel-supplier and electricity-importer columns are never read into a figure. A row with zero emitter CO2e (Jaco Oil, "Kern Energy (fuel supplier)") is dropped even though its `Total CO2e` is millions (`test_emitter_columns_only`, Task 3).
- **Biogenic stays separate.** GHGRP gas 8 (`BIOCO2`) and MRR's `Emitter CO2 from Biogenic Fuels` go to `co2e_biogenic`, never into `co2e` (`test_gas_totals`, Task 2; `test_biogenic_separate`, Task 3).
- **CH4 and N2O are tons of gas.** MRR's per-gas sheet is already mass; GHGRP's emissions rows are CO2e per gas and are divided by the GWP EPA used for that year (AR4: 25 / 298 through RY2023; AR5: 28 / 265 from RY2024). Pinned by `test_gas_totals`.
- **Matching is conservative.** The FRS path only matches a parsed SJVAPCD id that exists; the auto match needs a clear best candidate (ratio ≥ 0.8, next best at least 0.05 behind) among facilities with a trusted point within 1 km (GHGRP) or in the same ZIP (MRR). A crosswalk `None` beats everything. Unmatched rows are shown on county pages, never on a facility (`test_auto_match_needs_a_clear_winner`, Task 1).
- **Idempotence.** Re-running either import changes no row counts and refreshes figures; a row that disappears upstream for that year is deleted (`test_idempotent_and_prunes`, Tasks 2 and 3).
- **Caveat copy** is the spec's, verbatim, on the card, the county table and About; the hazard-index wording rule doesn't apply here.
- **No network in tests**: grep the new test files for `data.epa.gov` / `arb.ca.gov` URLs only inside patched functions.

---

## Task List

1. `GHGReport` model, migration, admin, the crosswalk module and the shared matching helpers (`ghg.py`)
2. `ghgrp.py` and `import_ghgrp`: Envirofacts facilities, emissions, FRS join
3. `mrr.py` and `import_mrr`: the CARB workbook, ZIP filter, emitter columns, per-gas join, basin flag
4. Read side: `ghg.facility_card`, `ghg.county_table`, `ghg.stamp`
5. Pages: the facility card, the county table, About and integrations
6. Crosswalk curation on the dev DB, full run, smoke, PR notes

---

### Task 1: `GHGReport`, migration, admin, the crosswalk and the shared matching helpers

**Files:**
- Modify: `camp/apps/emissions/models.py` (after `CountyInventory`, or after Phase 7's `Well`, whichever is last)
- Create: `camp/apps/emissions/migrations/0015_ghgreport.py` (generated)
- Modify: `camp/apps/emissions/admin.py`
- Create: `camp/apps/emissions/ghg_crosswalk.py`, `camp/apps/emissions/ghg.py`
- Create: `camp/apps/emissions/tests/test_ghg.py`

**Interfaces:**
- Produces: `GHGReport` with `Program` (`GHGRP='ghgrp'`, `MRR='mrr'`) and `MatchMethod` (`FRS='frs'`, `CROSSWALK='crosswalk'`, `AUTO='auto'`, `NONE=''`) choices, `Facility.ghg_reports` reverse name, `GHGReport.source_url` property.
- `ghg_crosswalk.MRR: dict[str, tuple | None]` and `ghg_crosswalk.GHGRP: dict[str, tuple | None]`: external id → `(county_code, district_code, facid)` or `None` (pin to "no facility").
- `ghg.name_key(name) -> str`, `ghg.similarity(a, b) -> float`, `ghg.facility_for_key(key) -> Facility | None`, `ghg.best_match(name, candidates) -> Facility | None`, `ghg.candidates_near(point, km=1.0) -> QuerySet`, `ghg.candidates_in_zip(zipcode) -> QuerySet`, `ghg.resolve(program, external_id, *, name, frs_air_id=None, point=None, zipcode='') -> (Facility | None, str)`; constants `AUTO_RATIO = 0.8`, `AUTO_MARGIN = 0.05`, `MATCH_KM = 1.0`.
- Consumed by: Tasks 2–5.

- [ ] **Step 1: The model**

In `camp/apps/emissions/models.py`, at the end of the models (after the last model the earlier phases added):

```python
class GHGReport(models.Model):
    """
    One large emitter's reported greenhouse gases for one year, from EPA's
    Greenhouse Gas Reporting Program (GHGRP) or CARB's Mandatory GHG
    Reporting (MRR). Metric tons. `co2e` is the emitter's own non-biogenic
    total; biogenic CO2 is kept apart, never added in. `ch4` and `n2o` are
    tons of the gas itself, not CO2e. Matched to a CEIDARS facility when we
    can say so with confidence; otherwise it still has a county, and county
    pages show it as an unmatched reporter.
    """

    class Program(models.TextChoices):
        GHGRP = 'ghgrp', _('EPA GHGRP')
        MRR = 'mrr', _('CARB MRR')

    class MatchMethod(models.TextChoices):
        FRS = 'frs', _('FRS air program id')
        CROSSWALK = 'crosswalk', _('Hand-curated crosswalk')
        AUTO = 'auto', _('Name and place')
        NONE = '', _('Unmatched')

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.GHGReport'))
    program = models.CharField(_('Program'), max_length=8, choices=Program.choices, db_index=True)
    # GHGRP facility_id or the MRR "ARB ID": the program's own key, as text.
    external_id = models.CharField(_('External id'), max_length=20)
    year = models.IntegerField(_('Year'), db_index=True)
    facility = models.ForeignKey(
        Facility, verbose_name=_('Facility'), null=True, blank=True,
        on_delete=models.SET_NULL, related_name='ghg_reports',
    )
    # GHGRP: from county_fips. MRR: the matched facility's county, else the
    # county containing the reported ZIP. Null only when neither resolves.
    county = models.ForeignKey(
        'regions.Region', verbose_name=_('County'), null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )
    name = models.CharField(_('Name'), max_length=128)
    city = models.CharField(_('City'), max_length=64, blank=True)
    zipcode = models.CharField(_('ZIP code'), max_length=10, blank=True)
    naics = models.CharField(_('NAICS'), max_length=8, blank=True)
    # GHGRP facility_types ("Direct Emitter") / MRR Industry Sector ("Refinery").
    sector = models.CharField(_('Sector'), max_length=128, blank=True)
    subparts = models.CharField(_('Subparts'), max_length=128, blank=True)
    co2e = models.FloatField(_('CO2e (metric tons)'))
    co2e_biogenic = models.FloatField(_('Biogenic CO2 (metric tons)'), null=True, blank=True)
    ch4 = models.FloatField(_('CH4 (metric tons)'), null=True, blank=True)
    n2o = models.FloatField(_('N2O (metric tons)'), null=True, blank=True)
    point = models.PointField(_('Point'), null=True, blank=True)
    frs_id = models.CharField(_('FRS registry id'), max_length=12, blank=True)
    # MRR oil & gas production is reported per basin, not per site.
    basin_wide = models.BooleanField(_('Basin-wide'), default=False)
    match_method = models.CharField(_('Match method'), max_length=10, choices=MatchMethod.choices, blank=True, default='')

    class Meta:
        unique_together = [('program', 'external_id', 'year')]
        ordering = ['-co2e']
        verbose_name = _('GHG report')

    def __str__(self):
        return f'{self.get_program_display()} {self.year}: {self.name}'

    @property
    def source_url(self):
        if self.program == self.Program.GHGRP:
            return f'https://ghgdata.epa.gov/ghgp/service/facilityDetail/{self.year}?id={self.external_id}&et=undefined'
        return 'https://ww2.arb.ca.gov/mrr-data'
```

- [ ] **Step 2: Migration and admin**

Run: `$MANAGE makemigrations emissions -n ghgreport`
Expected: `camp/apps/emissions/migrations/0015_ghgreport.py` creating `GHGReport`, depending on `0014_well` (or the newest). Open it and check nothing else is in it (a stray change means an earlier phase left an unmigrated edit; stop and report rather than absorbing it).

In `admin.py`, add `GHGReport` to the models import and, at the end:

```python
@admin.register(GHGReport)
class GHGReportAdmin(ReadOnlyAdminMixin, base_admin.ModelAdmin):
    list_display = ['name', 'program', 'year', 'county', 'facility', 'match_method', 'basin_wide', 'co2e', 'ch4']
    list_filter = ['program', 'year', 'match_method', 'basin_wide', 'county']
    search_fields = ['name', 'external_id', 'frs_id', 'facility__name']
    raw_id_fields = ['facility']
    ordering = ['-co2e']
```

- [ ] **Step 3: The crosswalk module**

`camp/apps/emissions/ghg_crosswalk.py`:

```python
"""
Hand-curated links from a GHG program's id to a CEIDARS facility key
(county_code, district_code, facid), for the reporters the automatic match
gets wrong or can't reach. A value of None pins the id to *no* facility:
basin-wide oil & gas reports, and known false positives of the name match.
Checked against the dev DB on the date beside each entry. Curated for the
top ~40 MRR emitters in Task 6; keep it sorted by CO2e, largest first.

Facility keys: `Facility.objects.get(county_code=c, air_district__external_id=d, facid=f)`.
County codes: Fresno 10, Kern 15, Kings 16, Madera 20, Merced 24, San Joaquin 39,
Stanislaus 50, Tulare 54. Districts: 'SJU' (Valley Air District), 'KER' (Eastern Kern).
"""

# CARB MRR "ARB ID" -> facility key or None.
MRR = {
    '104030': None,               # California Resources Production Corp - San Joaquin Valley Basin 745: basin-wide
    '101342': (20, 'SJU', 801),   # Ardagh Glass Inc., Madera (FRS AIR id CASJV00006039C0801), 2026-09-28
}

# EPA GHGRP facility_id -> facility key or None. Most GHGRP rows resolve
# through FRS; this is for the rest (field-level oil & gas ids stay None).
GHGRP = {}
```

- [ ] **Step 4: The failing tests for matching**

`camp/apps/emissions/tests/test_ghg.py` (the whole file is new; later tasks append classes):

```python
from unittest.mock import patch

from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.test import TestCase

from camp.apps.emissions import ghg, ghg_crosswalk
from camp.apps.emissions.models import Facility, GHGReport
from camp.apps.regions.models import Region


# TEST PLANT: Fresno (10, 'SJU', 1), point (-119.787, 36.737), ZIP 93728 (a fixture ZIP Region).
# TEST GAS STATION: Kern (15, 'SJU', 2), ZIP 93301 (no fixture ZIP Region).
# TEST CEMENT: Eastern Kern (15, 'KER', 2), point (-118.17, 35.05).
NEAR_PLANT = Point(-119.790, 36.739, srid=4326)      # ~350 m from TEST PLANT
FAR_FROM_PLANT = Point(-119.72, 36.737, srid=4326)   # ~6 km east


class GHGTestCase(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.plant = Facility.objects.get(name='TEST PLANT')
        self.station = Facility.objects.get(name='TEST GAS STATION')
        self.cement = Facility.objects.get(name='TEST CEMENT')
        self.fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        self.kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        # Phase 2: only trusted points take part in the distance match.
        Facility.objects.update(point_source=Facility.PointSource.CENSUS)


def report(program='mrr', external_id='1', year=2024, **kwargs):
    values = dict(name='X', co2e=10000.0)
    values.update(kwargs)
    return GHGReport.objects.create(program=program, external_id=external_id, year=year, **values)


class NameKeyTests(TestCase):
    def test_key_drops_corporate_noise(self):
        assert ghg.name_key('Ardagh Glass Inc.') == 'ARDAGH GLASS'
        assert ghg.name_key('PG&E McDonald Island Underground Storage Station') == 'PG AND E MCDONALD ISLAND UNDERGROUND STORAGE STATION'
        assert ghg.name_key('The Test Plant, LLC (Fresno)') == 'TEST PLANT FRESNO'
        assert ghg.name_key('') == ''

    def test_similarity(self):
        assert ghg.similarity('Test Plant Inc', 'TEST PLANT') == 1.0
        assert ghg.similarity('Mt. Poso Cogeneration Company', 'Sycamore Cogeneration Co') < ghg.AUTO_RATIO


class ResolveTests(GHGTestCase):
    def test_frs_id_wins(self):
        facility, method = ghg.resolve('ghgrp', '1', name='UNRELATED NAME', frs_air_id='CASJV00006019C0001', point=FAR_FROM_PLANT)
        assert facility == self.plant and method == 'frs'

    def test_frs_id_for_an_unknown_facility_falls_through(self):
        facility, method = ghg.resolve('ghgrp', '1', name='Nothing Like It', frs_air_id='CASJV00006019C9999', point=FAR_FROM_PLANT)
        assert facility is None and method == ''
        # Eastern Kern ids don't parse; they fall through too.
        facility, method = ghg.resolve('ghgrp', '1', name='Test Cement', frs_air_id='CAKCA000000000002', point=Point(-118.17, 35.05, srid=4326))
        assert facility == self.cement and method == 'auto'

    def test_crosswalk_beats_auto_and_can_pin_none(self):
        with patch.dict(ghg_crosswalk.MRR, {'7': (15, 'KER', 2), '8': None}, clear=True):
            assert ghg.resolve('mrr', '7', name='Test Plant', zipcode='93728') == (self.cement, 'crosswalk')
            assert ghg.resolve('mrr', '8', name='Test Plant', zipcode='93728') == (None, 'crosswalk')
        with patch.dict(ghg_crosswalk.MRR, {'7': (15, 'KER', 999)}, clear=True):
            # A stale key (no such facility) is ignored, not fatal.
            assert ghg.resolve('mrr', '7', name='Test Plant', zipcode='93728') == (self.plant, 'auto')

    def test_auto_match_by_zip(self):
        assert ghg.resolve('mrr', '1', name='Test Plant Inc.', zipcode='93728') == (self.plant, 'auto')
        assert ghg.resolve('mrr', '1', name='Test Plant Inc.', zipcode='93728-1234') == (self.plant, 'auto')
        # Same ZIP, different name.
        assert ghg.resolve('mrr', '1', name='Fresno Cogeneration Partners', zipcode='93728') == (None, '')
        # Right name, other ZIP.
        assert ghg.resolve('mrr', '1', name='Test Plant', zipcode='93301') == (None, '')

    def test_auto_match_by_distance(self):
        assert ghg.resolve('ghgrp', '1', name='Test Plant', point=NEAR_PLANT) == (self.plant, 'auto')
        assert ghg.resolve('ghgrp', '1', name='Test Plant', point=FAR_FROM_PLANT) == (None, '')
        Facility.objects.filter(pk=self.plant.pk).update(point_source=Facility.PointSource.MAPTILER)
        assert ghg.resolve('ghgrp', '1', name='Test Plant', point=NEAR_PLANT) == (None, '')

    def test_auto_match_needs_a_clear_winner(self):
        # Multi-site companies reuse a name across CEIDARS facilities: two
        # equal candidates (1.0 and 1.0) is no match at all.
        twin = Facility.objects.create(
            county_code=10, air_district=self.plant.air_district, facid=77, name='TEST PLANT', sic_code=3221,
            address={'zipcode': '93728'}, point=Point(-119.788, 36.738, srid=4326), point_source=Facility.PointSource.CENSUS,
            county=self.fresno, zipcode=self.plant.zipcode,
        )
        assert ghg.resolve('mrr', '1', name='Test Plant', zipcode='93728') == (None, '')
        # 'TEST PLANT NORTH' scores 0.8 against 'Test Plant' (at the ratio floor)
        # and the original scores 1.0: a clear winner either way round.
        Facility.objects.filter(pk=twin.pk).update(name='TEST PLANT NORTH')
        twin.refresh_from_db()
        assert ghg.resolve('mrr', '1', name='Test Plant', zipcode='93728') == (self.plant, 'auto')
        assert ghg.resolve('mrr', '1', name='Test Plant North', zipcode='93728') == (twin, 'auto')
```

Run: `$TEST camp/apps/emissions/tests/test_ghg.py`
Expected: FAIL (`ghg` has no `name_key`).

- [ ] **Step 5: `ghg.py` (the matching half; Task 4 adds the read side)**

```python
"""
Greenhouse-gas reports (GHGReport): matching a program's row to a CEIDARS
facility, and the read side for the facility card and the county table.
"""
import difflib
import re

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from django.db.models import Q

from camp.apps.emissions import ghg_crosswalk, icis
from camp.apps.emissions.models import Facility, GHGReport

# The auto match: best candidate's name similarity, and how far ahead of the
# runner-up it must be. Conservative on purpose: a wrong match puts one
# company's emissions on another's page; an unmatched row still shows on
# the county page.
AUTO_RATIO = 0.8
AUTO_MARGIN = 0.05
MATCH_KM = 1.0
# Corporate noise that names differ on between programs.
STOPWORDS = frozenset({
    'INC', 'LLC', 'LP', 'LTD', 'CO', 'CORP', 'CORPORATION', 'COMPANY', 'THE', 'OF', 'DBA',
})
_NON_ALNUM = re.compile(r'[^A-Z0-9 ]+')


def name_key(name):
    text = (name or '').upper().replace('&', ' AND ')
    text = _NON_ALNUM.sub(' ', text)
    return ' '.join(token for token in text.split() if token not in STOPWORDS)


def similarity(a, b):
    return difflib.SequenceMatcher(None, name_key(a), name_key(b)).ratio()


def facility_for_key(key):
    """The facility for a crosswalk key, or None when the key is None or stale."""
    if not key:
        return None
    county_code, district, facid = key
    return Facility.objects.filter(county_code=county_code, air_district__external_id=district, facid=facid).first()


def candidates_near(point, km=MATCH_KM):
    """Facilities with a trusted point within `km` of `point`, nearest first (geodetic, metres on a sphere)."""
    return (
        Facility.objects
        .filter(point__isnull=False, point_source__in=Facility.TRUSTED_POINT_SOURCES)
        .filter(point__dwithin=(point, 0.02), point__distance_lte=(point, D(km=km)))
        .annotate(distance=Distance('point', point))
        .order_by('distance')
    )


def candidates_in_zip(zipcode):
    zip5 = (zipcode or '').strip()[:5]
    if not zip5.isdigit():
        return Facility.objects.none()
    return Facility.objects.filter(Q(zipcode__external_id=zip5) | Q(address__zipcode=zip5))


def best_match(name, candidates):
    """The one candidate whose name clearly matches, or None."""
    scored = sorted(((similarity(name, f.name), f) for f in candidates), key=lambda pair: -pair[0])
    if not scored or scored[0][0] < AUTO_RATIO:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < AUTO_MARGIN:
        return None
    return scored[0][1]


def resolve(program, external_id, *, name, frs_air_id=None, point=None, zipcode=''):
    """
    (facility, match_method) for one program row: the FRS AIR id when it parses
    to a facility we have; else the crosswalk (which may pin None); else the
    auto match near the point (GHGRP) or in the ZIP (MRR); else (None, '').
    """
    if frs_air_id:
        parsed = icis.parse_pgm_sys_id(frs_air_id)
        if parsed:
            facility = facility_for_key(parsed)
            if facility is not None:
                return facility, GHGReport.MatchMethod.FRS
    table = ghg_crosswalk.GHGRP if program == GHGReport.Program.GHGRP else ghg_crosswalk.MRR
    if str(external_id) in table:
        key = table[str(external_id)]
        if key is None:
            return None, GHGReport.MatchMethod.CROSSWALK
        facility = facility_for_key(key)
        if facility is not None:
            return facility, GHGReport.MatchMethod.CROSSWALK
    candidates = candidates_near(point) if point is not None else candidates_in_zip(zipcode)
    facility = best_match(name, candidates)
    if facility is not None:
        return facility, GHGReport.MatchMethod.AUTO
    return None, GHGReport.MatchMethod.NONE
```

`icis.parse_pgm_sys_id` returns `(county_code, 'SJU', facid)`, which is exactly a crosswalk key. `point__dwithin` in degrees is the index prefilter (0.02° ≈ 2 km); `distance_lte` with `D(km=…)` is the real test, in metres on the sphere because `Facility.point` is geodetic (the Phase 2 idiom). The `MAPTILER` assert in `test_auto_match_by_distance` pins the trusted-point rule.

Run: `$TEST camp/apps/emissions/tests/test_ghg.py`
Expected: PASS. If `point_source` / `PointSource` don't exist, Phase 2 hasn't landed on your branch: stop and report.

- [ ] **Step 6: Commit**

```bash
git -C <worktree> add camp/apps/emissions/migrations/0015_ghgreport.py camp/apps/emissions/ghg.py camp/apps/emissions/ghg_crosswalk.py camp/apps/emissions/tests/test_ghg.py
git -C <worktree> commit -m "feat(emissions): GHGReport model and facility matching for greenhouse-gas programs" -- camp/apps/emissions/models.py camp/apps/emissions/migrations/0015_ghgreport.py camp/apps/emissions/admin.py camp/apps/emissions/ghg.py camp/apps/emissions/ghg_crosswalk.py camp/apps/emissions/tests/test_ghg.py
```

---

### Task 2: `ghgrp.py` and `import_ghgrp`: Envirofacts facilities, emissions and the FRS join

**Files:**
- Create: `camp/apps/emissions/ghgrp.py`, `camp/apps/emissions/management/commands/import_ghgrp.py`
- Create: `camp/apps/emissions/tests/data/ghgrp/facilities-06039.json`, `emissions-1000005.json`, `frs-110000482022.json` (trimmed real responses, Step 1)
- Modify: `camp/apps/emissions/tests/test_ghg.py` (append)

**Interfaces:**
- `ghgrp.BASE`, `ghgrp.COUNTY_FIPS` (the eight 5-digit FIPS, from `icis.FIPS_TO_CARB`), `ghgrp.GAS_CO2 = 1`, `GAS_CH4 = 2`, `GAS_N2O = 3`, `GAS_BIOCO2 = 8`, `ghgrp.gwp(year) -> {gas_id: gwp}`.
- `ghgrp.facilities_url(year, fips)`, `ghgrp.emissions_url(facility_id, year)`, `ghgrp.frs_url(frs_id)`; `ghgrp.fetch_json(url) -> list` (the one network call; tests patch it).
- `ghgrp.gas_totals(rows) -> {gas_id: co2e}`, `ghgrp.figures(totals, year) -> dict(co2e, co2e_biogenic, ch4, n2o)`, `ghgrp.frs_air_id(rows) -> str`, `ghgrp.import_county(year, county_region, log) -> Counter`.
- Command: `import_ghgrp --year 2023 [--county <slug>]`. Writes `SourceImport(source='ghgrp', version=str(year), data_through=date(year, 12, 31), notes={counts})`, calls `stats.clear_caches()`.

- [ ] **Step 1: The sample data**

Real responses, trimmed (Ardagh Glass Madera, `facility_id` 1000005, is the FRS-join example from the research):

```bash
OUT=/home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer/camp/apps/emissions/tests/data/ghgrp; mkdir -p "$OUT"
curl -sS 'https://data.epa.gov/efservice/pub_dim_facility/state/CA/year/2023/county_fips/06039/JSON' \
  | python3 -c "import json,sys; rows=json.load(sys.stdin); json.dump([r for r in rows if r['facility_id'] in (1000005, 1001698)], open('$OUT/facilities-06039.json','w'), indent=1)"
curl -sS 'https://data.epa.gov/efservice/pub_facts_sector_ghg_emission/facility_id/1000005/year/2023/JSON' -o "$OUT/emissions-1000005.json"
curl -sS 'https://data.epa.gov/efservice/frs_program_facility/registry_id/110000482022/JSON' \
  | python3 -c "import json,sys; rows=json.load(sys.stdin); json.dump([r for r in rows if r['pgm_sys_acrnm'] in ('AIR','AIRS/AFS','E-GGRT','ICIS')], open('$OUT/frs-110000482022.json','w'), indent=1)"
python3 -c "import json; d=json.load(open('$OUT/emissions-1000005.json')); print(d)"
```

Expected: the facilities file has 2 rows with `facility_id`, `latitude`, `longitude`, `city`, `zip`, `county_fips` (`"06039"`), `facility_name`, `naics_code`, `frs_id` (`"110000482022"`), `reported_subparts` (`"C,N"`), `facility_types` (`"Direct Emitter"`); the emissions file has 3 rows `{facility_id, year, sector_id, subsector_id, gas_id, co2e_emission}` with gas 1 = 71521.2, gas 2 = 24.25, gas 3 = 28.906; the FRS file includes one row with `pgm_sys_acrnm` `"AIR"` and `pgm_sys_id` `"CASJV00006039C0801"` (and an `AIRS/AFS` row `06039C0801` that must be ignored). If the numbers differ (EPA revised the year), use what you got and adjust the asserts in Step 2 to match the file.

- [ ] **Step 2: The failing tests**

Append to `test_ghg.py`:

```python
import json
from collections import Counter
from datetime import date
from io import StringIO
from pathlib import Path

from django.core.management import call_command

from camp.apps.emissions import ghgrp, icis, stats
from camp.apps.emissions.models import SourceImport

DATA = Path(__file__).parent / 'data'


def load(name):
    return json.loads((DATA / name).read_text())


def envirofacts(responses):
    """A fetch_json stand-in: the first payload whose key is in the URL, else []."""
    def fetch(url):
        for needle, payload in responses.items():
            if needle in url:
                return payload
        return []
    return fetch


def ef_facility(facility_id, fips, name, lat, lng, frs_id='', zipcode='93728'):
    return {
        'facility_id': facility_id, 'latitude': lat, 'longitude': lng, 'city': 'FRESNO', 'zip': zipcode,
        'county_fips': fips, 'facility_name': name, 'naics_code': '327213', 'frs_id': frs_id,
        'reported_subparts': 'C', 'facility_types': 'Direct Emitter', 'year': 2023,
    }


def ef_gas(facility_id, gas_id, co2e):
    return {'facility_id': facility_id, 'year': 2023, 'sector_id': 8, 'subsector_id': 7, 'gas_id': gas_id, 'co2e_emission': co2e}


class GHGRPParseTests(TestCase):
    def test_gas_totals_and_figures(self):
        totals = ghgrp.gas_totals(load('ghgrp/emissions-1000005.json'))
        assert totals == {1: 71521.2, 2: 24.25, 3: 28.906}
        figures = ghgrp.figures(totals, 2023)
        assert round(figures['co2e'], 3) == 71574.356
        assert figures['co2e_biogenic'] is None
        assert round(figures['ch4'], 3) == 0.97 and round(figures['n2o'], 4) == 0.097
        # Two sector rows for one gas add up; biogenic CO2 stays out of co2e.
        rows = [ef_gas(1, 1, 100.0), ef_gas(1, 1, 50.0), ef_gas(1, 8, 900.0)]
        figures = ghgrp.figures(ghgrp.gas_totals(rows), 2023)
        assert figures == {'co2e': 150.0, 'co2e_biogenic': 900.0, 'ch4': None, 'n2o': None}
        # RY2024 onward uses AR5 GWPs.
        assert ghgrp.figures({2: 28.0, 3: 265.0}, 2024)['ch4'] == 1.0
        assert ghgrp.figures({2: 28.0, 3: 265.0}, 2024)['n2o'] == 1.0

    def test_frs_air_id(self):
        air_id = ghgrp.frs_air_id(load('ghgrp/frs-110000482022.json'))
        assert air_id == 'CASJV00006039C0801'
        assert icis.parse_pgm_sys_id(air_id) == (20, 'SJU', 801)
        assert ghgrp.frs_air_id([]) == ''

    def test_urls(self):
        assert ghgrp.facilities_url(2023, '06039').endswith('/pub_dim_facility/state/CA/year/2023/county_fips/06039/JSON')
        assert ghgrp.emissions_url(1000005, 2023).endswith('/pub_facts_sector_ghg_emission/facility_id/1000005/year/2023/JSON')
        assert ghgrp.frs_url('110000482022').endswith('/frs_program_facility/registry_id/110000482022/JSON')
        assert ghgrp.COUNTY_FIPS == ('06019', '06029', '06031', '06039', '06047', '06077', '06099', '06107')


class ImportGHGRPTests(GHGTestCase):
    def responses(self):
        return {
            'county_fips/06019': [
                # Matched through FRS despite the point being far and the name unrelated.
                ef_facility(501, '06019', 'Big Glass Co', 36.60, -119.60, frs_id='110000000501'),
                # Matched by name within 1 km.
                ef_facility(502, '06019', 'Test Plant', 36.739, -119.790),
                # Nothing to match: far from anything.
                ef_facility(503, '06019', 'Lonely Landfill', 36.60, -119.20),
                # Reported no emissions rows: skipped.
                ef_facility(504, '06019', 'Silent Site', 36.61, -119.21),
            ],
            'county_fips/06029': [
                ef_facility(601, '06029', 'Basin Gathering LLC', 35.30, -119.30, zipcode='93308'),
            ],
            'facility_id/501/': [ef_gas(501, 1, 1000.0), ef_gas(501, 2, 250.0), ef_gas(501, 8, 5.0)],
            'facility_id/502/': [ef_gas(502, 1, 2000.0)],
            'facility_id/503/': [ef_gas(503, 2, 500.0), ef_gas(503, 3, 298.0)],
            'facility_id/601/': [ef_gas(601, 1, 30000.0), ef_gas(601, 2, 25000.0)],
            'registry_id/110000000501': [
                {'registry_id': '110000000501', 'pgm_sys_acrnm': 'AIRS/AFS', 'pgm_sys_id': '06019C0001'},
                {'registry_id': '110000000501', 'pgm_sys_acrnm': 'AIR', 'pgm_sys_id': 'CASJV00006019C0001'},
            ],
        }

    def run_import(self, responses=None, **options):
        out = StringIO()
        with patch('camp.apps.emissions.ghgrp.fetch_json', side_effect=envirofacts(responses or self.responses())):
            call_command('import_ghgrp', year=2023, stdout=out, **options)
        return out.getvalue()

    def test_import_matches_figures_and_counties(self):
        out = self.run_import()
        rows = {r.external_id: r for r in GHGReport.objects.filter(program='ghgrp', year=2023)}
        assert set(rows) == {'501', '502', '503', '601'}
        assert rows['501'].facility == self.plant and rows['501'].match_method == 'frs'
        assert rows['501'].co2e == 1250.0 and rows['501'].co2e_biogenic == 5.0 and rows['501'].ch4 == 10.0 and rows['501'].n2o is None
        assert rows['501'].frs_id == '110000000501' and rows['501'].county == self.fresno
        assert rows['502'].facility == self.plant and rows['502'].match_method == 'auto'
        assert rows['503'].facility is None and rows['503'].match_method == '' and rows['503'].county == self.fresno
        assert rows['503'].n2o == 1.0 and rows['503'].point.x == -119.20
        assert rows['601'].county == self.kern and rows['601'].zipcode == '93308' and rows['601'].sector == 'Direct Emitter'
        assert 'Fresno County: 3 reporters (1 frs, 1 auto, 1 unmatched)' in out
        stamp = SourceImport.latest('ghgrp')
        assert stamp.version == '2023' and stamp.data_through == date(2023, 12, 31)
        assert stamp.notes['reporters'] == 4 and stamp.notes['matched'] == 2

    def test_idempotent_and_prunes(self):
        self.run_import()
        before = stats.generation()
        responses = self.responses()
        responses['county_fips/06019'] = responses['county_fips/06019'][:2]   # 503 and 504 gone upstream
        responses['facility_id/502/'] = [ef_gas(502, 1, 2500.0)]
        self.run_import(responses)
        assert stats.generation() == before + 1
        assert set(GHGReport.objects.values_list('external_id', flat=True)) == {'501', '502', '601'}
        assert GHGReport.objects.get(external_id='502').co2e == 2500.0
        assert SourceImport.objects.filter(source='ghgrp').count() == 2

    def test_one_county(self):
        self.run_import(county='kern')
        assert list(GHGReport.objects.values_list('external_id', flat=True)) == ['601']

    def test_a_failed_fetch_skips_the_facility(self):
        import requests
        responses = self.responses()
        def fetch(url):
            if 'facility_id/502/' in url:
                raise requests.ConnectionError('boom')
            return envirofacts(responses)(url)
        err = StringIO()
        with patch('camp.apps.emissions.ghgrp.fetch_json', side_effect=fetch):
            with pytest.raises(CommandError):
                call_command('import_ghgrp', year=2023, stdout=StringIO(), stderr=err)
        assert '502' in err.getvalue()
        assert set(GHGReport.objects.values_list('external_id', flat=True)) == {'501', '503', '601'}
```

Add `import pytest` and `from django.core.management.base import CommandError` to the file's imports.

Run: `$TEST camp/apps/emissions/tests/test_ghg.py`
Expected: FAIL (`ghgrp` missing).

- [ ] **Step 3: `ghgrp.py`**

```python
"""
EPA's Greenhouse Gas Reporting Program via the Envirofacts REST API (public
domain, no key). Facilities per county (server-side county_fips filter),
then per facility its per-gas CO2e rows and its FRS program ids, whose AIR
entry is the district's facility id (Phase 4's icis.parse_pgm_sys_id).
RY2023 is the newest year published; EPA has proposed ending the program.
"""
import time
from collections import Counter

import requests

from django.contrib.gis.geos import Point
from django.db import transaction

from camp.apps.emissions import ghg, icis
from camp.apps.emissions.models import GHGReport
from camp.apps.regions.models import Region

BASE = 'https://data.epa.gov/efservice'
# The eight counties as 5-digit FIPS; icis has the 3-digit tails.
COUNTY_FIPS = tuple(f'06{tail}' for tail in sorted(icis.FIPS_TO_CARB))
GAS_CO2, GAS_CH4, GAS_N2O, GAS_BIOCO2 = 1, 2, 3, 8
PROGRAM = GHGReport.Program.GHGRP


def gwp(year):
    """
    The global warming potentials GHGRP used to turn tons of gas into CO2e
    (40 CFR 98, Table A-1): AR4 through RY2023, AR5 from RY2024.
    """
    if year <= 2023:
        return {GAS_CH4: 25, GAS_N2O: 298}
    return {GAS_CH4: 28, GAS_N2O: 265}


def facilities_url(year, fips):
    return f'{BASE}/pub_dim_facility/state/CA/year/{year}/county_fips/{fips}/JSON'


def emissions_url(facility_id, year):
    return f'{BASE}/pub_facts_sector_ghg_emission/facility_id/{facility_id}/year/{year}/JSON'


def frs_url(frs_id):
    return f'{BASE}/frs_program_facility/registry_id/{frs_id}/JSON'


def fetch_json(url, retries=3):
    """The one network call. Envirofacts throttles; back off and retry."""
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=120)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)


def gas_totals(rows):
    """{gas_id: CO2e} summed over sector rows."""
    totals = Counter()
    for row in rows:
        totals[int(row['gas_id'])] += float(row['co2e_emission'] or 0)
    return dict(totals)


def figures(totals, year):
    factors = gwp(year)
    co2e = sum(value for gas, value in totals.items() if gas != GAS_BIOCO2)
    return {
        'co2e': co2e,
        'co2e_biogenic': totals.get(GAS_BIOCO2),
        'ch4': totals[GAS_CH4] / factors[GAS_CH4] if GAS_CH4 in totals else None,
        'n2o': totals[GAS_N2O] / factors[GAS_N2O] if GAS_N2O in totals else None,
    }


def frs_air_id(rows):
    for row in rows:
        if row.get('pgm_sys_acrnm') == 'AIR':
            return (row.get('pgm_sys_id') or '').strip()
    return ''


def import_county(year, county, log):
    """
    One county's reporters for `year`, in one transaction: upsert each, delete
    the ones no longer reported. Returns a Counter of outcomes; `failed`
    reporters are logged and skipped (their existing rows are kept).
    """
    fips = county.external_id
    counts = Counter()
    seen = set()
    failed = set()
    rows = fetch_json(facilities_url(year, fips))
    with transaction.atomic():
        for fac in rows:
            external_id = str(fac['facility_id'])
            try:
                totals = gas_totals(fetch_json(emissions_url(external_id, year)))
                frs_rows = fetch_json(frs_url(fac['frs_id'])) if fac.get('frs_id') else []
            except requests.RequestException as err:
                log.error(f'{external_id} {fac.get("facility_name")}: {err}')
                failed.add(external_id)
                continue
            if not totals:
                counts['no_emissions'] += 1
                continue
            point = None
            if fac.get('latitude') is not None and fac.get('longitude') is not None:
                point = Point(float(fac['longitude']), float(fac['latitude']), srid=4326)
            facility, method = ghg.resolve(
                PROGRAM, external_id, name=fac.get('facility_name') or '', frs_air_id=frs_air_id(frs_rows), point=point,
            )
            GHGReport.objects.update_or_create(
                program=PROGRAM, external_id=external_id, year=year,
                defaults=dict(
                    facility=facility, match_method=method,
                    county=facility.county if facility is not None and facility.county_id else county,
                    name=(fac.get('facility_name') or '')[:128], city=(fac.get('city') or '')[:64],
                    zipcode=(fac.get('zip') or '')[:10], naics=(fac.get('naics_code') or '')[:8],
                    sector=(fac.get('facility_types') or '')[:128], subparts=(fac.get('reported_subparts') or '')[:128],
                    point=point, frs_id=(fac.get('frs_id') or '')[:12], basin_wide=False,
                    **figures(totals, year),
                ),
            )
            seen.add(external_id)
            counts[method or 'unmatched'] += 1
        stale = GHGReport.objects.filter(program=PROGRAM, year=year, county=county).exclude(external_id__in=seen | failed)
        counts['deleted'] += stale.count()
        stale.delete()
    counts['failed'] = len(failed)
    return counts
```

The stale-row query is by the *page* county, so a matched facility's row in another county (a Firebaugh plant with Madera FIPS) is pruned by the county whose page it's on. `log` is the command (it has `.error` below).

- [ ] **Step 4: The command**

`camp/apps/emissions/management/commands/import_ghgrp.py`:

```python
import time
from collections import Counter
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from camp.apps.emissions import ghgrp, stats
from camp.apps.emissions.models import GHGReport, SourceImport
from camp.apps.regions.models import Region


class Command(BaseCommand):
    help = (
        "Import EPA GHGRP greenhouse-gas totals for the eight counties' reporters from Envirofacts "
        '(about 350 requests). Idempotent; a reporter that vanishes upstream for the year is deleted.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, required=True, help='Reporting year (2023 is the newest published)')
        parser.add_argument('--county', help='One county slug (default: all eight)')

    def error(self, message):
        self.stderr.write(message)

    def handle(self, *args, **options):
        year = options['year']
        counties = Region.objects.filter(type=Region.Type.COUNTY, external_id__in=ghgrp.COUNTY_FIPS).order_by('name')
        if options['county']:
            counties = counties.filter(slug=options['county'])
            if not counties.exists():
                raise CommandError(f'No covered county with slug {options["county"]!r}.')
        start = time.monotonic()
        total = Counter()
        for county in counties:
            counts = ghgrp.import_county(year, county, self)
            total.update(counts)
            reporters = counts['frs'] + counts['crosswalk'] + counts['auto'] + counts['unmatched']
            self.stdout.write(
                f'{county.name}: {reporters} reporters ({counts["frs"]} frs, {counts["auto"]} auto, '
                f'{counts["unmatched"]} unmatched)'
                + (f', {counts["crosswalk"]} crosswalk' if counts['crosswalk'] else '')
                + (f', {counts["deleted"]} deleted' if counts['deleted'] else '')
                + (f', {counts["failed"]} failed' if counts['failed'] else '')
            )
        matched = total['frs'] + total['crosswalk'] + total['auto']
        reporters = matched + total['unmatched']
        SourceImport.objects.create(
            source='ghgrp', version=str(year), data_through=date(year, 12, 31),
            notes={'reporters': reporters, 'matched': matched, 'unmatched': total['unmatched'],
                   'no_emissions': total['no_emissions'], 'deleted': total['deleted'], 'failed': total['failed']},
        )
        stats.clear_caches()
        self.stdout.write(f'\nDone. {reporters} reporters, {matched} matched [{time.monotonic() - start:.1f}s]')
        if total['failed']:
            raise CommandError(f'{total["failed"]} reporters could not be fetched; re-run for their counties.')
```

Run: `$TEST camp/apps/emissions/tests/test_ghg.py`
Expected: PASS. If `test_import_matches_figures_and_counties` fails on `rows['502']` (auto), check `Facility.objects.update(point_source=...)` in `setUp` ran and that the plant's point is `(-119.787, 36.737)`.

- [ ] **Step 5: Commit**

```bash
git -C <worktree> add camp/apps/emissions/ghgrp.py camp/apps/emissions/management/commands/import_ghgrp.py camp/apps/emissions/tests/data/ghgrp
git -C <worktree> commit -m "feat(emissions): import EPA GHGRP reporters from Envirofacts, joined to facilities through FRS (import_ghgrp)" -- camp/apps/emissions/ghgrp.py camp/apps/emissions/management/commands/import_ghgrp.py camp/apps/emissions/tests/data/ghgrp camp/apps/emissions/tests/test_ghg.py
```

---

### Task 3: `mrr.py` and `import_mrr`: the CARB workbook, ZIP filter, emitter columns, per-gas join, basin flag

**Files:**
- Create: `camp/apps/emissions/mrr.py`, `camp/apps/emissions/management/commands/import_mrr.py`
- Create: `camp/apps/emissions/tests/data/mrr-sample.xlsx` (built in Step 1; ~10 KB)
- Modify: `camp/apps/emissions/tests/test_ghg.py` (append)

**Interfaces:**
- `mrr.URL`, `mrr.HEADERS`, `mrr.COLUMNS`, `mrr.GAS_COLUMNS`, `mrr.BASIN_SECTOR = 'Oil and Gas Production'`, `mrr.MRRFormatError`.
- `mrr.download(url=URL) -> path` (the one network call; tests patch it), `mrr.read(path, year) -> (rows, gases)`, `mrr.is_basin_wide(row) -> bool`, `mrr.valley_zips() -> {zip5: Region}`, `mrr.apply(rows, gases, year) -> Counter`, `mrr.audit(year, limit=60) -> list[str]`.
- Command: `import_mrr --year 2024 (--path <xlsx> | --url [<url>]) [--report]`. Writes `SourceImport(source='mrr', version=str(year), data_through=date(year, 12, 31), notes={counts})`, calls `stats.clear_caches()`.

- [ ] **Step 1: The sample workbook**

The real file is 1.6 MB with 822 reporters; the sample reproduces its layout (title rows, the header on row 8 of the data sheet and row 6 of the per-gas sheet, wrapped header text, a stray leading space on ` CH4`) with six invented reporters in the fixture's ZIP 93728, one in 90245, and the traps: a fuel supplier with zero emitter CO2e, a basin-wide oil & gas row, a biogenic cogeneration row. Write this to `<worktree>/camp/apps/emissions/tests/data/make_mrr_sample.py` and run it once; keep the script (it documents the fixture) and commit both.

```python
"""Builds mrr-sample.xlsx, a six-reporter stand-in for CARB's MRR workbook with its real layout. Run from the repo root inside the web container."""
from pathlib import Path

import openpyxl

OUT = Path(__file__).with_name('mrr-sample.xlsx')
wb = openpyxl.Workbook()
intro = wb.active
intro.title = 'Introduction'
intro['B1'] = 'Sample built for tests; layout of the 2024 file released November 4, 2025.'
wb.create_sheet('Column Descriptions')['B1'] = 'See the real workbook.'

data = wb.create_sheet('2024 GHG Data')
data['B1'] = 'Released November 4, 2025. '
data['B3'] = 'California Air Resources Board'
data['B5'] = 'Annual Summary of GHG Mandatory Reporting\nNon-Confidential Data for Calendar Year 2024'
data['F7'] = 'Total Emissions\n(metric tons CO2e)'
data['I7'] = 'Entity-Reported GHG Data\n(metric tons CO2e)'
header = {
    'B': 'ARB ID', 'C': 'Facility Name', 'D': 'Report\nYear', 'F': 'Total CO2e \n(combustion, process, vented, and supplier)', 'G': 'AEL',
    'I': 'Emitter CO2e from Non-Biogenic Sources and CH4 and N2O from Biogenic Fuels', 'J': 'Emitter CO2 from Biogenic Fuels',
    'K': 'Emitter CO2 from Non-Exempt Biogenic Fuels', 'L': 'Fuel Supplier CO2e from Non-Biogenic Fuels and CH4 and N2O from Biogenic Fuels',
    'M': 'Fuel Supplier CO2 from Biogenic Fuels', 'N': 'Fuel Supplier CO2 from Non-Exempt Biogenic Fuels', 'O': 'Electricity Importer CO2e ',
    'Q': 'Emitter Covered\nEmissions', 'R': 'Fuel Supplier Covered\nEmissions', 'S': 'Electricity Importer Covered Emissions',
    'T': 'Total Covered Emissions', 'U': 'Total Non-Covered Emissions ', 'W': 'Emissions Data', 'X': 'Product Data', 'Y': 'Verification Body',
    'AA': 'City', 'AB': 'State', 'AC': 'Zip Code', 'AD': 'North American Industry Classification System (NAICS) \nCode and Description',
    'AE': 'U.S.EPA/ARB Subparts', 'AF': 'Industry Sector',
}
for col, text in header.items():
    data[f'{col}8'] = text
# (arb_id, name, total, emitter, biogenic, supplier, city, zip, naics, subparts, sector)
reporters = [
    ('900001', 'Test Plant Inc.', 87635.27178, 87635.27178, 0, 0, 'Fresno', '93728', '327213 - Glass Container Manufacturing', 'C,N', 'Other Combustion Source'),
    ('900002', 'Valley Oil - San Joaquin Valley Basin 745', 2898915.199, 2898915.199, 0, 0, 'Bakersfield', '93728', '211111 - Crude Petroleum and Natural Gas Extraction', 'C,W', 'Oil and Gas Production'),
    ('900003', 'Valley Fuel Supplier', 1554865.449, 0, 0, 1455571.071, 'FRESNO', '93728', '447190 - Other Gasoline Stations', 'MM', 'Transportation Fuel Supplier'),
    ('900004', 'Mojave Kiln Partners', 360659.6584, 351466.6584, 9193, 0, 'Fresno', '93728-1234', '327310 - Cement Manufacturing', 'C,H', 'Cement Plant'),
    ('900005', 'Biomass Cogen', 208512.8079, 7543.573321, 200969.2346, 0, 'Fresno', 93728, '221117 - Biomass Electric Power Generation', 'C', 'Cogeneration'),
    ('900006', 'Coastal Refinery', 113292.6515, 112309.8365, 982.8150558, 0, 'El Segundo', '90245', '324110 - Petroleum Refineries', 'C,Y', 'Refinery'),
]
for i, (arb_id, name, total, emitter, bio, supplier, city, zipcode, naics, subparts, sector) in enumerate(reporters, start=9):
    for col, value in zip(('B', 'C', 'D', 'F', 'G', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'W', 'X', 'AA', 'AB', 'AC', 'AD', 'AE', 'AF'),
                          (arb_id, name, 2024, total, 'No', emitter, bio, 0, supplier, 0, 0, 0, 'Positive', 'N/A', city, 'CA', zipcode, naics, subparts, sector)):
        data[f'{col}{i}'] = value

gas = wb.create_sheet('2024 Emissions by GHG')
gas['B1'] = 'Released November 4, 2025.'
gas['F2'] = '* Entities with Assigned Emissions Levels (AEL) are not assigned individual GHG emissions (i.e., CO2, CH4, and N2O), only Total CO2e emissions.'
gas['B4'] = 'GHG Mandatory Reporting\nEmission Totals by GHG for Calendar Year 2024'
gas['F5'] = 'Total Emissions\n(metric tons)'
for col, text in {'B': 'ARB ID', 'C': 'Facility Name', 'D': 'Reporting Year', 'F': 'CO2', 'G': ' CH4', 'H': 'N2O', 'I': 'AEL*'}.items():
    gas[f'{col}6'] = text
gases = [
    ('900001', 'Test Plant Inc.', 87571.545182, 1.1628941, 0.11628941),
    ('900002', 'Valley Oil - San Joaquin Valley Basin 745', 2860465.0792, 1477.8195, 5.0491),
    ('900003', 'Valley Fuel Supplier', 1527961.6064, 87.212241, 82.964889),
    ('900004', 'Mojave Kiln Partners', 359593.8313, 15.6239017, 2.2658709),
    ('900005', 'Biomass Cogen', 204742.8005, 58.8133385, 7.7170265),
    ('900006', 'Coastal Refinery', 112644.7513, 14.1644386, 0.98587),
]
for i, (arb_id, name, co2, ch4, n2o) in enumerate(gases, start=7):
    for col, value in zip(('B', 'C', 'D', 'F', 'G', 'H', 'I'), (arb_id, name, 2024, co2, ch4, n2o, 'No')):
        gas[f'{col}{i}'] = value
wb.save(OUT)
print(OUT, OUT.stat().st_size, 'bytes')
```

Run: `$MANAGE shell -c "exec(open('/app/camp/apps/emissions/tests/data/make_mrr_sample.py').read())"` (or `python /app/camp/apps/emissions/tests/data/make_mrr_sample.py` with the same compose prefix and service `web`).
Expected: `mrr-sample.xlsx` of roughly 8–12 KB beside the script. Note reporter 900005's ZIP is the integer `93728` (openpyxl gives ints for numeric cells in the real file too) and 900004's is `93728-1234`: the reader must handle both.

- [ ] **Step 2: The failing tests**

Append to `test_ghg.py`:

```python
import shutil
import tempfile

from camp.apps.emissions import mrr

SAMPLE = DATA / 'mrr-sample.xlsx'


class MRRReadTests(TestCase):
    def test_read_finds_headers_and_rows(self):
        rows, gases = mrr.read(SAMPLE, 2024)
        assert [r['arb_id'] for r in rows] == ['900001', '900002', '900003', '900004', '900005', '900006']
        plant = rows[0]
        assert plant['name'] == 'Test Plant Inc.' and plant['co2e'] == 87635.27178 and plant['co2e_biogenic'] == 0
        assert plant['zipcode'] == '93728' and plant['city'] == 'Fresno' and plant['naics'] == '327213'
        assert plant['subparts'] == 'C,N' and plant['sector'] == 'Other Combustion Source'
        assert rows[3]['zipcode'] == '93728-1234' and rows[4]['zipcode'] == '93728'
        assert gases['900001'] == {'co2': 87571.545182, 'ch4': 1.1628941, 'n2o': 0.11628941}
        assert set(gases) == {r['arb_id'] for r in rows}

    def test_other_year_rows_are_skipped_and_missing_columns_fail(self):
        import openpyxl
        wb = openpyxl.load_workbook(SAMPLE)
        wb['2024 GHG Data']['D9'] = 2023
        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
            wb.save(tmp.name)
        rows, _ = mrr.read(tmp.name, 2024)
        assert [r['arb_id'] for r in rows] == ['900002', '900003', '900004', '900005', '900006']
        wb['2024 GHG Data']['I8'] = 'Renamed'
        wb.save(tmp.name)
        with pytest.raises(mrr.MRRFormatError, match='Emitter CO2e'):
            mrr.read(tmp.name, 2024)
        del wb['2024 Emissions by GHG']
        wb.save(tmp.name)
        with pytest.raises(mrr.MRRFormatError, match='2024 Emissions by GHG'):
            mrr.read(tmp.name, 2024)

    def test_basin_wide(self):
        rows, _ = mrr.read(SAMPLE, 2024)
        assert [mrr.is_basin_wide(r) for r in rows] == [False, True, False, False, False, False]
        assert not mrr.is_basin_wide({'name': 'Basin Street Bakery', 'sector': 'Other Combustion Source'})


class ImportMRRTests(GHGTestCase):
    def run_import(self, path=SAMPLE, **options):
        out = StringIO()
        call_command('import_mrr', year=2024, path=str(path), stdout=out, **options)
        return out.getvalue()

    def rows(self):
        return {r.external_id: r for r in GHGReport.objects.filter(program='mrr', year=2024)}

    def test_zip_filter_and_emitter_columns_only(self):
        out = self.run_import()
        rows = self.rows()
        # 900003 has 1.5 MMT of supplier CO2e and no emitter CO2e; 900006 isn't in a Valley ZIP.
        assert set(rows) == {'900001', '900002', '900004', '900005'}
        assert '4 emitters kept, 1 outside the Valley, 1 with no emitter CO2e' in out

    def test_figures_join_match_and_basin(self):
        self.run_import()
        rows = self.rows()
        plant = rows['900001']
        assert plant.facility == self.plant and plant.match_method == 'auto' and plant.county == self.fresno
        assert plant.co2e == 87635.27178 and plant.co2e_biogenic == 0 and plant.ch4 == 1.1628941 and plant.n2o == 0.11628941
        assert plant.naics == '327213' and plant.subparts == 'C,N' and plant.sector == 'Other Combustion Source'
        assert plant.zipcode == '93728' and plant.city == 'Fresno' and plant.point is None and plant.frs_id == ''
        basin = rows['900002']
        assert basin.basin_wide and basin.facility is None and basin.match_method == '' and basin.county == self.fresno
        assert basin.ch4 == 1477.8195
        cogen = rows['900005']
        assert cogen.co2e == 7543.573321 and cogen.co2e_biogenic == 200969.2346 and cogen.facility is None
        assert rows['900004'].zipcode == '93728-1234' and rows['900004'].facility is None

    def test_crosswalk_then_auto(self):
        with patch.dict(ghg_crosswalk.MRR, {'900004': (15, 'KER', 2), '900001': None}, clear=True):
            self.run_import()
        rows = self.rows()
        kiln = rows['900004']
        assert kiln.facility == self.cement and kiln.match_method == 'crosswalk' and kiln.county == self.kern
        assert rows['900001'].facility is None and rows['900001'].match_method == 'crosswalk'
        # Without the crosswalk the auto match is back, and the pinned row stays unmatched.
        self.run_import()
        assert self.rows()['900001'].facility == self.plant and self.rows()['900004'].facility is None

    def test_idempotent_and_prunes(self):
        self.run_import()
        before = stats.generation()
        self.run_import()
        assert stats.generation() == before + 1 and GHGReport.objects.count() == 4
        import openpyxl
        wb = openpyxl.load_workbook(SAMPLE)
        wb['2024 GHG Data'].delete_rows(13)   # Biomass Cogen
        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
            wb.save(tmp.name)
        self.run_import(tmp.name)
        assert set(self.rows()) == {'900001', '900002', '900004'}
        stamp = SourceImport.latest('mrr')
        assert stamp.version == '2024' and stamp.data_through == date(2024, 12, 31) and stamp.notes['deleted'] == 1
        assert SourceImport.objects.filter(source='mrr').count() == 3

    def test_url_downloads_then_cleans_up(self):
        copied = tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False).name
        shutil.copy(SAMPLE, copied)
        with patch('camp.apps.emissions.mrr.download', return_value=copied) as download:
            call_command('import_mrr', year=2024, url=mrr.URL, stdout=StringIO())
        download.assert_called_once_with(mrr.URL)
        assert GHGReport.objects.count() == 4 and not Path(copied).exists()

    def test_report(self):
        out = self.run_import(report=True)
        assert 'Valley Oil - San Joaquin Valley Basin 745' in out and 'basin-wide' in out
        assert 'Mojave Kiln Partners' in out and 'unmatched' in out and 'TEST PLANT' in out
```

Run: `$TEST camp/apps/emissions/tests/test_ghg.py`
Expected: FAIL (`mrr` missing).

- [ ] **Step 3: `mrr.py`**

```python
"""
CARB's Mandatory GHG Reporting (MRR) annual workbook (https://ww2.arb.ca.gov/mrr-data,
one XLSX per year, released each November). Two sheets matter: '<year> GHG
Data' (one row per reporter, with emitter, fuel-supplier and electricity-
importer figures side by side) and '<year> Emissions by GHG' (tons of CO2,
CH4 and N2O). Only the emitter columns are emissions at a place: suppliers
report fuel they sold. Oil & gas production reports per basin, not per
site. There is no county or coordinate, only city and ZIP.
"""
import os
import re
import tempfile
from collections import Counter

import openpyxl
import requests

from django.db import transaction

from camp.apps.emissions import ghg
from camp.apps.emissions.models import GHGReport
from camp.apps.regions.models import Region

URL = 'https://ww2.arb.ca.gov/sites/default/files/classic/cc/reporting/ghg-rep/reported-data/2024-ghg-emissions-2025-11-04.xlsx'
# ww2.arb.ca.gov answers bare clients with 503; a browser User-Agent gets through.
HEADERS = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36 SJVAir'}
DATA_SHEET = '{year} GHG Data'
GAS_SHEET = '{year} Emissions by GHG'
# Column key -> the start of its header, whitespace collapsed. Headers wrap
# and carry qualifiers ("…and CH4 and N2O from Biogenic Fuels"); startswith
# on the collapsed text is the contract, and a renamed column fails read().
COLUMNS = {
    'arb_id': 'ARB ID',
    'name': 'Facility Name',
    'year': 'Report Year',
    'co2e': 'Emitter CO2e from Non-Biogenic Sources',
    'co2e_biogenic': 'Emitter CO2 from Biogenic Fuels',
    'city': 'City',
    'zipcode': 'Zip Code',
    'naics': 'North American Industry Classification System (NAICS)',
    'subparts': 'U.S.EPA/ARB Subparts',
    'sector': 'Industry Sector',
}
GAS_COLUMNS = {'arb_id': 'ARB ID', 'co2': 'CO2', 'ch4': 'CH4', 'n2o': 'N2O'}
HEADER_SCAN_ROWS = 20
BASIN_SECTOR = 'Oil and Gas Production'
_BASIN = re.compile(r'\bbasin\b', re.IGNORECASE)
PROGRAM = GHGReport.Program.MRR


class MRRFormatError(ValueError):
    """The workbook isn't the layout this importer knows: a sheet or a column is missing."""


def download(url=URL):
    """Fetch the workbook to a temp file and return its path (the caller unlinks it). The one network call here."""
    response = requests.get(url, headers=HEADERS, timeout=300)
    response.raise_for_status()
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
        tmp.write(response.content)
    return tmp.name


def _text(value):
    return ' '.join(str(value).split()) if value is not None else ''


def _float(value):
    if value is None or value == '':
        return 0.0
    return float(value)


def _zip(value):
    if isinstance(value, (int, float)):
        return f'{int(value):05d}'
    return _text(value)


def _header(sheet, columns, label):
    """(header row number, {key: column index}) for a sheet whose header row starts with 'ARB ID'."""
    # Row numbers are counted here: read-only empty cells carry none.
    for number, row in enumerate(sheet.iter_rows(min_row=1, max_row=HEADER_SCAN_ROWS), start=1):
        texts = {cell.column: _text(cell.value) for cell in row if cell.value is not None}
        if 'ARB ID' not in texts.values():
            continue
        found = {}
        for key, prefix in columns.items():
            for column, text in texts.items():
                if text.startswith(prefix) and column not in found.values():
                    found[key] = column
                    break
        missing = [columns[key] for key in columns if key not in found]
        if missing:
            raise MRRFormatError(f'{label}: missing column(s) {", ".join(repr(m) for m in missing)}')
        return number, found
    raise MRRFormatError(f'{label}: no header row starting with "ARB ID" in the first {HEADER_SCAN_ROWS} rows')


def read(path, year):
    """(rows, gases) for `year`: rows as dicts keyed by COLUMNS, gases as {arb_id: {co2, ch4, n2o}}."""
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    for name in (DATA_SHEET.format(year=year), GAS_SHEET.format(year=year)):
        if name not in workbook.sheetnames:
            raise MRRFormatError(f'no sheet named {name!r} (sheets: {", ".join(workbook.sheetnames)})')
    data = workbook[DATA_SHEET.format(year=year)]
    header_row, cols = _header(data, COLUMNS, DATA_SHEET.format(year=year))
    rows = []
    for values in data.iter_rows(min_row=header_row + 1, values_only=True):
        cell = lambda key: values[cols[key] - 1] if cols[key] - 1 < len(values) else None
        arb_id = _text(cell('arb_id'))
        if not arb_id or str(_text(cell('year'))) != str(year):
            continue
        rows.append({
            'arb_id': arb_id, 'name': _text(cell('name')), 'year': year,
            'co2e': _float(cell('co2e')), 'co2e_biogenic': _float(cell('co2e_biogenic')),
            'city': _text(cell('city')), 'zipcode': _zip(cell('zipcode')),
            'naics': _text(cell('naics')).split(' ')[0][:8], 'subparts': _text(cell('subparts')), 'sector': _text(cell('sector')),
        })
    gas = workbook[GAS_SHEET.format(year=year)]
    header_row, cols = _header(gas, GAS_COLUMNS, GAS_SHEET.format(year=year))
    gases = {}
    for values in gas.iter_rows(min_row=header_row + 1, values_only=True):
        cell = lambda key: values[cols[key] - 1] if cols[key] - 1 < len(values) else None
        arb_id = _text(cell('arb_id'))
        if arb_id:
            gases[arb_id] = {key: _float(cell(key)) for key in ('co2', 'ch4', 'n2o')}
    workbook.close()
    return rows, gases


def is_basin_wide(row):
    return row.get('sector') == BASIN_SECTOR and bool(_BASIN.search(row.get('name') or ''))


def valley_zips():
    """{zip5: Region} for every ZIP Region we carry: the Valley filter, since MRR has no county."""
    return {region.external_id: region for region in Region.objects.filter(type=Region.Type.ZIPCODE)}


def apply(rows, gases, year):
    """
    Upsert the Valley emitters for `year` in one transaction and delete that
    year's rows no longer in the file. Keeps a row when its ZIP is one of ours
    and its emitter CO2e is positive; matches by crosswalk, then name + ZIP.
    """
    zips = valley_zips()
    county_of_zip = {}
    counts = Counter()
    seen = set()
    with transaction.atomic():
        for row in rows:
            zip5 = row['zipcode'][:5]
            zip_region = zips.get(zip5)
            if zip_region is None:
                counts['outside'] += 1
                continue
            if row['co2e'] <= 0:
                counts['no_emitter'] += 1
                continue
            facility, method = ghg.resolve(PROGRAM, row['arb_id'], name=row['name'], zipcode=zip5)
            if facility is not None and facility.county_id:
                county = facility.county
            else:
                if zip5 not in county_of_zip:
                    county_of_zip[zip5] = Region.objects.get_county_region(zip_region)
                county = county_of_zip[zip5]
            per_gas = gases.get(row['arb_id'], {})
            basin = is_basin_wide(row)
            GHGReport.objects.update_or_create(
                program=PROGRAM, external_id=row['arb_id'], year=year,
                defaults=dict(
                    facility=facility, match_method=method, county=county,
                    name=row['name'][:128], city=row['city'][:64], zipcode=row['zipcode'][:10], naics=row['naics'],
                    sector=row['sector'][:128], subparts=row['subparts'][:128],
                    co2e=row['co2e'], co2e_biogenic=row['co2e_biogenic'],
                    ch4=per_gas.get('ch4'), n2o=per_gas.get('n2o'),
                    point=None, frs_id='', basin_wide=basin,
                ),
            )
            seen.add(row['arb_id'])
            counts['kept'] += 1
            counts[method or 'unmatched'] += 1
            counts['basin'] += int(basin)
        stale = GHGReport.objects.filter(program=PROGRAM, year=year).exclude(external_id__in=seen)
        counts['deleted'] += stale.count()
        stale.delete()
    return counts


def audit(year, limit=60):
    """Lines for curating the crosswalk: the largest emitters, how each matched, and the same-ZIP candidates otherwise."""
    lines = []
    for report in GHGReport.objects.filter(program=PROGRAM, year=year).select_related('facility').order_by('-co2e')[:limit]:
        if report.basin_wide:
            status = 'basin-wide'
        elif report.facility is not None:
            status = f'{report.match_method} -> {report.facility.name} ({report.facility.county_code}, {report.facility.air_district.external_id}, {report.facility.facid})'
        else:
            status = 'unmatched'
        lines.append(f'{report.external_id:>8} {report.co2e:>14,.0f}  {report.name} [{report.zipcode}]: {status}')
        if report.match_method != GHGReport.MatchMethod.CROSSWALK and not report.basin_wide:
            candidates = sorted(((ghg.similarity(report.name, f.name), f) for f in ghg.candidates_in_zip(report.zipcode)), key=lambda p: -p[0])[:3]
            for score, facility in candidates:
                lines.append(f'{"":>24} {score:.2f} {facility.name} ({facility.county_code}, {facility.air_district.external_id}, {facility.facid})')
    return lines
```

`Region.objects.get_county_region` takes a region and returns the county containing it (covers, then largest overlap); it's a spatial query, so it's memoised per ZIP. `ZIPCODE` is `Region.Type.ZIPCODE` (the fixture's `type: zipcode`).

- [ ] **Step 4: The command**

`camp/apps/emissions/management/commands/import_mrr.py`, on the `import_cadd` pattern:

```python
import os
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from camp.apps.emissions import mrr, stats
from camp.apps.emissions.models import SourceImport


class Command(BaseCommand):
    help = (
        "Import CARB's Mandatory GHG Reporting workbook for one year: the Valley's emitters (by ZIP), "
        'emitter CO2e only, per-gas CH4 and N2O, matched to facilities. Idempotent. CARB changes the URL '
        'each November: pass --url <new file> for a new year.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, required=True, help='Data year (the sheet names carry it)')
        source = parser.add_mutually_exclusive_group(required=True)
        source.add_argument('--path', help='A locally downloaded MRR XLSX')
        source.add_argument('--url', nargs='?', const=mrr.URL, help=f'URL to download (default: {mrr.URL})')
        parser.add_argument('--report', action='store_true', help='After importing, print the largest emitters and their match for crosswalk curation')

    def handle(self, *args, **options):
        if options['path']:
            self.run(options['path'], options)
            return
        url = options['url'] or mrr.URL
        self.stdout.write(f'Downloading {url}')
        path = mrr.download(url)
        try:
            self.run(path, options)
        finally:
            os.unlink(path)

    def run(self, path, options):
        year = options['year']
        try:
            rows, gases = mrr.read(path, year)
        except mrr.MRRFormatError as err:
            raise CommandError(str(err))
        counts = mrr.apply(rows, gases, year)
        SourceImport.objects.create(
            source='mrr', version=str(year), data_through=date(year, 12, 31),
            notes={key: counts[key] for key in ('kept', 'outside', 'no_emitter', 'auto', 'crosswalk', 'unmatched', 'basin', 'deleted')},
        )
        stats.clear_caches()
        self.stdout.write(
            f'{len(rows)} reporters in the file: {counts["kept"]} emitters kept, {counts["outside"]} outside the Valley, '
            f'{counts["no_emitter"]} with no emitter CO2e. Matched {counts["auto"]} by name and ZIP, {counts["crosswalk"]} by crosswalk; '
            f'{counts["unmatched"]} unmatched ({counts["basin"]} basin-wide); {counts["deleted"]} deleted.'
        )
        if options['report']:
            self.stdout.write('\n'.join(mrr.audit(year)))
```

Run: `$TEST camp/apps/emissions/tests/test_ghg.py`
Expected: PASS. `test_report` needs "unmatched" in the audit (Mojave Kiln's line) and the plant's name from the candidate lines.

- [ ] **Step 5: Commit**

```bash
git -C <worktree> add camp/apps/emissions/mrr.py camp/apps/emissions/management/commands/import_mrr.py camp/apps/emissions/tests/data/mrr-sample.xlsx camp/apps/emissions/tests/data/make_mrr_sample.py
git -C <worktree> commit -m "feat(emissions): import CARB's Mandatory GHG Reporting workbook for the Valley's emitters (import_mrr)" -- camp/apps/emissions/mrr.py camp/apps/emissions/management/commands/import_mrr.py camp/apps/emissions/tests/data/mrr-sample.xlsx camp/apps/emissions/tests/data/make_mrr_sample.py camp/apps/emissions/tests/test_ghg.py
```

---

### Task 4: Read side: `ghg.facility_card`, `ghg.county_table`, `ghg.stamps`

**Files:**
- Modify: `camp/apps/emissions/ghg.py` (append)
- Modify: `camp/apps/emissions/tests/test_ghg.py` (append)

**Interfaces:**
- `ghg.latest_years() -> {program: year}` (programs with rows only; uncached).
- `ghg.facility_card(facility) -> list[GHGReport] | None`: the newest MRR report, then the newest GHGRP report; `None` when the facility has neither (no card).
- `ghg.county_table(county, limit=10) -> dict | None`: `None` before any import; else `{'years': {'mrr': 2024, 'ghgrp': 2023}, 'rows': [...]}` with each row `{'name', 'facility', 'sector', 'basin_wide', 'mrr', 'ghgrp', 'ch4'}`, one per matched facility (both programs' figures side by side) or per unmatched report, sorted by the larger figure, top `limit`. Cached under `stats.prefix()` for `stats.CACHE_TIMEOUT`.
- `ghg.stamps() -> {'ghgrp': SourceImport | None, 'mrr': SourceImport | None}`.
- Consumed by: Task 5.

- [ ] **Step 1: The failing tests**

Append to `test_ghg.py`:

```python
class ReadSideTests(GHGTestCase):
    def test_facility_card(self):
        assert ghg.facility_card(self.plant) is None
        report('ghgrp', '501', 2022, facility=self.plant, county=self.fresno, co2e=900.0)
        newest = report('ghgrp', '501', 2023, facility=self.plant, county=self.fresno, co2e=1000.0, ch4=2.0)
        mrr_row = report('mrr', '900001', 2024, facility=self.plant, county=self.fresno, co2e=1100.0)
        report('mrr', '900009', 2024, facility=self.cement, county=self.kern, co2e=5.0)
        assert ghg.facility_card(self.plant) == [mrr_row, newest]
        assert newest.source_url == 'https://ghgdata.epa.gov/ghgp/service/facilityDetail/2023?id=501&et=undefined'
        assert mrr_row.source_url == 'https://ww2.arb.ca.gov/mrr-data'

    def test_county_table_unifies_the_programs(self):
        assert ghg.county_table(self.fresno) is None
        report('mrr', '900001', 2024, facility=self.plant, county=self.fresno, co2e=1100.0, name='Test Plant Inc.', sector='Other Combustion Source')
        report('ghgrp', '501', 2023, facility=self.plant, county=self.fresno, co2e=1000.0, ch4=3.0, name='TEST PLANT (EPA)', sector='Direct Emitter')
        report('ghgrp', '501', 2022, facility=self.plant, county=self.fresno, co2e=5.0)   # an older year: ignored
        report('mrr', '900002', 2024, county=self.fresno, co2e=2898915.0, name='Valley Oil - SJV Basin', basin_wide=True, ch4=1477.8, sector='Oil and Gas Production')
        report('ghgrp', '503', 2023, county=self.fresno, co2e=800.0, name='Lonely Landfill')
        report('ghgrp', '601', 2023, county=self.kern, co2e=30000.0, name='Basin Gathering')
        table = ghg.county_table(self.fresno)
        assert table['years'] == {'mrr': 2024, 'ghgrp': 2023}
        assert [row['name'] for row in table['rows']] == ['Valley Oil - SJV Basin', 'TEST PLANT', 'Lonely Landfill']
        basin, plant, landfill = table['rows']
        assert basin['basin_wide'] and basin['facility'] is None and basin['mrr'] == 2898915.0 and basin['ghgrp'] is None and basin['ch4'] == 1477.8
        assert plant['facility'] == self.plant and plant['mrr'] == 1100.0 and plant['ghgrp'] == 1000.0 and plant['ch4'] == 3.0
        assert plant['sector'] == 'Other Combustion Source' and not plant['basin_wide']
        assert landfill['ghgrp'] == 800.0 and landfill['mrr'] is None and landfill['facility'] is None
        assert [row['name'] for row in ghg.county_table(self.kern)['rows']] == ['Basin Gathering']

    def test_county_table_is_cached_under_the_stats_generation(self):
        report('mrr', '1', 2024, county=self.fresno, co2e=10.0, name='One')
        assert len(ghg.county_table(self.fresno)['rows']) == 1
        report('mrr', '2', 2024, county=self.fresno, co2e=20.0, name='Two')
        assert len(ghg.county_table(self.fresno)['rows']) == 1
        stats.clear_caches()
        assert len(ghg.county_table(self.fresno)['rows']) == 2

    def test_limit(self):
        for i in range(12):
            report('mrr', str(i), 2024, county=self.fresno, co2e=float(i), name=f'R{i}')
        assert len(ghg.county_table(self.fresno)['rows']) == 10
        assert ghg.county_table(self.fresno, limit=3)['rows'][0]['name'] == 'R11'

    def test_stamps(self):
        assert ghg.stamps() == {'ghgrp': None, 'mrr': None}
        SourceImport.objects.create(source='mrr', version='2024', data_through=date(2024, 12, 31))
        assert ghg.stamps()['mrr'].version == '2024' and ghg.stamps()['ghgrp'] is None
```

Run: `$TEST camp/apps/emissions/tests/test_ghg.py::ReadSideTests`
Expected: FAIL (`ghg` has no `facility_card`).

- [ ] **Step 2: The read side**

Append to `ghg.py` (add `from django.core.cache import cache`, `from django.db.models import Max, Q` and `from camp.apps.emissions import stats` to its imports; `stats` doesn't import `ghg`, so there's no cycle; `SourceImport` joins the models import):

```python
PROGRAMS = (GHGReport.Program.MRR, GHGReport.Program.GHGRP)


def latest_years():
    """{program: its newest year with rows}; empty before any import."""
    years = {}
    for program in PROGRAMS:
        year = GHGReport.objects.filter(program=program).aggregate(year=Max('year'))['year']
        if year is not None:
            years[str(program)] = year
    return years


def facility_card(facility):
    """The facility's newest report per program (MRR first, the newer year), or None for no card."""
    rows = []
    for program in PROGRAMS:
        report = facility.ghg_reports.filter(program=program).order_by('-year', '-pk').first()
        if report is not None:
            rows.append(report)
    return rows or None


def county_table(county, limit=10):
    """
    The county's largest reporters across both programs' newest years: one
    row per matched facility (both figures), one per unmatched report. None
    before any import (not cached, so the first import shows up at once).
    """
    years = latest_years()
    if not years:
        return None

    def compute():
        wanted = Q()
        for program, year in years.items():
            wanted |= Q(program=program, year=year)
        groups = {}
        reports = GHGReport.objects.filter(county=county).filter(wanted).select_related('facility').order_by('program', '-co2e')
        for report in reports:
            key = ('facility', report.facility_id) if report.facility_id else (report.program, report.external_id)
            row = groups.setdefault(key, {
                'name': report.facility.name if report.facility_id else report.name,
                'facility': report.facility, 'sector': '', 'basin_wide': False, 'mrr': None, 'ghgrp': None, 'ch4': None,
            })
            row[str(report.program)] = report.co2e
            row['sector'] = row['sector'] or report.sector
            row['basin_wide'] = row['basin_wide'] or report.basin_wide
            if report.ch4 is not None:
                row['ch4'] = max(row['ch4'] or 0.0, report.ch4)
        rows = sorted(groups.values(), key=lambda row: -max(row['mrr'] or 0.0, row['ghgrp'] or 0.0))
        return {'years': years, 'rows': rows[:limit]}

    return cache.get_or_set(f'{stats.prefix()}:ghg-county:{county.pk}:{limit}', compute, stats.CACHE_TIMEOUT)


def stamps():
    return {str(program): SourceImport.latest(str(program)) for program in (GHGReport.Program.GHGRP, GHGReport.Program.MRR)}
```

`order_by('program', '-co2e')` puts `ghgrp` before `mrr`, so a matched facility's row takes the *MRR* sector last (the `or` keeps the first non-empty, GHGRP's "Direct Emitter"); the test expects MRR's "Other Combustion Source", so order MRR first: use `order_by('-program', '-co2e')` (`'mrr' > 'ghgrp'` sorts first descending). Keep whichever passes `test_county_table_unifies_the_programs` and add a one-line comment saying MRR's sector is the more descriptive one.

Run: `$TEST camp/apps/emissions/tests/test_ghg.py`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git -C <worktree> commit -m "feat(emissions): the greenhouse-gas facility card and county table read side" -- camp/apps/emissions/ghg.py camp/apps/emissions/tests/test_ghg.py
```

---

### Task 5: Pages: the facility card, the county table, About and integrations

**Files:**
- Create: `camp/templates/emissions/includes/ghg-card.html`, `camp/templates/emissions/includes/ghg-table.html`
- Modify: `camp/apps/emissions/views.py` (`FacilityDetail.get_context_data`, `AreaPage.get_context_data`, `RegionPage.get_context_data`, `About.get_context_data`)
- Modify: `camp/templates/emissions/facility-detail.html`, `camp/templates/emissions/area.html`, `camp/templates/emissions/about.html`, `datafiles/data-integrations.yaml`
- Modify: `camp/apps/emissions/tests/test_ghg.py` (append)

**Interfaces:**
- Context: `ghg_card` (facility page; `list[GHGReport] | None`), `ghg_table` (area pages; the `county_table` dict on county pages, `None` elsewhere), `ghg_stamps` (About).
- No new URLs, JS or Sass.

- [ ] **Step 1: The failing tests**

Append to `test_ghg.py`:

```python
from django.urls import reverse


class GHGPageTests(GHGTestCase):
    def detail(self, facility, **params):
        return self.client.get(facility.get_absolute_url(), params).content.decode()

    def test_no_card_without_reports(self):
        content = self.detail(self.plant)
        assert 'Greenhouse gases' not in content and 'id="greenhouse-gases"' not in content

    def test_card(self):
        report('mrr', '900001', 2024, facility=self.plant, county=self.fresno, co2e=87635.27, ch4=1.1628941, n2o=0.11628941)
        report('ghgrp', '501', 2023, facility=self.plant, county=self.fresno, co2e=71574.356, ch4=0.97, n2o=0.097, co2e_biogenic=12.4)
        content = self.detail(self.plant)
        card = content[content.index('id="greenhouse-gases"'):content.index('Source: California Air Resources Board')]
        assert '<h3 class="title is-4">Greenhouse gases</h3>' in card
        assert '2024: 87,635 t CO2e (CH4 1.2 t, N2O 0.1 t)' in card
        assert '2023: 71,574 t CO2e (CH4 1.0 t, N2O 0.1 t), plus 12 t biogenic CO2' in card
        assert card.index('2024:') < card.index('2023:')
        assert 'href="https://ww2.arb.ca.gov/mrr-data">CARB MRR →</a>' in card
        assert 'href="https://ghgdata.epa.gov/ghgp/service/facilityDetail/2023?id=501&amp;et=undefined">EPA GHGRP →</a>' in card
        assert "Dairies don't report to either program." in card
        # A report with no per-gas figures has no parenthetical.
        GHGReport.objects.filter(external_id='900001').update(ch4=None, n2o=None)
        assert '2024: 87,635 t CO2e ·' in self.detail(self.plant)

    def test_county_table(self):
        report('mrr', '900002', 2024, county=self.fresno, co2e=2898915.2, name='Valley Oil - San Joaquin Valley Basin 745', basin_wide=True, ch4=1477.8, sector='Oil and Gas Production')
        report('mrr', '900001', 2024, facility=self.plant, county=self.fresno, co2e=87635.27, ch4=1.16, name='Test Plant Inc.', sector='Other Combustion Source')
        report('ghgrp', '501', 2023, facility=self.plant, county=self.fresno, co2e=71574.4, ch4=0.97)
        report('ghgrp', '503', 2023, county=self.fresno, co2e=800.0, name='Lonely Landfill', sector='Direct Emitter')
        content = self.client.get(self.fresno.get_emissions_url(), {'year': '2024'}).content.decode()
        table = content[content.index('id="greenhouse-gases"'):]
        assert '<h2 class="title is-4">Largest greenhouse-gas reporters</h2>' in table
        assert '<th class="has-text-right">CARB MRR 2024</th>' in table and '<th class="has-text-right">EPA GHGRP 2023</th>' in table
        assert table.index('Valley Oil') < table.index('Test Plant') < table.index('Lonely Landfill')
        assert 'basin-wide, not one site' in table
        assert f'href="{self.plant.get_absolute_url()}' in table and '>Test Plant</a>' in table
        assert 'not matched to a permitted facility' in table
        assert '2,898,915' in table and '87,635' in table and '71,574' in table and '1,478' in table
        assert 'Only large emitters (about 10,000 t CO2e a year and up) report' in table
        assert '<a href="#greenhouse-gases">Greenhouse gases</a>' in content
        # Other counties and non-county pages have no table.
        assert 'greenhouse-gas reporters' not in self.client.get(self.kern.get_emissions_url(), {'year': '2024'}).content.decode()
        near = self.client.get(reverse('emissions:near-me'), {'lat': '36.737', 'lng': '-119.787', 'radius': '1'}).content.decode()
        assert 'greenhouse-gas reporters' not in near

    def test_about_and_integrations(self):
        content = self.client.get(reverse('emissions:about')).content.decode()
        assert '<h2 id="greenhouse-gases">Greenhouse gases</h2>' in content
        assert 'No greenhouse-gas data has been imported yet.' in content
        assert 'Greenhouse gases warm the climate' in content
        SourceImport.objects.create(source='ghgrp', version='2023', data_through=date(2023, 12, 31))
        SourceImport.objects.create(source='mrr', version='2024', data_through=date(2024, 12, 31))
        content = self.client.get(reverse('emissions:about')).content.decode()
        assert 'EPA GHGRP reporting year 2023; CARB MRR data year 2024.' in content
        assert 'ghgdata.epa.gov' in content and 'ww2.arb.ca.gov/mrr-data' in content
        integrations = self.client.get('/about/integrations/').content.decode()
        assert 'EPA Greenhouse Gas Reporting Program' in integrations and 'CARB Mandatory GHG Reporting' in integrations
```

Run: `$TEST camp/apps/emissions/tests/test_ghg.py::GHGPageTests`
Expected: FAIL on the card heading.

- [ ] **Step 2: The two includes**

`camp/templates/emissions/includes/ghg-card.html`:

```django
{% load emissions_explorer %}
{% comment %}
A facility's newest greenhouse-gas report per program (ghg.facility_card):
metric tons a year, CO2e with CH4 and N2O as tons of gas, biogenic CO2
apart. Rendered only when the facility has a report: most don't, because
only large emitters report, and that absence isn't a figure.
{% endcomment %}
<section class="ghg-card mt-5" id="greenhouse-gases">
    <h3 class="title is-4">Greenhouse gases</h3>
    <ul>
    {% for r in ghg_card %}
        <li>{{ r.year }}: {{ r.co2e|whole }} t CO2e{% if r.ch4 is not None or r.n2o is not None %} (CH4 {{ r.ch4|quantity }} t, N2O {{ r.n2o|quantity }} t){% endif %}{% if r.co2e_biogenic %}, plus {{ r.co2e_biogenic|whole }} t biogenic CO2{% endif %} · <a href="{{ r.source_url }}">{{ r.get_program_display }} →</a></li>
    {% endfor %}
    </ul>
    <details class="ghg-caveats is-size-7">
        <summary>What this is, and isn't</summary>
        <p>Greenhouse gases warm the climate; they aren't a local health measure. Only large emitters (about 10,000 t CO2e a year and up) report, so most facilities have none. Oil and gas production reports for a whole basin, not one site. Fuel sold by suppliers isn't counted here. Dairies don't report to either program.</p>
    </details>
</section>
```

`camp/templates/emissions/includes/ghg-table.html`:

```django
{% load emissions_explorer %}
{% comment %}
A county's largest greenhouse-gas reporters (ghg.county_table): both
programs' newest years side by side, matched reporters linking to their
facility page, basin-wide oil & gas rows and unmatched reporters labelled.
{% endcomment %}
<section class="ghg-table mt-5" id="greenhouse-gases">
    <h2 class="title is-4">Largest greenhouse-gas reporters</h2>
    <p class="is-size-7 has-text-grey">Metric tons CO2e a year, as reported to CARB and EPA. Greenhouse gases warm the climate; they aren't a local health measure. Only large emitters (about 10,000 t CO2e a year and up) report, so most facilities have none. Oil and gas production reports for a whole basin, not one site. Fuel sold by suppliers isn't counted here. Dairies don't report to either program.</p>
    <div class="table-container">
    <table class="table is-fullwidth is-narrow">
        <thead><tr>
            <th>Reporter</th><th>Sector</th>
            {% if ghg_table.years.mrr %}<th class="has-text-right">CARB MRR {{ ghg_table.years.mrr }}</th>{% endif %}
            {% if ghg_table.years.ghgrp %}<th class="has-text-right">EPA GHGRP {{ ghg_table.years.ghgrp }}</th>{% endif %}
            <th class="has-text-right">CH4 (t)</th>
        </tr></thead>
        <tbody>
        {% for row in ghg_table.rows %}
        <tr>
            <td>{% if row.facility %}<a href="{{ row.facility.get_absolute_url }}{{ scope_qs }}">{{ row.name|title }}</a>{% else %}{{ row.name }} {% if row.basin_wide %}<span class="tag is-light">basin-wide, not one site</span>{% else %}<span class="has-text-grey is-size-7">not matched to a permitted facility</span>{% endif %}{% endif %}</td>
            <td>{{ row.sector }}</td>
            {% if ghg_table.years.mrr %}<td class="has-text-right">{% if row.mrr is not None %}{{ row.mrr|whole }}{% else %}—{% endif %}</td>{% endif %}
            {% if ghg_table.years.ghgrp %}<td class="has-text-right">{% if row.ghgrp is not None %}{{ row.ghgrp|whole }}{% else %}—{% endif %}</td>{% endif %}
            <td class="has-text-right">{% if row.ch4 is not None %}{{ row.ch4|whole }}{% else %}—{% endif %}</td>
        </tr>
        {% endfor %}
        </tbody>
    </table>
    </div>
</section>
```

`scope_qs` is the area page's scope query string (already in the context, `?year=…` or empty). `whole` rounds to a whole number with commas; `quantity` keeps one decimal.

- [ ] **Step 3: Views and templates**

`views.py`: add `ghg` to `from camp.apps.emissions import …`.

- `FacilityDetail.get_context_data`: add `ghg_card=ghg.facility_card(facility)`.
- `AreaPage.get_context_data`: next to `kwargs.setdefault('within', None)`, add `kwargs.setdefault('ghg_table', None)`.
- `RegionPage.get_context_data`: pass `ghg_table=ghg.county_table(region) if region.type == Region.Type.COUNTY else None`.
- `About.get_context_data`: add `ghg_stamps=ghg.stamps()`.

`facility-detail.html`: after the compliance card include (`{% if compliance_card %}…{% endif %}`, Phase 4) and before the `Source:` paragraph, add `{% if ghg_card %}{% include 'emissions/includes/ghg-card.html' %}{% endif %}`.

`area.html`: after the `<div class="columns mt-5">…</div>` holding "By sector" and the trend chart, and before Phase 7's `{% if wells_block %}` line (or `{% if dairy_block %}` if wells isn't there), add `{% if ghg_table.rows %}{% include 'emissions/includes/ghg-table.html' %}{% endif %}`. In the section nav, add `or ghg_table.rows` to whatever condition the earlier phases left (`{% if dairy_block.has_dairies or within.any or … %}`) and, right before the Dairies link, `{% if ghg_table.rows %} · <a href="#greenhouse-gases">Greenhouse gases</a>{% endif %}`.

`about.html`, before `<h2 id="sources">`:

```django
<h2 id="greenhouse-gases">Greenhouse gases</h2>
<p>Facility pages for the largest emitters carry a <strong>Greenhouse gases</strong> card, and county pages a <strong>Largest greenhouse-gas reporters</strong> table, from two programs: EPA's <a href="https://ghgdata.epa.gov/flight">Greenhouse Gas Reporting Program</a> (GHGRP) and CARB's <a href="https://ww2.arb.ca.gov/mrr-data">Mandatory GHG Reporting</a> (MRR). {% if ghg_stamps.ghgrp or ghg_stamps.mrr %}{% if ghg_stamps.ghgrp %}EPA GHGRP reporting year {{ ghg_stamps.ghgrp.version }}{% if ghg_stamps.mrr %}; {% endif %}{% endif %}{% if ghg_stamps.mrr %}CARB MRR data year {{ ghg_stamps.mrr.version }}{% endif %}.{% else %}No greenhouse-gas data has been imported yet.{% endif %}</p>
<ul>
    <li><strong>Greenhouse gases warm the climate; they aren't a local health measure.</strong> Only large emitters (about 10,000 t CO2e a year and up) report, so most facilities have none. Oil and gas production reports for a whole basin, not one site. Fuel sold by suppliers isn't counted here. Dairies don't report to either program.</li>
    <li><strong>Metric tons.</strong> CO2e is the emitter's own non-biogenic total. CH4 and N2O are tons of the gas, not CO2e; biogenic CO2 (from burning biomass) is shown apart.</li>
    <li><strong>How reporters are matched.</strong> EPA's registry carries the Valley Air District's facility id for most of its reporters, so those matches are exact. CARB's file has only a name, a city and a ZIP; the largest CARB reporters are matched by hand, the rest only when the name clearly matches a facility in the same ZIP. A reporter we couldn't match still appears on its county's table, never on a facility page.</li>
    <li><strong>Years differ.</strong> EPA's newest published year is 2023 (EPA has proposed ending the program); CARB publishes the previous year each November.</li>
</ul>
```

Add to the Sources list: `<li><a href="https://ghgdata.epa.gov/flight">EPA Greenhouse Gas Reporting Program (FLIGHT)</a> via <a href="https://www.epa.gov/enviro/greenhouse-gas-customized-search">Envirofacts</a></li>` and `<li><a href="https://ww2.arb.ca.gov/mrr-data">CARB Mandatory GHG Reporting data</a></li>`.

`datafiles/data-integrations.yaml`, under `Emissions Data` after the last existing entry there:

```yaml
    - name: EPA Greenhouse Gas Reporting Program
      logo: img/logo/epa-vertical.svg
      url: https://ghgdata.epa.gov/flight
      description: EPA's Greenhouse Gas Reporting Program collects annual greenhouse-gas totals from the largest emitters — power plants, refineries, landfills, oil and gas fields and heavy industry — with each one's location and its ids in other federal systems. SJVAir imports the Valley's reporters, links them to the Valley Air District's facilities through EPA's facility registry, and shows each one's CO2e, methane and nitrous oxide on its facility page.

    - name: CARB Mandatory GHG Reporting
      logo: img/logo/carb-vertical.png
      url: https://ww2.arb.ca.gov/mrr-data
      description: California's Mandatory Greenhouse Gas Reporting program publishes a verified annual summary of every large emitter's greenhouse gases, a year sooner than the federal program and including California-only reporters. SJVAir imports the Valley's emitters (only their own emissions, never the fuel that suppliers sell), matches the largest to their permitted facilities by hand and the rest by name and ZIP, and lists each county's largest reporters.
```

Run: `$TEST camp/apps/emissions/tests/test_ghg.py camp/apps/emissions/tests/test_facility_page.py camp/apps/emissions/tests/test_areas_pages.py camp/apps/emissions/tests/test_views.py`
Expected: PASS. If `test_about_and_integrations` fails on the integrations page, check the yaml indentation matches its neighbours (four spaces before `- name:`).

- [ ] **Step 4: Commit**

```bash
git -C <worktree> add camp/templates/emissions/includes/ghg-card.html camp/templates/emissions/includes/ghg-table.html
git -C <worktree> commit -m "feat(emissions): the greenhouse-gas facility card, county reporters table, About section and integrations" -- camp/apps/emissions/views.py camp/templates/emissions/includes/ghg-card.html camp/templates/emissions/includes/ghg-table.html camp/templates/emissions/facility-detail.html camp/templates/emissions/area.html camp/templates/emissions/about.html datafiles/data-integrations.yaml camp/apps/emissions/tests/test_ghg.py
```

---

### Task 6: Crosswalk curation on the dev DB, full run, smoke, PR notes

**Files:**
- Modify: `camp/apps/emissions/ghg_crosswalk.py`
- No other code changes; this task runs the imports for real and writes the PR description.

**Interfaces:** none new. Uses `import_mrr --report` (Task 3) and the admin (`/admin/emissions/ghgreport/`).

- [ ] **Step 1: Migrate the dev DB and run both imports**

The dev server on :8003 is the container to use (`docker ps --filter publish=8003`; never stop it). `DEV` below is `docker exec $(docker ps --filter publish=8003 --format '{{.Names}}')`.

```bash
$DEV python manage.py migrate emissions
$DEV python manage.py import_ghgrp --year 2023
```

Expected: eight county lines in a few minutes (≈350 Envirofacts calls; the API throttles, `fetch_json` retries). Totals to compare with the research: about 169 reporters, ~87 `frs`, ~15 `auto`, the rest unmatched (field-level oil & gas, Eastern Kern `CAKCA…` ids). Markedly fewer `frs` than 80 means the FRS parse or the `AIR` acronym changed: open one `frs_url` in a browser and compare before going on.

```bash
curl -sS -A 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36' \
  -o /tmp/claude-1000/-home-derek-dev-ccac-sjvair-com/d44a9b36-1d95-48d8-9dc1-7d9a1cd0932f/scratchpad/mrr-2024.xlsx \
  'https://ww2.arb.ca.gov/sites/default/files/classic/cc/reporting/ghg-rep/reported-data/2024-ghg-emissions-2025-11-04.xlsx'
docker cp /tmp/claude-1000/-home-derek-dev-ccac-sjvair-com/d44a9b36-1d95-48d8-9dc1-7d9a1cd0932f/scratchpad/mrr-2024.xlsx $(docker ps --filter publish=8003 --format '{{.Names}}'):/tmp/mrr-2024.xlsx
$DEV python manage.py import_mrr --year 2024 --path /tmp/mrr-2024.xlsx --report > /tmp/claude-1000/-home-derek-dev-ccac-sjvair-com/d44a9b36-1d95-48d8-9dc1-7d9a1cd0932f/scratchpad/mrr-report.txt
head -3 /tmp/claude-1000/-home-derek-dev-ccac-sjvair-com/d44a9b36-1d95-48d8-9dc1-7d9a1cd0932f/scratchpad/mrr-report.txt
```

Expected first line: about `822 reporters in the file: ~146 emitters kept, ~660 outside the Valley, ~20 with no emitter CO2e`, with roughly 75–85% of the kept rows matched by name and ZIP. (If `--url` is used instead, a 503 means the User-Agent header was dropped; the download must send `mrr.HEADERS`.) If the file has moved, find the current link on `https://ww2.arb.ca.gov/mrr-data` and update `mrr.URL` in the same commit.

- [ ] **Step 2: Curate the crosswalk**

Work through `mrr-report.txt` from the top. For every one of the **40 largest emitters**, and any lower row whose auto match looks wrong, decide the facility and write it into `ghg_crosswalk.MRR`, sorted by CO2e, one comment per line with the CEIDARS name and today's date. Rules:

- A basin-wide oil & gas row (`basin-wide` in the report) gets `None`.
- An `auto` match is kept only when the candidate is plainly the same site (same operator, same city); otherwise pin the right key, or `None` when no CEIDARS facility is that site.
- An `unmatched` row gets its key when one of the candidate lines (or an admin search at `/admin/emissions/facility/?q=<part of the name>`) is plainly it. Same-ZIP candidates are printed with their key; for a facility in a neighbouring ZIP search the admin.
- The research's known cases must come out right: **Mt. Poso Cogeneration** is not Sycamore Cogeneration and **Sentinel Peak Resources** is not Seneca (pin each to its own facility, or `None`); **La Paloma Generating**, **Tracy Combined Cycle** (GWF) and **Lodi Energy Center** are pinned to their facilities, which the name match misses. Look each up:
  `$DEV python manage.py shell -c "from camp.apps.emissions.models import Facility; [print(f.county_code, f.air_district.external_id, f.facid, f.name, f.address) for f in Facility.objects.filter(name__icontains='PALOMA')]"`
- Leave `GHGRP` alone unless the admin list (`/admin/emissions/ghgreport/?program=ghgrp&match_method=`) shows an unmatched reporter that is obviously one facility (a landfill, a glass plant, a winery within a kilometre of its CEIDARS twin under a different name): pin it by `facility_id`.

Re-run `import_mrr --path … --report` and `import_ghgrp --year 2023` after editing (the container sees the worktree's files only if it mounts it; otherwise `docker cp` the crosswalk module in, and remember the dev container's copy is not the one under test). Check the report's top 40 are all `crosswalk`, a verified `auto`, or `basin-wide`, and the Kern county page's table on :8003 (`/tools/emissions/region/<kern sqid>/kern/`) reads sensibly: CRC's basin row on top with the tag, then refineries and power plants linking to their pages.

- [ ] **Step 3: Tests, full suites, smoke**

Run: `$TEST camp/apps/emissions/tests/test_ghg.py`
Expected: PASS (the crosswalk tests use `patch.dict(..., clear=True)`, so the real entries don't leak in).

Run: `$TEST camp/apps/emissions camp/api/v2/emissions camp/apps/regions`
Expected: all PASS. (Remember the shared `db` container: a full-suite failure that isn't in a GHG file may be another session's run; re-run the failing file alone before treating it as real.)

Run the smoke (no map changes here, so this is a regression check): `/home/derek/.claude/jobs/d44a9b36/tmp/venv/bin/python scripts/emissions_map_smoke.py --base http://localhost:8003`
Expected: passes as before this phase.

Open on :8003 and look: Ardagh Glass (Madera) facility page — a card with both a 2024 MRR line and a 2023 GHGRP line, both links working; a facility with no reports (any gas station) — no card; the Kern and Fresno county pages — the table and the section-nav link; About — the section with both years; `/about/integrations/` — the two new cards with logos.

- [ ] **Step 4: Commit the crosswalk**

```bash
git -C <worktree> commit -m "feat(emissions): curate the MRR crosswalk for the Valley's largest greenhouse-gas emitters" -- camp/apps/emissions/ghg_crosswalk.py
git -C <worktree> log --oneline -7
```

Expected: the six commits of this plan on `feature/emissions-ghg`, nothing staged, no other files touched (`git -C <worktree> status --short` shows only pre-existing untracked files).

- [ ] **Step 5: PR notes (write them into the PR description; do not commit a notes file)**

Include, under "Deploy":

1. `python manage.py migrate` (adds `emissions_ghgreport`).
2. One-off imports, in either order, each a few minutes as a one-off dyno:
   `python manage.py import_ghgrp --year 2023`
   `python manage.py import_mrr --year 2024 --url`
   Both are idempotent; both bump the explorer cache generation, so the county pages pick the tables up at once.
3. Yearly refresh, by hand: CARB posts the new MRR workbook each November at `https://ww2.arb.ca.gov/mrr-data` (update `mrr.URL`, or pass `--url <file>`); run `import_mrr --year <Y> --url --report` and review the report's top 40 against `ghg_crosswalk.MRR` (new large emitters, renamed ones). EPA's RY2024 data, if it is published, is `import_ghgrp --year 2024` (GWPs switch to AR5 automatically). EPA has proposed ending the GHGRP; if `pub_dim_facility` returns nothing for a year, that's why.
4. Match rates seen on the dev DB (fill in from Step 1: GHGRP `frs`/`auto`/unmatched counts; MRR kept/auto/crosswalk/unmatched).

Under "Decisions", note: `GHGReport.county` added beyond the spec so unmatched reporters have a county page; the county table unifies both programs into one row per facility rather than two tables; no map layer, list filter or periodic task, per the spec.

---

## Notes for the implementer

- **Envirofacts quirks.** Only the plain `table/column/value/…/JSON` form works (`ghg.`-prefixed table names and `/=/` return parse errors). The county filter is server-side (`county_fips/06039`), which is why `import_ghgrp` makes eight facility calls, not one statewide one. Emission rows repeat per `sector_id`/`subsector_id`; `gas_totals` sums them. `frs_program_facility` also lists `AIRS/AFS` (`06039C0801`, the legacy id) and `E-GGRT` (the GHGRP id itself); only `AIR` is parsed.
- **MRR quirks.** Headers wrap across lines and one (` CH4`) has a leading space: match on whitespace-collapsed `startswith`. ZIPs arrive as ints, 5-digit strings or ZIP+4. `Total CO2e` includes supplier and importer figures and is never used. Reporters with an Assigned Emissions Level (`AEL` = Yes) have a total but no per-gas split; `ch4`/`n2o` come through as 0 from the per-gas sheet for them, which is what CARB publishes.
- **Why the auto match is strict.** A wrong match puts one company's emissions on another's facility page under that company's name. Unmatched rows lose nothing: they show on the county table with a label.
- **Caches.** `county_table` is keyed under `stats.prefix()`, so `stats.clear_caches()` (called by both imports and by every other emissions import) orphans it; `facility_card` is two indexed queries and isn't cached.
