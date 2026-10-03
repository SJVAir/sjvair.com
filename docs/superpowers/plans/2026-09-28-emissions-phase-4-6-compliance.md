# Emissions Phase 4 (EPA ICIS-Air compliance) and Phase 6 (dairy Water Board compliance) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two compliance feeds on the explorer, each shipping as its own PR. **Part A (Phase 4):** import EPA's ICIS-Air bulk files monthly, match the SJVAPCD rows to CEIDARS facilities through the facility id embedded in `PGM_SYS_ID`, and show a "Compliance (federal Clean Air Act reporting)" card on matched facility pages, a compliance filter on the facility list and a one-line count on region pages. **Part B (Phase 6):** import the Central Valley Water Board's dairy enrollments and enforcement actions (CIWQS, via data.ca.gov) monthly, joined to CADD dairies on `place_id`, and show them in the dairy table (a column and a filter), the dairy popup and a headline tile on dairy area pages.

**Architecture:**
- **Shared stamp.** `SourceImport` (spec §Shared) records each import's `data_through`; both parts write one row per run and the templates read it for "Reported through {date}". Phase 1 creates this model; Task 1 creates it here only if it isn't there yet.
- **Part A.** `camp/apps/emissions/icis.py` parses `PGM_SYS_ID`, streams the six CSVs out of the zip (never unpacked to disk), filters to CA + the covered counties and writes `AirComplianceFacility` / `ComplianceEvent` in one transaction. `camp/apps/emissions/compliance.py` holds the read side: the facility card's rollups and the region line's counts. `stats.facility_table()` gains a `compliance` filter the list and CSV use. `camp/apps/emissions/tasks.py` (new) registers the monthly task on the `primary` queue under `lock_task`.
- **Part B.** `camp/apps/emissions/ciwqs.py` resolves each CKAN resource's current CSV URL (`resource_show`), streams the two CSVs, keeps region 5 CAFO rows and enforcement rows whose facility id is a CADD `place_id`, and writes `DairyWaterEnrollment` / `DairyEnforcementAction` in one transaction. `dairies.py` gains the five-year window and an `actions_5y` annotation on `table()`, a `water_actions` key on `summary()`, and an `enforcement` filter; the dairy popup endpoint gains a `water_board` block that `dairy-map.js` renders.
- **Windows.** "Last 5 years" is always measured back from the source's `data_through` (the newest event date in the file), never from today: the feeds run a year or more late, and a window from today would read as "nothing recent" when the truth is "not reported yet".

**Tech Stack:** Django/GeoDjango + PostGIS, django-vanilla-views, django-resticus, django-huey (`db_periodic_task`, `lock_task`), `requests`, stdlib `zipfile`/`csv`, MapTiler SDK popup (`assets/js/emissions/dairy-map.js`), Bulma.

**Spec:** `docs/superpowers/specs/2026-09-28-emissions-data-expansion-design.md`, sections "Shared: SourceImport", "Phase 4" and "Phase 6". Research: `.superpowers/research/compliance.md` (the verified column names, join and match rates, the caveats).

## Global Constraints

- **Where to work.** A new branch stacked on `feature/ceidars-explorer`, after the dairy region pages plan (`docs/superpowers/plans/2026-09-28-dairy-region-pages.md`) has landed: this plan reads `dairy_views.search_filters`, `DairyAreaPage`, `includes/dairy-stats.html` and `dairy-area.html` as that plan leaves them. One branch per part (`feature/icis-air-compliance` for Tasks 1–6, `feature/ciwqs-dairies` for Tasks 7–10); Part B's branch is stacked on Part A's only if Part A hasn't merged, and only for `SourceImport` (see Task 7 Step 0). Use `git -C <worktree>` for every git command; never touch `/home/derek/dev/ccac/sjvair.com` (the main checkout).
- **Tests** use `django.test.TestCase` with plain `assert`; fixtures `regions.yaml`, `emissions.yaml`. Helpers in `camp/apps/emissions/tests`: `make`, `AROUND_PLANT` (test_areas), `make_dairies`, `make_dairy`, `IN_KERN` (test_dairies), `scope` (test_stats).
- **Tests never hit the network.** Every fetch is behind a module-level function (`icis.download`, `ciwqs.download`, `ciwqs.resource_url`) that tests patch; the sample data under `camp/apps/emissions/tests/data/` is trimmed from the real downloads by the commands each task gives.
- **Test command** (`$TEST <paths>` below):
  `docker compose -f /home/derek/dev/ccac/sjvair.com/docker-compose.yml --project-directory /home/derek/dev/ccac/sjvair.com run --rm -T -e DATABASE_URL=postgis://sjvair:changeme@db:5432/sjvair_compliance -v <worktree>:/app test pytest <paths> -q -p no:cacheprovider --create-db`
  (`fatal: not a git repository` in its output is harmless.)
- **Asset rebuild** (Task 9 only): the same prefix without `-e`, service `web`, `invoke vendor bundle styles`. Run `node --check` on any JS touched.
- **Smoke:** `/home/derek/.claude/jobs/d44a9b36/tmp/venv/bin/python scripts/emissions_map_smoke.py --base http://localhost:8003`. The dev server's container is `docker ps --filter publish=8003`; never stop it.
- **Migrations.** Run `makemigrations emissions --name <name>` inside the test container command (service `web`, `python manage.py makemigrations …`) and commit the generated file. Sibling phase branches also add `0007_*`; whichever merges second adds a merge migration (`makemigrations --merge`), which is fine.
- **Models.** `sqid = SqidsField(alphabet=shuffle_alphabet('emissions.<Model>'))` beside the integer PK. Verbose names use `_()` as the first positional arg; don't align `=`. No `SmallUUIDField`.
- **Commits:** explicit paths only (`git -C <worktree> add <new files>`, then `git -C <worktree> commit -m "…" -- <every path>`). Never `git add -A`, never `git stash`, never push, no AI attribution or Co-Authored-By trailers. Message style: `feat(emissions): …`, `feat(dairies): …`, `test(emissions): …`.
- **Deploy notes go in the PR description**, not CLAUDE.md. Each part's PR description ends with its Deploy block from the spec (`migrate`; the one-off import; the task registers on the next `huey_primary` restart) and, for Part A, the reporting-lag sentence from the research.
- **Copy, verbatim from the spec.** Card title `Compliance (federal Clean Air Act reporting)`. HPV badge text `No violation identified` / `High-priority violation: addressed` / `High-priority violation: unaddressed`. Rollup line `Last 5 years: N inspections · N notices of violation · N formal actions, $X in penalties`. Link `Full record at EPA ECHO →`. Stamp `Reported to EPA through {date}.` Region line `N of the M facilities here are tracked in EPA's air compliance system; K have an unaddressed high-priority violation →`. Dairy column heading `Water Board actions`; filter label `With a Water Board action in the last 5 years`; popup link `Record at CIWQS →`; tile `N with a Water Board action since {year}`. The two caveat panels are quoted in Tasks 5 and 10.
- **Refinements made while planning** (the spec is otherwise followed as written):
  1. `ComplianceEvent.external_id` is ICIS's `ACTIVITY_ID` for every kind (every event file has it; `ENF_IDENTIFIER` only the two action files), so the unique key is uniform.
  2. Title V comes from `ICIS-AIR_PROGRAMS.csv` rows whose `PROGRAM_DESC` contains `TITLE V` (case-insensitive) or `PROGRAM_CODE` is `CAATVP`, not from a facility column (there is none).
  3. `AirComplianceFacility.pollutant_class` stores `AIR_POLLUTANT_CLASS_DESC` as given (`Major`, `Synthetic Minor`, `Minor`, `Unclassified`, blank), char 32; the template shows it as is.
  4. The region line links the filtered list with `county=<slug>` on a county page, `region=<sqid>` on a city / urban area / CDP / ZIP page (the list's region filter accepts only those), and no area parameter on tract, school-district and near-me pages (the list then shows the whole scope; the line still states the area's own counts).
  5. The CIWQS "last 5 years" is `data_through` minus five years (see Architecture), one definition (`ciwqs.window()`) for the column, the filter and the tile.
  6. `import_ciwqs_dairies` takes the two sources as CSVs (`--cafo-path`, `--enforcement-path`) and by default resolves each resource's dated CSV URL through CKAN `resource_show`; the spec's `datastore_search` route isn't used (the CSV is one request and the same rows).

## Review Focus

- **A facility with no ICIS row must show nothing** (no card, no "no violations" line). Pinned by `test_no_card_without_a_match` (Task 5). The spec is explicit: absence must not read as compliance.
- **The five-year rollup is anchored on `reported_through`, not today.** Pinned by `test_rollups_count_back_from_reported_through` (Task 4): a fixture with events in 2019–2024 and `reported_through` 2024-06-30 counts 2019-07-01 onward, whatever the current date.
- **An EKAPCD id is stored but never matched or shown.** `CAKCA…` ids don't encode a CEIDARS facid; a naive `int(tail)` would match the wrong company. Pinned by `test_ekapcd_and_epa_ids_stay_unmatched` (Task 2) and the card's absence on TEST CEMENT (Task 5).
- **Re-running an import replaces, never duplicates.** Both imports delete each matched row's events/actions and re-insert inside one transaction. Pinned by `test_rerun_replaces_events` (Task 2) and `test_rerun_replaces_actions` (Task 8).
- **The dairy column, filter and tile agree.** All three read `ciwqs.window()`; a boundary-date action (exactly on the cutoff) counts in all three or none. Pinned by `test_window_boundary` (Task 8).

---

# Part A: Phase 4, EPA ICIS-Air compliance

### Task 1: Models and migration (`SourceImport`, `AirComplianceFacility`, `ComplianceEvent`)

**Files:**
- Modify: `camp/apps/emissions/models.py` (append after `Digester`)
- Create: `camp/apps/emissions/migrations/0007_compliance.py` (generated)
- Modify: `camp/apps/emissions/admin.py`
- Test: `camp/apps/emissions/tests/test_models.py`

**Interfaces:**
- Produces (all in `camp.apps.emissions.models`):
  - `SourceImport(sqid, source, imported_at, data_through, version, notes)`; `SourceImport.latest(source) -> SourceImport | None`.
  - `AirComplianceFacility(sqid, facility FK null SET_NULL related_name='icis_facilities', pgm_sys_id unique, registry_id, name, address JSON, pollutant_class, operating_status, title_v, current_hpv, local_region, match_method, reported_through)` with `hpv_status` property → `'none' | 'addressed' | 'unaddressed'`, `dfr_url` property, `class MatchMethod(TextChoices)`: `PARSED='parsed'`, `MANUAL='manual'`, and `''`.
  - `ComplianceEvent(sqid, icis_facility FK CASCADE related_name='events', kind, date, agency, action_type, description, penalty, program, pollutant, resolved, external_id)`; `class Kind(TextChoices)`: `INSPECTION='inspection'`, `NOV='nov'`, `FORMAL='formal'`, `HPV='hpv'`; `unique (icis_facility, kind, external_id)`; `index (icis_facility, kind, date)`.

- [ ] **Step 0: Check whether Phase 1 already added `SourceImport`**

Run: `grep -n "class SourceImport" <worktree>/camp/apps/emissions/models.py`. If it prints a line, skip the `SourceImport` class below (use the existing one; its interface is the same) and name the migration accordingly. If it prints nothing, add it.

- [ ] **Step 1: Write the failing tests**

Append to `camp/apps/emissions/tests/test_models.py`:

```python
from datetime import date

from camp.apps.emissions.models import AirComplianceFacility, ComplianceEvent, SourceImport


class SourceImportTests(TestCase):
    def test_latest_is_the_newest_row_or_none(self):
        assert SourceImport.latest('icis-air') is None
        SourceImport.objects.create(source='icis-air', data_through=date(2024, 1, 1))
        newest = SourceImport.objects.create(source='icis-air', data_through=date(2025, 6, 30))
        SourceImport.objects.create(source='ciwqs', data_through=date(2026, 1, 1))
        assert SourceImport.latest('icis-air') == newest


class AirComplianceFacilityTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def test_hpv_status_and_dfr_url(self):
        row = AirComplianceFacility.objects.create(pgm_sys_id='CASJV00006019C0001', registry_id='110000000001', name='X')
        assert row.hpv_status == 'none'
        row.current_hpv = 'Unaddressed-Local'
        assert row.hpv_status == 'unaddressed'
        row.current_hpv = 'Addressed-EPA'
        assert row.hpv_status == 'addressed'
        assert row.dfr_url == 'https://echo.epa.gov/detailed-facility-report?fid=110000000001'
        assert row.sqid

    def test_events_are_unique_per_kind_and_id(self):
        row = AirComplianceFacility.objects.create(pgm_sys_id='CASJV00006019C0001', name='X')
        ComplianceEvent.objects.create(icis_facility=row, kind='nov', date=date(2024, 1, 1), agency='L', external_id='1')
        ComplianceEvent.objects.create(icis_facility=row, kind='formal', date=date(2024, 1, 1), agency='L', external_id='1')
        with pytest.raises(IntegrityError):
            ComplianceEvent.objects.create(icis_facility=row, kind='nov', date=date(2024, 2, 2), agency='L', external_id='1')
```

Add `import pytest`, `from django.db import IntegrityError` and `from django.test import TestCase` to the file's imports if missing (check the existing header first).

- [ ] **Step 2: Run them to verify they fail**

Run: `$TEST camp/apps/emissions/tests/test_models.py`
Expected: FAIL with `ImportError: cannot import name 'AirComplianceFacility'`.

- [ ] **Step 3: Add the models**

Append to `camp/apps/emissions/models.py`:

```python
class SourceImport(models.Model):
    """
    One finished run of an external-source import (ICIS-Air, CIWQS, …): when
    it ran and how far the data reaches, for the "reported through" stamps.
    """

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.SourceImport'))
    source = models.CharField(_('Source'), max_length=32, db_index=True)
    imported_at = models.DateTimeField(_('Imported at'), auto_now_add=True)
    # The newest date in the data (an event date, an inventory year's end); null when the source has none.
    data_through = models.DateField(_('Data through'), null=True, blank=True)
    version = models.CharField(_('Version'), max_length=64, blank=True)
    notes = models.JSONField(_('Notes'), default=dict, blank=True)

    class Meta:
        ordering = ['-imported_at']

    def __str__(self):
        return f'{self.source} @ {self.imported_at:%Y-%m-%d}'

    @classmethod
    def latest(cls, source):
        return cls.objects.filter(source=source).order_by('-imported_at', '-pk').first()


class AirComplianceFacility(models.Model):
    """
    A Clean Air Act source in EPA's ICIS-Air, as its bulk files describe it.
    `facility` is the CEIDARS facility it was matched to (see icis.parse_pgm_sys_id);
    unmatched rows are kept but never shown.
    """

    class MatchMethod(models.TextChoices):
        PARSED = 'parsed', _('Parsed from the ICIS id')
        MANUAL = 'manual', _('Hand-kept crosswalk')

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.AirComplianceFacility'))
    facility = models.ForeignKey(
        Facility, verbose_name=_('Facility'), null=True, blank=True,
        on_delete=models.SET_NULL, related_name='icis_facilities',
    )
    pgm_sys_id = models.CharField(_('ICIS-Air id'), max_length=20, unique=True)
    registry_id = models.CharField(_('FRS registry id'), max_length=12, blank=True)
    name = models.CharField(_('Name'), max_length=128)
    # street, city, county, zip as ICIS gives them.
    address = models.JSONField(_('Address'), default=dict, blank=True)
    pollutant_class = models.CharField(_('Pollutant class'), max_length=32, blank=True)
    operating_status = models.CharField(_('Operating status'), max_length=40, blank=True)
    title_v = models.BooleanField(_('Title V'), default=False)
    current_hpv = models.CharField(_('Current HPV status'), max_length=40, blank=True)
    local_region = models.CharField(_('Local control region'), max_length=8, blank=True)
    match_method = models.CharField(_('Match method'), max_length=8, choices=MatchMethod.choices, blank=True)
    # The newest event date for this facility; the card's five-year window ends here.
    reported_through = models.DateField(_('Reported through'), null=True, blank=True)

    class Meta:
        verbose_name_plural = 'air compliance facilities'

    def __str__(self):
        return f'{self.name} ({self.pgm_sys_id})'

    @property
    def hpv_status(self):
        """'unaddressed', 'addressed' or 'none', from ICIS's CURRENT_HPV text ("Unaddressed-Local", "No Violation Identified")."""
        status = self.current_hpv.lower()
        if status.startswith('unaddressed'):
            return 'unaddressed'
        if status.startswith('addressed'):
            return 'addressed'
        return 'none'

    @property
    def dfr_url(self):
        return f'https://echo.epa.gov/detailed-facility-report?fid={self.registry_id}'


class ComplianceEvent(models.Model):
    """One ICIS-Air event: an inspection, a notice of violation, a formal action or an HPV determination."""

    class Kind(models.TextChoices):
        INSPECTION = 'inspection', _('Inspection')
        NOV = 'nov', _('Notice of violation')
        FORMAL = 'formal', _('Formal action')
        HPV = 'hpv', _('High-priority violation')

    class Agency(models.TextChoices):
        LOCAL = 'L', _('Air district')
        STATE = 'S', _('State')
        EPA = 'E', _('EPA')

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.ComplianceEvent'))
    icis_facility = models.ForeignKey(AirComplianceFacility, verbose_name=_('ICIS facility'), on_delete=models.CASCADE, related_name='events')
    kind = models.CharField(_('Kind'), max_length=12, choices=Kind.choices)
    date = models.DateField(_('Date'))
    agency = models.CharField(_('Agency'), max_length=1, choices=Agency.choices, blank=True)
    action_type = models.CharField(_('Action type'), max_length=80, blank=True)
    description = models.TextField(_('Description'), blank=True)
    penalty = models.DecimalField(_('Penalty'), max_digits=12, decimal_places=2, null=True, blank=True)
    program = models.CharField(_('Program'), max_length=40, blank=True)
    pollutant = models.CharField(_('Pollutant'), max_length=40, blank=True)
    # HPV only: the day the violation was resolved.
    resolved = models.DateField(_('Resolved'), null=True, blank=True)
    external_id = models.CharField(_('ICIS activity id'), max_length=40)

    class Meta:
        unique_together = [('icis_facility', 'kind', 'external_id')]
        indexes = [models.Index(fields=['icis_facility', 'kind', 'date'])]

    def __str__(self):
        return f'{self.get_kind_display()} {self.date} ({self.icis_facility.pgm_sys_id})'
```

- [ ] **Step 4: Generate the migration**

Run: `docker compose -f /home/derek/dev/ccac/sjvair.com/docker-compose.yml --project-directory /home/derek/dev/ccac/sjvair.com run --rm -T -v <worktree>:/app web python manage.py makemigrations emissions --name compliance`
Expected: `camp/apps/emissions/migrations/0007_compliance.py` created (its number may differ; use whatever `makemigrations` produced).

- [ ] **Step 5: Admin (list display only)**

In `camp/apps/emissions/admin.py`, extend the import to `from .models import AirComplianceFacility, ComplianceEvent, CountyInventory, EmissionsRecord, Facility, SourceImport` and append:

```python
@admin.register(SourceImport)
class SourceImportAdmin(ReadOnlyAdminMixin, base_admin.ModelAdmin):
    list_display = ['source', 'imported_at', 'data_through', 'version']
    list_filter = ['source']


class ComplianceEventInline(admin.TabularInline):
    model = ComplianceEvent
    extra = 0
    can_delete = False
    fields = ['kind', 'date', 'agency', 'action_type', 'description', 'penalty', 'resolved']
    readonly_fields = fields
    ordering = ['-date']

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(AirComplianceFacility)
class AirComplianceFacilityAdmin(ReadOnlyAdminMixin, base_admin.ModelAdmin):
    list_display = ['pgm_sys_id', 'name', 'facility', 'pollutant_class', 'operating_status', 'title_v', 'current_hpv', 'match_method', 'reported_through']
    list_filter = ['match_method', 'pollutant_class', 'title_v', 'current_hpv']
    search_fields = ['pgm_sys_id', 'name', 'facility__name', 'registry_id']
    raw_id_fields = ['facility']
    inlines = [ComplianceEventInline]
```

(If `SourceImport` already had an admin from Phase 1, keep theirs and skip `SourceImportAdmin`.)

- [ ] **Step 6: Run the tests**

Run: `$TEST camp/apps/emissions/tests/test_models.py`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git -C <worktree> add camp/apps/emissions/migrations/0007_compliance.py
git -C <worktree> commit -m "feat(emissions): SourceImport, AirComplianceFacility and ComplianceEvent models" -- camp/apps/emissions/models.py camp/apps/emissions/migrations/0007_compliance.py camp/apps/emissions/admin.py camp/apps/emissions/tests/test_models.py
```

---

### Task 2: `icis.py`: id parsing, zip streaming, apply

**Files:**
- Create: `camp/apps/emissions/icis.py`
- Create: `camp/apps/emissions/icis_crosswalk.py`
- Create: `camp/apps/emissions/tests/data/icis-air/` (six trimmed CSVs, see Step 3)
- Test: `camp/apps/emissions/tests/test_icis.py` (new)

**Interfaces:**
- `icis.URL = 'https://echo.epa.gov/files/echodownloads/ICIS-AIR_downloads.zip'`
- `icis.FIPS_TO_CARB = {'019': 10, '029': 15, '031': 16, '039': 20, '047': 24, '077': 39, '099': 50, '107': 54}`
- `icis.parse_pgm_sys_id(pgm_sys_id) -> (carb_county_code, 'SJU', facid) | None` (SJVAPCD ids only).
- `icis.download(url=URL) -> str` (a temp file path; the only network call; tests patch it).
- `icis.read(zip_path) -> dict` with keys `facilities` (list of dict rows, Valley only), `inspections`, `novs`, `formals`, `hpvs` (lists of dict rows for those facilities), `title_v` (set of `PGM_SYS_ID`).
- `icis.apply(data) -> Report` writes everything in one transaction, returns a `Report` dataclass with `lines()`.
- `icis.FILES` maps each logical name to the CSV file name inside the zip.
- `icis_crosswalk.CROSSWALK = {}` typed `{pgm_sys_id: (county_code, district_external_id, facid)}`.

- [ ] **Step 1: Write the failing tests**

Create `camp/apps/emissions/tests/test_icis.py`:

```python
import csv
import io
import os
import tempfile
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.test import TestCase

from camp.apps.emissions import icis
from camp.apps.emissions.models import AirComplianceFacility, ComplianceEvent, Facility, SourceImport

DATA = Path(__file__).parent / 'data' / 'icis-air'

# TEST PLANT is Fresno (FIPS 019, CARB 10), SJU, facid 1; TEST GAS STATION is
# Kern (029, CARB 15), SJU, facid 2; TEST CEMENT is Kern, EKAPCD (KER), facid 2.
PLANT = 'CASJV00006019C0001'
STATION = 'CASJV00006029S0002'
EKAPCD = 'CAKCA00000000000123'
NOWHERE = 'CASJV00006037S0001'  # Los Angeles County: not covered

FACILITIES = [
    {'PGM_SYS_ID': PLANT, 'REGISTRY_ID': '110000000001', 'FACILITY_NAME': 'TEST PLANT INC', 'STREET_ADDRESS': '123 MAIN ST',
     'CITY': 'FRESNO', 'COUNTY_NAME': 'FRESNO', 'STATE': 'CA', 'ZIP_CODE': '93728', 'AIR_POLLUTANT_CLASS_DESC': 'Major',
     'AIR_OPERATING_STATUS_DESC': 'Operating', 'CURRENT_HPV': 'Unaddressed-Local', 'AIR_LOCAL_CONTROL_REGION_CODE': 'SJV'},
    {'PGM_SYS_ID': STATION, 'REGISTRY_ID': '110000000002', 'FACILITY_NAME': 'OLD OWNER GAS', 'STREET_ADDRESS': '456 OAK AVE',
     'CITY': 'BAKERSFIELD', 'COUNTY_NAME': 'KERN', 'STATE': 'CA', 'ZIP_CODE': '93301', 'AIR_POLLUTANT_CLASS_DESC': 'Synthetic Minor',
     'AIR_OPERATING_STATUS_DESC': 'Permanently Closed', 'CURRENT_HPV': 'No Violation Identified', 'AIR_LOCAL_CONTROL_REGION_CODE': 'SJV'},
    {'PGM_SYS_ID': EKAPCD, 'REGISTRY_ID': '110000000003', 'FACILITY_NAME': 'DESERT CEMENT', 'STREET_ADDRESS': '1 QUARRY RD',
     'CITY': 'MOJAVE', 'COUNTY_NAME': 'KERN', 'STATE': 'CA', 'ZIP_CODE': '93501', 'AIR_POLLUTANT_CLASS_DESC': 'Major',
     'AIR_OPERATING_STATUS_DESC': 'Operating', 'CURRENT_HPV': 'No Violation Identified', 'AIR_LOCAL_CONTROL_REGION_CODE': 'KCA'},
    {'PGM_SYS_ID': NOWHERE, 'REGISTRY_ID': '110000000004', 'FACILITY_NAME': 'LA PLANT', 'STREET_ADDRESS': '1 LA ST',
     'CITY': 'LOS ANGELES', 'COUNTY_NAME': 'LOS ANGELES', 'STATE': 'CA', 'ZIP_CODE': '90001', 'AIR_POLLUTANT_CLASS_DESC': 'Major',
     'AIR_OPERATING_STATUS_DESC': 'Operating', 'CURRENT_HPV': 'No Violation Identified', 'AIR_LOCAL_CONTROL_REGION_CODE': 'SC'},
]
INSPECTIONS = [
    {'PGM_SYS_ID': PLANT, 'ACTIVITY_ID': '9001', 'STATE_EPA_FLAG': 'L', 'ACTIVITY_TYPE_DESC': 'Full Compliance Evaluation',
     'COMP_MONITOR_TYPE_DESC': 'FCE On-Site', 'ACTUAL_END_DATE': '03/15/2024', 'PROGRAM_CODES': 'CAATVP', 'ACTIVITY_PURPOSE_DESC': ''},
    {'PGM_SYS_ID': PLANT, 'ACTIVITY_ID': '9002', 'STATE_EPA_FLAG': 'L', 'ACTIVITY_TYPE_DESC': 'Partial Compliance Evaluation',
     'COMP_MONITOR_TYPE_DESC': 'PCE Off-Site', 'ACTUAL_END_DATE': '06/30/2018', 'PROGRAM_CODES': '', 'ACTIVITY_PURPOSE_DESC': ''},
    {'PGM_SYS_ID': NOWHERE, 'ACTIVITY_ID': '9003', 'STATE_EPA_FLAG': 'L', 'ACTIVITY_TYPE_DESC': 'Full Compliance Evaluation',
     'COMP_MONITOR_TYPE_DESC': 'FCE On-Site', 'ACTUAL_END_DATE': '01/01/2024', 'PROGRAM_CODES': '', 'ACTIVITY_PURPOSE_DESC': ''},
]
NOVS = [
    {'PGM_SYS_ID': PLANT, 'ACTIVITY_ID': '8001', 'ENF_IDENTIFIER': 'NOV-1', 'ACTIVITY_TYPE_DESC': 'Informal Enforcement Action',
     'STATE_EPA_FLAG': 'L', 'ENF_TYPE_DESC': 'Notice of Violation', 'ACHIEVED_DATE': '05/02/2023', 'OFFICIAL_FLG': 'Y'},
]
FORMALS = [
    {'PGM_SYS_ID': PLANT, 'ACTIVITY_ID': '7001', 'ENF_IDENTIFIER': 'CASE-1', 'ACTIVITY_TYPE_DESC': 'Formal Enforcement Action',
     'STATE_EPA_FLAG': 'L', 'ENF_TYPE_DESC': 'Administrative - Formal (Settlement)', 'SETTLEMENT_ENTERED_DATE': '06/30/2024', 'PENALTY_AMOUNT': '12500.50'},
    {'PGM_SYS_ID': STATION, 'ACTIVITY_ID': '7002', 'ENF_IDENTIFIER': 'CASE-2', 'ACTIVITY_TYPE_DESC': 'Formal Enforcement Action',
     'STATE_EPA_FLAG': 'S', 'ENF_TYPE_DESC': 'Administrative - Formal (Settlement)', 'SETTLEMENT_ENTERED_DATE': '02/01/2015', 'PENALTY_AMOUNT': ''},
]
HPVS = [
    {'PGM_SYS_ID': PLANT, 'ACTIVITY_ID': '6001', 'AGENCY_TYPE_DESC': 'Local', 'ENF_RESPONSE_POLICY_CODE': 'HPV',
     'PROGRAM_DESCS': 'Title V Permits', 'POLLUTANT_DESCS': 'Nitrogen oxides', 'EARLIEST_FRV_DETERM_DATE': '',
     'HPV_DAYZERO_DATE': '04/01/2024', 'HPV_RESOLVED_DATE': ''},
]
PROGRAMS = [
    {'PGM_SYS_ID': PLANT, 'PROGRAM_CODE': 'CAATVP', 'PROGRAM_DESC': 'Title V Permits', 'AIR_OPERATING_STATUS_DESC': 'Operating'},
    {'PGM_SYS_ID': STATION, 'PROGRAM_CODE': 'CAASIP', 'PROGRAM_DESC': 'State Implementation Plan', 'AIR_OPERATING_STATUS_DESC': 'Operating'},
]


def build_zip(directory, facilities=FACILITIES, inspections=INSPECTIONS, novs=NOVS, formals=FORMALS, hpvs=HPVS, programs=PROGRAMS):
    """An ICIS-AIR_downloads.zip stand-in with the six files we read, from row dicts (each file's header is its rows' keys)."""
    path = os.path.join(directory, 'ICIS-AIR_downloads.zip')
    tables = {
        icis.FILES['facilities']: facilities, icis.FILES['inspections']: inspections, icis.FILES['novs']: novs,
        icis.FILES['formals']: formals, icis.FILES['hpvs']: hpvs, icis.FILES['programs']: programs,
    }
    with zipfile.ZipFile(path, 'w') as archive:
        for name, rows in tables.items():
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()) if rows else ['PGM_SYS_ID'])
            writer.writeheader()
            writer.writerows(rows)
            archive.writestr(name, buffer.getvalue())
    return path


def real_sample_zip(directory):
    """The checked-in trimmed CSVs (real ICIS rows) zipped up."""
    path = os.path.join(directory, 'real.zip')
    with zipfile.ZipFile(path, 'w') as archive:
        for name in icis.FILES.values():
            archive.write(DATA / name, name)
    return path


class ParseTests(TestCase):
    def test_the_three_verified_ids(self):
        assert icis.parse_pgm_sys_id('CASJV00006029S3636') == (15, 'SJU', 3636)
        assert icis.parse_pgm_sys_id('CASJV00006029S0075') == (15, 'SJU', 75)
        assert icis.parse_pgm_sys_id('CASJV00006077N7365') == (39, 'SJU', 7365)
        assert icis.parse_pgm_sys_id('CASJV00006019C0001') == (10, 'SJU', 1)

    def test_other_ids_do_not_parse(self):
        for bad in ('CAKCA00000000000123', '0900000012345', 'CA0000123456', 'CASJV00006037S0001', 'CASJV00006029X0001', 'CASJV00006029S00AB', ''):
            assert icis.parse_pgm_sys_id(bad) is None, bad


class ReadTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_keeps_valley_rows_and_their_events_only(self):
        data = icis.read(build_zip(self.tmp.name))
        assert [row['PGM_SYS_ID'] for row in data['facilities']] == [PLANT, STATION, EKAPCD]
        assert [row['ACTIVITY_ID'] for row in data['inspections']] == ['9001', '9002']
        assert len(data['novs']) == 1 and len(data['formals']) == 2 and len(data['hpvs']) == 1
        assert data['title_v'] == {PLANT}

    def test_the_real_layout(self):
        # The checked-in files are trimmed from the real download: the headers are EPA's.
        data = icis.read(real_sample_zip(self.tmp.name))
        ids = {row['PGM_SYS_ID'] for row in data['facilities']}
        assert {'CASJV00006029S3636', 'CASJV00006029S0075', 'CASJV00006077N7365'} <= ids
        assert any(row['PGM_SYS_ID'].startswith('CAKCA') for row in data['facilities'])
        assert data['inspections'] and data['formals']
        for row in data['facilities']:
            assert row['COUNTY_NAME'].upper() in {'FRESNO', 'KERN', 'KINGS', 'MADERA', 'MERCED', 'SAN JOAQUIN', 'STANISLAUS', 'TULARE'}


class ApplyTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.plant = Facility.objects.get(name='TEST PLANT')
        self.station = Facility.objects.get(name='TEST GAS STATION')

    def run_apply(self, **tables):
        return icis.apply(icis.read(build_zip(self.tmp.name, **tables)))

    def test_matches_parsed_ids_and_replaces_events(self):
        report = self.run_apply()
        plant = AirComplianceFacility.objects.get(pgm_sys_id=PLANT)
        assert plant.facility == self.plant and plant.match_method == 'parsed'
        assert plant.title_v is True and plant.pollutant_class == 'Major' and plant.hpv_status == 'unaddressed'
        assert plant.address == {'street': '123 MAIN ST', 'city': 'FRESNO', 'county': 'FRESNO', 'zip': '93728'}
        assert plant.reported_through == date(2024, 6, 30)
        kinds = dict(plant.events.values_list('kind').annotate(n=models.Count('pk')).values_list('kind', 'n'))
        assert kinds == {'inspection': 2, 'nov': 1, 'formal': 1, 'hpv': 1}
        formal = plant.events.get(kind='formal')
        assert formal.penalty == Decimal('12500.50') and formal.agency == 'L' and formal.external_id == '7001'
        assert formal.action_type == 'Administrative - Formal (Settlement)'
        hpv = plant.events.get(kind='hpv')
        assert (hpv.date, hpv.resolved, hpv.pollutant, hpv.program) == (date(2024, 4, 1), None, 'Nitrogen oxides', 'Title V Permits')
        assert hpv.description == 'High-priority violation'
        station = AirComplianceFacility.objects.get(pgm_sys_id=STATION)
        assert station.facility == self.station and station.title_v is False
        assert station.events.get().penalty is None and station.reported_through == date(2015, 2, 1)
        assert report.matched == 2 and report.unmatched == 1 and report.events == 6

    def test_ekapcd_and_epa_ids_stay_unmatched(self):
        self.run_apply()
        desert = AirComplianceFacility.objects.get(pgm_sys_id=EKAPCD)
        assert desert.facility is None and desert.match_method == ''
        assert not AirComplianceFacility.objects.filter(pgm_sys_id=NOWHERE).exists()

    def test_crosswalk_matches_manually(self):
        from unittest.mock import patch
        cement = Facility.objects.get(name='TEST CEMENT')
        with patch.dict(icis.CROSSWALK, {EKAPCD: (15, 'KER', 2)}):
            self.run_apply()
        desert = AirComplianceFacility.objects.get(pgm_sys_id=EKAPCD)
        assert desert.facility == cement and desert.match_method == 'manual'

    def test_rerun_replaces_events(self):
        self.run_apply()
        self.run_apply(novs=[], formals=[dict(FORMALS[0], PENALTY_AMOUNT='99')])
        plant = AirComplianceFacility.objects.get(pgm_sys_id=PLANT)
        assert AirComplianceFacility.objects.count() == 3
        assert not plant.events.filter(kind='nov').exists()
        assert plant.events.get(kind='formal').penalty == Decimal('99')
        assert plant.reported_through == date(2024, 6, 30)

    def test_source_import_stamp(self):
        self.run_apply()
        stamp = SourceImport.latest('icis-air')
        assert stamp.data_through == date(2024, 6, 30)
        assert stamp.notes['facilities'] == 3 and stamp.notes['matched'] == 2

    def test_bad_dates_are_skipped_not_fatal(self):
        self.run_apply(novs=[dict(NOVS[0], ACHIEVED_DATE='')])
        assert not AirComplianceFacility.objects.get(pgm_sys_id=PLANT).events.filter(kind='nov').exists()
```

Add `from django.db import models` to the imports.

- [ ] **Step 2: Run them to verify they fail**

Run: `$TEST camp/apps/emissions/tests/test_icis.py`
Expected: FAIL with `ImportError: cannot import name 'icis'`.

- [ ] **Step 3: Produce the checked-in sample files**

From a machine with the real download (70 MB; do this once, by hand, outside the container):

```bash
mkdir -p /tmp/icis && cd /tmp/icis
curl -sSLo ICIS-AIR_downloads.zip https://echo.epa.gov/files/echodownloads/ICIS-AIR_downloads.zip
IDS='CASJV00006029S3636|CASJV00006029S0075|CASJV00006077N7365'
# One EKAPCD row too: the first CAKCA… id in Kern.
EK=$(unzip -p ICIS-AIR_downloads.zip ICIS-AIR_FACILITIES.csv | grep -m1 -E '^"?CAKCA' | cut -d, -f1 | tr -d '"')
IDS="$IDS|$EK"
OUT=<worktree>/camp/apps/emissions/tests/data/icis-air; mkdir -p "$OUT"
for f in ICIS-AIR_FACILITIES ICIS-AIR_FCES_PCES ICIS-AIR_INFORMAL_ACTIONS ICIS-AIR_FORMAL_ACTIONS ICIS-AIR_VIOLATION_HISTORY ICIS-AIR_PROGRAMS; do
  unzip -p ICIS-AIR_downloads.zip $f.csv | head -1 > "$OUT/$f.csv"
  unzip -p ICIS-AIR_downloads.zip $f.csv | grep -E "^\"?($IDS)" | head -12 >> "$OUT/$f.csv"
done
wc -l "$OUT"/*.csv
```

Each file must have its header plus 1–12 real rows; every file under 20 rows. If the real header names differ from the ones this plan uses (`icis.COLUMNS` below), fix the constants to the real names and say so in the commit message: the header is the contract.

- [ ] **Step 4: Write `icis_crosswalk.py`**

```python
"""
ICIS-Air ids that don't encode a CEIDARS facility id (Eastern Kern APCD's
`CAKCA…`, EPA Region 9's `0900…` / `CA0000…`), matched by hand:
pgm_sys_id -> (CARB county code, air district external id, facid). Empty
until someone checks the rows against the permit portal; icis.apply stores
unmatched rows but never shows them.
"""

CROSSWALK = {}
```

- [ ] **Step 5: Write `icis.py`**

```python
"""
EPA's ICIS-Air bulk download (Clean Air Act compliance): the facilities the
air districts and EPA report on, their inspections, notices of violation,
formal actions and high-priority violations.

Only federally reportable sources are here (about 660 of the Valley's
11,000 permitted facilities). SJVAPCD's own id is embedded in the ICIS id:
`CA` + `SJV` + `0000` + 5-digit county FIPS + a region letter (S/C/N) + the
district facid, which is the CEIDARS facid. Eastern Kern and EPA-lead ids
don't encode ours (icis_crosswalk). The district's reporting runs a year or
more behind: every surface stamps "reported through" the newest event date.
"""
import csv
import io
import re
import tempfile
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

import requests

from django.conf import settings
from django.db import transaction

from camp.apps.emissions.icis_crosswalk import CROSSWALK
from camp.apps.emissions.models import AirComplianceFacility, ComplianceEvent, Facility, SourceImport
from camp.apps.regions.models import Region

URL = 'https://echo.epa.gov/files/echodownloads/ICIS-AIR_downloads.zip'
SOURCE = 'icis-air'
FILES = {
    'facilities': 'ICIS-AIR_FACILITIES.csv',
    'inspections': 'ICIS-AIR_FCES_PCES.csv',
    'novs': 'ICIS-AIR_INFORMAL_ACTIONS.csv',
    'formals': 'ICIS-AIR_FORMAL_ACTIONS.csv',
    'hpvs': 'ICIS-AIR_VIOLATION_HISTORY.csv',
    'programs': 'ICIS-AIR_PROGRAMS.csv',
}
# The columns each file must have (the header is the contract; a renamed column fails in read()).
COLUMNS = {
    'facilities': ('PGM_SYS_ID', 'REGISTRY_ID', 'FACILITY_NAME', 'STREET_ADDRESS', 'CITY', 'COUNTY_NAME', 'STATE', 'ZIP_CODE',
                   'AIR_POLLUTANT_CLASS_DESC', 'AIR_OPERATING_STATUS_DESC', 'CURRENT_HPV', 'AIR_LOCAL_CONTROL_REGION_CODE'),
    'inspections': ('PGM_SYS_ID', 'ACTIVITY_ID', 'STATE_EPA_FLAG', 'ACTIVITY_TYPE_DESC', 'COMP_MONITOR_TYPE_DESC', 'ACTUAL_END_DATE', 'PROGRAM_CODES'),
    'novs': ('PGM_SYS_ID', 'ACTIVITY_ID', 'STATE_EPA_FLAG', 'ENF_TYPE_DESC', 'ACHIEVED_DATE'),
    'formals': ('PGM_SYS_ID', 'ACTIVITY_ID', 'STATE_EPA_FLAG', 'ENF_TYPE_DESC', 'SETTLEMENT_ENTERED_DATE', 'PENALTY_AMOUNT'),
    'hpvs': ('PGM_SYS_ID', 'ACTIVITY_ID', 'AGENCY_TYPE_DESC', 'ENF_RESPONSE_POLICY_CODE', 'PROGRAM_DESCS', 'POLLUTANT_DESCS',
             'EARLIEST_FRV_DETERM_DATE', 'HPV_DAYZERO_DATE', 'HPV_RESOLVED_DATE'),
    'programs': ('PGM_SYS_ID', 'PROGRAM_CODE', 'PROGRAM_DESC'),
}
# County FIPS (the 3 digits after the state's 06) -> CARB's county number.
FIPS_TO_CARB = {'019': 10, '029': 15, '031': 16, '039': 20, '047': 24, '077': 39, '099': 50, '107': 54}
SJVAPCD = 'SJU'
_SJV_ID = re.compile(r'^CASJV0000(?:06)(\d{3})([SCN])(\d{1,6})$')
DATE_FORMATS = ('%m/%d/%Y', '%Y-%m-%d', '%m/%d/%Y %H:%M:%S', '%d-%b-%y')
TITLE_V_CODE = 'CAATVP'


class ICISFormatError(ValueError):
    """The zip isn't the ICIS-Air layout this importer knows: a file or a column is missing."""


def parse_pgm_sys_id(pgm_sys_id):
    """(CARB county code, 'SJU', facid) for an SJVAPCD id in a covered county, else None."""
    match = _SJV_ID.match((pgm_sys_id or '').strip())
    if not match:
        return None
    fips, _, facid = match.groups()
    county_code = FIPS_TO_CARB.get(fips)
    if county_code is None:
        return None
    return county_code, SJVAPCD, int(facid)


def parse_date(value):
    value = (value or '').strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def parse_decimal(value):
    value = (value or '').strip().replace(',', '').replace('$', '')
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def agency_code(value):
    """'L', 'S' or 'E' from STATE_EPA_FLAG ('L') or AGENCY_TYPE_DESC ('Local', 'State', 'EPA'); '' when unknown."""
    letter = (value or '').strip()[:1].upper()
    return letter if letter in ('L', 'S', 'E') else ''


def download(url=URL):
    """Fetch the zip to a temp file and return its path (the caller unlinks it). The one network call here."""
    response = requests.get(url, timeout=600, stream=True)
    response.raise_for_status()
    with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
        for chunk in response.iter_content(chunk_size=1 << 20):
            tmp.write(chunk)
    return tmp.name


def _rows(archive, name, columns):
    try:
        member = archive.open(name)
    except KeyError:
        raise ICISFormatError(f'The zip has no {name}.')
    reader = csv.DictReader(io.TextIOWrapper(member, encoding='utf-8-sig', errors='replace', newline=''))
    header = reader.fieldnames or []
    missing = [column for column in columns if column not in header]
    if missing:
        raise ICISFormatError(f"{name} has no {', '.join(missing)} column.")
    return reader


def read(zip_path):
    """
    {facilities, inspections, novs, formals, hpvs, title_v} from the zip,
    streamed row by row: the facilities in CA and a covered county, then each
    event file filtered to those facilities' ids. Nothing is unpacked to disk.
    """
    counties = {name.upper() for name in settings.SJVAIR_COUNTIES}
    data = {key: [] for key in ('facilities', 'inspections', 'novs', 'formals', 'hpvs')}
    with zipfile.ZipFile(zip_path) as archive:
        for row in _rows(archive, FILES['facilities'], COLUMNS['facilities']):
            if row['STATE'].strip().upper() != 'CA' or row['COUNTY_NAME'].strip().upper() not in counties:
                continue
            data['facilities'].append(row)
        ids = {row['PGM_SYS_ID'] for row in data['facilities']}
        for key in ('inspections', 'novs', 'formals', 'hpvs'):
            data[key] = [row for row in _rows(archive, FILES[key], COLUMNS[key]) if row['PGM_SYS_ID'] in ids]
        data['title_v'] = {
            row['PGM_SYS_ID'] for row in _rows(archive, FILES['programs'], COLUMNS['programs'])
            if row['PGM_SYS_ID'] in ids and (row['PROGRAM_CODE'].strip() == TITLE_V_CODE or 'TITLE V' in row['PROGRAM_DESC'].upper())
        }
    return data


@dataclass
class Report:
    facilities: int = 0
    matched: int = 0
    unmatched: int = 0
    events: int = 0
    skipped: int = 0
    data_through: object = None

    def lines(self):
        return [
            f'ICIS-Air facilities in the covered counties: {self.facilities:,} ({self.matched:,} matched to CEIDARS, {self.unmatched:,} not).',
            f'Events: {self.events:,} written, {self.skipped:,} skipped (no date). Reported through {self.data_through or "—"}.',
        ]


def _match(pgm_sys_id, districts):
    """(Facility | None, match_method) for an ICIS id: parsed from the id, else the crosswalk, else nothing."""
    parsed = parse_pgm_sys_id(pgm_sys_id)
    method = AirComplianceFacility.MatchMethod.PARSED
    if parsed is None:
        parsed = CROSSWALK.get(pgm_sys_id)
        method = AirComplianceFacility.MatchMethod.MANUAL
    if parsed is None:
        return None, ''
    county_code, district, facid = parsed
    if district not in districts:
        return None, ''
    facility = Facility.objects.filter(county_code=county_code, air_district=districts[district], facid=facid).first()
    return facility, (method if facility is not None else '')


def _event(icis_facility, kind, row):
    """A ComplianceEvent for a row of one of the four event files, or None when it has no usable date."""
    E = ComplianceEvent
    if kind == E.Kind.INSPECTION:
        when, agency = parse_date(row['ACTUAL_END_DATE']), agency_code(row['STATE_EPA_FLAG'])
        action = row['COMP_MONITOR_TYPE_DESC'].strip() or row['ACTIVITY_TYPE_DESC'].strip()
        extra = {'description': row['ACTIVITY_TYPE_DESC'].strip(), 'program': row['PROGRAM_CODES'].strip()[:40]}
    elif kind == E.Kind.NOV:
        when, agency = parse_date(row['ACHIEVED_DATE']), agency_code(row['STATE_EPA_FLAG'])
        action = row['ENF_TYPE_DESC'].strip()
        extra = {'description': action}
    elif kind == E.Kind.FORMAL:
        when, agency = parse_date(row['SETTLEMENT_ENTERED_DATE']), agency_code(row['STATE_EPA_FLAG'])
        action = row['ENF_TYPE_DESC'].strip()
        extra = {'description': action, 'penalty': parse_decimal(row['PENALTY_AMOUNT'])}
    else:
        when = parse_date(row['HPV_DAYZERO_DATE']) or parse_date(row['EARLIEST_FRV_DETERM_DATE'])
        agency = agency_code(row['AGENCY_TYPE_DESC'])
        policy = row['ENF_RESPONSE_POLICY_CODE'].strip().upper()
        action = 'High-priority violation' if 'HPV' in policy else 'Federally reportable violation'
        extra = {
            'description': action, 'program': row['PROGRAM_DESCS'].strip()[:40], 'pollutant': row['POLLUTANT_DESCS'].strip()[:40],
            'resolved': parse_date(row['HPV_RESOLVED_DATE']),
        }
    if when is None:
        return None
    return E(icis_facility=icis_facility, kind=kind, date=when, agency=agency, action_type=action[:80],
             external_id=row['ACTIVITY_ID'].strip()[:40], **extra)


def apply(data):
    """
    Upsert the facilities on pgm_sys_id (matching each to a CEIDARS facility),
    replace their events, set reported_through, and stamp SourceImport, in
    one transaction. Rows for facilities no longer in the file are left as they
    are (ICIS never drops a source; a closed one stays with its history).
    """
    report = Report(facilities=len(data['facilities']))
    districts = {region.external_id: region for region in Region.objects.filter(type=Region.Type.AIR_DISTRICT)}
    kinds = {'inspections': ComplianceEvent.Kind.INSPECTION, 'novs': ComplianceEvent.Kind.NOV,
             'formals': ComplianceEvent.Kind.FORMAL, 'hpvs': ComplianceEvent.Kind.HPV}
    with transaction.atomic():
        rows = {}
        for row in data['facilities']:
            pgm_sys_id = row['PGM_SYS_ID'].strip()
            facility, method = _match(pgm_sys_id, districts)
            values = {
                'facility': facility, 'match_method': method,
                'registry_id': row['REGISTRY_ID'].strip()[:12], 'name': row['FACILITY_NAME'].strip()[:128],
                'address': {'street': row['STREET_ADDRESS'].strip(), 'city': row['CITY'].strip(),
                            'county': row['COUNTY_NAME'].strip(), 'zip': row['ZIP_CODE'].strip()},
                'pollutant_class': row['AIR_POLLUTANT_CLASS_DESC'].strip()[:32],
                'operating_status': row['AIR_OPERATING_STATUS_DESC'].strip()[:40],
                'title_v': pgm_sys_id in data['title_v'],
                'current_hpv': row['CURRENT_HPV'].strip()[:40],
                'local_region': row['AIR_LOCAL_CONTROL_REGION_CODE'].strip()[:8],
            }
            rows[pgm_sys_id], _ = AirComplianceFacility.objects.update_or_create(pgm_sys_id=pgm_sys_id, defaults=values)
            report.matched += facility is not None
            report.unmatched += facility is None
        ComplianceEvent.objects.filter(icis_facility__in=rows.values()).delete()
        events, seen = [], set()
        for key, kind in kinds.items():
            for row in data[key]:
                icis_facility = rows.get(row['PGM_SYS_ID'].strip())
                if icis_facility is None:
                    continue
                event = _event(icis_facility, kind, row)
                if event is None:
                    report.skipped += 1
                    continue
                dedupe = (icis_facility.pk, kind, event.external_id)
                if dedupe in seen:
                    continue
                seen.add(dedupe)
                events.append(event)
        ComplianceEvent.objects.bulk_create(events, batch_size=2000)
        report.events = len(events)
        latest = defaultdict(lambda: None)
        for event in events:
            if latest[event.icis_facility_id] is None or event.date > latest[event.icis_facility_id]:
                latest[event.icis_facility_id] = event.date
        for icis_facility in rows.values():
            through = latest[icis_facility.pk]
            if icis_facility.reported_through != through:
                icis_facility.reported_through = through
                icis_facility.save(update_fields=['reported_through'])
        report.data_through = max((d for d in latest.values() if d), default=None)
        SourceImport.objects.create(
            source=SOURCE, data_through=report.data_through,
            notes={'facilities': report.facilities, 'matched': report.matched, 'events': report.events},
        )
    return report
```

Note on `_SJV_ID`: the regex requires the state prefix `06` after `0000`; the research's examples (`CASJV00006029S3636`) are `CA SJV 0000 06 029 S 3636`. The facid is 1–6 digits, zero-padded in the file.

- [ ] **Step 6: Run the tests**

Run: `$TEST camp/apps/emissions/tests/test_icis.py`
Expected: PASS. If `test_the_real_layout` fails on a column name, the real header differs: fix `COLUMNS` (and `_event`) to the real names, never the sample.

- [ ] **Step 7: Commit**

```bash
git -C <worktree> add camp/apps/emissions/icis.py camp/apps/emissions/icis_crosswalk.py camp/apps/emissions/tests/test_icis.py camp/apps/emissions/tests/data/icis-air
git -C <worktree> commit -m "feat(emissions): read and apply EPA ICIS-Air, matched on the embedded SJVAPCD facility id" -- camp/apps/emissions/icis.py camp/apps/emissions/icis_crosswalk.py camp/apps/emissions/tests/test_icis.py camp/apps/emissions/tests/data/icis-air
```

---

### Task 3: `import_icis_air` command and the monthly task

**Files:**
- Create: `camp/apps/emissions/management/commands/import_icis_air.py`
- Create: `camp/apps/emissions/tasks.py`
- Test: `camp/apps/emissions/tests/test_icis.py` (append), `camp/apps/emissions/tests/test_tasks.py` (new)

**Interfaces:**
- `python manage.py import_icis_air [--path ZIP]`: `--path` reads a local zip; without it, `icis.download()`; runs `icis.read` + `icis.apply`, clears the compliance cache (`compliance.clear_caches()` from Task 4; until Task 4 lands, call `cache.delete_pattern`-free equivalent: nothing), prints `report.lines()`.
- `tasks.import_icis_air`: `db_periodic_task(crontab(day='2', hour='11', minute='0'), priority=20)` calling `call_command('import_icis_air')` under `get_queue('primary').lock_task('import-icis-air')`.

- [ ] **Step 1: Write the failing tests**

Append to `test_icis.py`:

```python
class CommandTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def test_path_imports_and_reports(self):
        from io import StringIO
        from django.core.management import call_command
        with tempfile.TemporaryDirectory() as tmp:
            out = StringIO()
            call_command('import_icis_air', path=build_zip(tmp), stdout=out)
        assert AirComplianceFacility.objects.count() == 3
        assert '2 matched to CEIDARS' in out.getvalue()

    def test_default_downloads_then_unlinks(self):
        from unittest.mock import patch
        from django.core.management import call_command
        tmp = tempfile.mkdtemp()
        path = build_zip(tmp)
        with patch('camp.apps.emissions.icis.download', return_value=path) as download:
            call_command('import_icis_air')
        download.assert_called_once_with()
        assert not os.path.exists(path)
        assert SourceImport.latest('icis-air') is not None
```

Create `camp/apps/emissions/tests/test_tasks.py`:

```python
from unittest.mock import patch

from django.test import TestCase

from camp.apps.emissions import tasks


class ImportIcisAirTaskTests(TestCase):
    @patch('camp.apps.emissions.tasks.call_command')
    def test_runs_the_command_under_the_lock(self, call_command):
        tasks.import_icis_air.call_local()
        call_command.assert_called_once_with('import_icis_air')

    def test_schedule(self):
        # Monthly, the 2nd at 11:00 UTC: ECHO refreshes weekly, the district's feed monthly at best.
        validate = tasks.import_icis_air.task_class.validate_datetime
        from datetime import datetime
        assert validate(datetime(2026, 10, 2, 11, 0))
        assert not validate(datetime(2026, 10, 3, 11, 0))
        assert not validate(datetime(2026, 10, 2, 12, 0))
```

(If `task_class.validate_datetime` isn't how the installed huey exposes the crontab, replace the schedule test with `assert tasks.import_icis_air.task_class.__name__` existing and check the crontab by reading `tasks.py`; don't spend time on it.)

- [ ] **Step 2: Run them to verify they fail**

Run: `$TEST camp/apps/emissions/tests/test_icis.py::CommandTests camp/apps/emissions/tests/test_tasks.py`
Expected: FAIL (`CommandError: Unknown command` / `ImportError`).

- [ ] **Step 3: The command**

`camp/apps/emissions/management/commands/import_icis_air.py`:

```python
import os

from django.core.management.base import BaseCommand, CommandError

from camp.apps.emissions import compliance, icis


class Command(BaseCommand):
    help = (
        "Import EPA ICIS-Air (Clean Air Act compliance) for the covered counties: facilities, inspections, notices of "
        'violation, formal actions and high-priority violations, matched to CEIDARS facilities. Idempotent. '
        'Downloads the weekly bulk zip unless --path names a local copy.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--path', help='A locally downloaded ICIS-AIR_downloads.zip')

    def handle(self, *args, **options):
        path = options['path']
        downloaded = path is None
        if downloaded:
            self.stdout.write(f'Downloading {icis.URL}')
            path = icis.download()
        try:
            try:
                data = icis.read(path)
            except icis.ICISFormatError as err:
                raise CommandError(str(err))
            report = icis.apply(data)
        finally:
            if downloaded:
                os.unlink(path)
        compliance.clear_caches()
        for line in report.lines():
            self.stdout.write(line)
```

Until Task 4 exists, create `camp/apps/emissions/compliance.py` with just the cache generation (Task 4 fills the rest):

```python
"""The read side of EPA ICIS-Air compliance (icis.py writes it): the facility card, the list filter and the region line."""
import time

from django.core.cache import cache

from camp.apps.emissions import stats

GENERATION_KEY = 'emissions:compliance:generation'


def generation():
    value = cache.get(GENERATION_KEY)
    if value is None:
        value = int(time.time())
        cache.set(GENERATION_KEY, value, None)
    return value


def clear_caches():
    """Orphan every cached compliance aggregate: they're keyed under the generation (import_icis_air calls this)."""
    cache.set(GENERATION_KEY, generation() + 1, None)


def key(*parts):
    return ':'.join(str(part) for part in (f'emissions:compliance:v{stats.CACHE_VERSION}', generation(), *parts))
```

- [ ] **Step 4: The task**

`camp/apps/emissions/tasks.py`:

```python
from django.core.management import call_command

from django_huey import db_periodic_task, get_queue
from huey import crontab


# EPA refreshes the ICIS-Air bulk files weekly; SJVAPCD's feed into them runs
# a year or more behind, so monthly is plenty. The 2nd at 11:00 UTC.
@db_periodic_task(crontab(day='2', hour='11', minute='0'), priority=20)
def import_icis_air():
    with get_queue('primary').lock_task('import-icis-air'):
        call_command('import_icis_air')
```

django-huey autodiscovers `tasks` modules in installed apps; nothing to register.

- [ ] **Step 5: Run the tests**

Run: `$TEST camp/apps/emissions/tests/test_icis.py camp/apps/emissions/tests/test_tasks.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git -C <worktree> add camp/apps/emissions/management/commands/import_icis_air.py camp/apps/emissions/tasks.py camp/apps/emissions/compliance.py camp/apps/emissions/tests/test_tasks.py
git -C <worktree> commit -m "feat(emissions): import_icis_air command and its monthly task" -- camp/apps/emissions/management/commands/import_icis_air.py camp/apps/emissions/tasks.py camp/apps/emissions/compliance.py camp/apps/emissions/tests/test_icis.py camp/apps/emissions/tests/test_tasks.py
```

---

### Task 4: `compliance.py` read side and the list filter

**Files:**
- Modify: `camp/apps/emissions/compliance.py`
- Modify: `camp/apps/emissions/stats.py` (`facility_table`)
- Modify: `camp/apps/emissions/views.py` (`list_filters`, `FacilityList.csv_response` header)
- Test: `camp/apps/emissions/tests/test_compliance.py` (new), `camp/apps/emissions/tests/test_lists.py` (append)

**Interfaces:**
- `compliance.WINDOW_YEARS = 5`
- `compliance.facility_card(facility) -> dict | None`: `None` when the facility has no matched ICIS row; else `{'rows': [AirComplianceFacility…], 'primary': row (newest reported_through), 'reported_through': date, 'since': date, 'inspections': n, 'novs': n, 'formals': n, 'penalties': Decimal, 'events': [ComplianceEvent…] newest first, 'shown': events[:25], 'more': events[25:], 'names': [distinct ICIS names ≠ facility.name]}`. Cached under `key('card', facility.pk)` for `stats.CACHE_TIMEOUT`.
- `compliance.area_summary(scope) -> dict | None`: `{'facilities': M, 'tracked': N, 'unaddressed': K}` over `stats.records(scope)`; `None` when `tracked == 0`. Cached under `scope.key(...)`-style key plus the generation.
- `compliance.FILTERS = ('any', 'hpv')`; `compliance.filter_q(value) -> Q | None`.
- `compliance.stamp() -> SourceImport | None` (`SourceImport.latest('icis-air')`).
- `stats.facility_table(scope, *, …, compliance=None)`: `compliance in ('any', 'hpv')` narrows with `compliance.filter_q`.
- `views.list_filters(get)` gains `'compliance': value if value in compliance.FILTERS else None`.

- [ ] **Step 1: Write the failing tests**

Create `camp/apps/emissions/tests/test_compliance.py`:

```python
from datetime import date
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase

from camp.apps.emissions import compliance, stats
from camp.apps.emissions.models import AirComplianceFacility, ComplianceEvent, Facility
from camp.apps.emissions.tests.test_stats import scope


def track(facility, pgm_sys_id, *, hpv='No Violation Identified', reported_through=None, name=None, **fields):
    """A matched ICIS row for `facility`."""
    return AirComplianceFacility.objects.create(
        facility=facility, pgm_sys_id=pgm_sys_id, registry_id='110000000001', name=name or facility.name,
        current_hpv=hpv, match_method='parsed', reported_through=reported_through, **fields,
    )


def event(row, kind, when, **fields):
    return ComplianceEvent.objects.create(icis_facility=row, kind=kind, date=when, agency='L', external_id=f'{kind}-{when}', **fields)


class ComplianceTestCase(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.plant = Facility.objects.get(name='TEST PLANT')
        self.station = Facility.objects.get(name='TEST GAS STATION')
        self.cement = Facility.objects.get(name='TEST CEMENT')


class CardTests(ComplianceTestCase):
    def test_none_without_a_match(self):
        assert compliance.facility_card(self.plant) is None
        AirComplianceFacility.objects.create(pgm_sys_id='CAKCA1', name='UNMATCHED')
        assert compliance.facility_card(self.cement) is None

    def test_rollups_count_back_from_reported_through(self):
        row = track(self.plant, 'CASJV00006019C0001', hpv='Unaddressed-Local', reported_through=date(2024, 6, 30), title_v=True, pollutant_class='Major')
        event(row, 'inspection', date(2019, 6, 30))   # a day before the window: out
        event(row, 'inspection', date(2019, 7, 1))    # the window's first day: in
        event(row, 'inspection', date(2024, 3, 15))
        event(row, 'nov', date(2023, 5, 2))
        event(row, 'formal', date(2024, 6, 30), penalty=Decimal('12500.50'))
        event(row, 'formal', date(2015, 1, 1), penalty=Decimal('99999'))
        event(row, 'hpv', date(2024, 4, 1), description='High-priority violation')
        card = compliance.facility_card(self.plant)
        assert card['primary'] == row and card['reported_through'] == date(2024, 6, 30) and card['since'] == date(2019, 7, 1)
        assert (card['inspections'], card['novs'], card['formals'], card['penalties']) == (2, 1, 1, Decimal('12500.50'))
        assert [e.date for e in card['events']][:2] == [date(2024, 6, 30), date(2024, 4, 1)]
        assert len(card['events']) == 7 and card['more'] == []
        assert card['names'] == []

    def test_names_as_reported_and_show_all_split(self):
        row = track(self.plant, 'CASJV00006019C0001', reported_through=date(2024, 1, 1), name='PREVIOUS OWNER LLC')
        for day in range(1, 31):
            event(row, 'inspection', date(2023, 1, day))
        card = compliance.facility_card(self.plant)
        assert card['names'] == ['PREVIOUS OWNER LLC']
        assert len(card['shown']) == 25 and len(card['more']) == 5

    def test_two_icis_rows_merge(self):
        old = track(self.plant, 'CASJV00006019C0001', reported_through=date(2020, 1, 1))
        new = track(self.plant, 'CASJV00006019C0009', reported_through=date(2024, 1, 1), hpv='Addressed-Local')
        event(old, 'nov', date(2019, 6, 1))
        event(new, 'nov', date(2023, 6, 1))
        card = compliance.facility_card(self.plant)
        assert card['primary'] == new and card['novs'] == 2 and len(card['events']) == 2

    def test_cache_clears_on_import(self):
        track(self.plant, 'CASJV00006019C0001', reported_through=date(2024, 1, 1))
        assert compliance.facility_card(self.plant)['novs'] == 0
        event(AirComplianceFacility.objects.get(), 'nov', date(2023, 1, 1))
        assert compliance.facility_card(self.plant)['novs'] == 0
        compliance.clear_caches()
        assert compliance.facility_card(self.plant)['novs'] == 1


class AreaAndFilterTests(ComplianceTestCase):
    def test_area_summary(self):
        assert compliance.area_summary(scope(year=2024)) is None
        track(self.plant, 'CASJV00006019C0001', hpv='Unaddressed-Local')
        track(self.station, 'CASJV00006029S0002')
        AirComplianceFacility.objects.create(pgm_sys_id='CAKCA1', name='UNMATCHED')  # never counted
        # 2024, major sources: TEST PLANT and TEST CEMENT; the station is minor.
        assert compliance.area_summary(scope(year=2024)) == {'facilities': 2, 'tracked': 1, 'unaddressed': 1}
        assert compliance.area_summary(scope(year=2024, minor=1)) == {'facilities': 3, 'tracked': 2, 'unaddressed': 1}
        assert compliance.area_summary(scope(year=2024, county='kern')) is None

    def test_facility_table_filter(self):
        track(self.plant, 'CASJV00006019C0001', hpv='Unaddressed-Local')
        track(self.cement, 'CAKCA1', hpv='Addressed-Local')
        names = lambda **kw: [r.facility.name for r in stats.facility_table(scope(year=2024), **kw)]
        assert names(compliance='any') == ['TEST CEMENT', 'TEST PLANT']
        assert names(compliance='hpv') == ['TEST PLANT']
        assert names(compliance='bogus') == names()
```

Append to `test_lists.py`:

```python
class ComplianceFilterTests(ListTestCase):
    def test_list_and_csv_follow_the_filter(self):
        from camp.apps.emissions.models import AirComplianceFacility
        AirComplianceFacility.objects.create(facility=self.plant, pgm_sys_id='CASJV00006019C0001', name='X', current_hpv='Unaddressed-Local', match_method='parsed')
        content = self.client.get(reverse('emissions:facility-list'), {'compliance': 'hpv'}).content.decode()
        assert 'TEST PLANT' in content and 'TEST CEMENT' not in content
        assert '<option value="hpv" selected>' in content
        body = self.client.get(reverse('emissions:facility-list'), {'compliance': 'any', 'format': 'csv'}).content.decode()
        assert 'TEST PLANT' in body and 'TEST CEMENT' not in body
        assert 'epa_tracked,hpv_status' in body.splitlines()[0]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$TEST camp/apps/emissions/tests/test_compliance.py camp/apps/emissions/tests/test_lists.py::ComplianceFilterTests`
Expected: FAIL (`AttributeError: module … has no attribute 'facility_card'`).

- [ ] **Step 3: Fill in `compliance.py`**

Append to `compliance.py` (imports at top: `from datetime import date`, `from decimal import Decimal`, `from django.db.models import Q`, `from camp.apps.emissions.models import AirComplianceFacility, ComplianceEvent, SourceImport`):

```python
SOURCE = 'icis-air'
WINDOW_YEARS = 5
SHOWN_EVENTS = 25
FILTERS = ('any', 'hpv')
FILTER_LABELS = (('', 'All facilities'), ('any', 'Tracked by EPA'), ('hpv', 'With an unaddressed high-priority violation'))
TRACKED = Q(facility__icis_facilities__isnull=False)
UNADDRESSED = Q(facility__icis_facilities__current_hpv__istartswith='unaddressed')


def stamp():
    return SourceImport.latest(SOURCE)


def years_before(day, years=WINDOW_YEARS):
    """`day` minus `years` years, plus one day: the first day of a window that ends on `day`."""
    try:
        start = day.replace(year=day.year - years)
    except ValueError:  # Feb 29
        start = day.replace(year=day.year - years, day=28)
    return date.fromordinal(start.toordinal() + 1)


def filter_q(value):
    """The facility list's ?compliance= as a Q on EmissionsRecord, or None for anything else."""
    if value == 'any':
        return TRACKED
    if value == 'hpv':
        return UNADDRESSED
    return None


def facility_card(facility):
    """
    The facility page's compliance card, or None when no ICIS row matched this
    facility (nothing is shown then, by design). Every matched row's events,
    newest first; the badges from the row reported most recently; the five-year
    rollups counted back from that row's reported_through.
    """
    def compute():
        rows = list(facility.icis_facilities.all())
        if not rows:
            return None
        primary = max(rows, key=lambda row: (row.reported_through or date.min, row.pk))
        through = primary.reported_through
        since = years_before(through) if through else None
        events = list(ComplianceEvent.objects.filter(icis_facility__in=rows).order_by('-date', '-pk'))
        recent = [e for e in events if since and e.date >= since]
        return {
            'rows': rows,
            'primary': primary,
            'reported_through': through,
            'since': since,
            'inspections': sum(e.kind == ComplianceEvent.Kind.INSPECTION for e in recent),
            'novs': sum(e.kind == ComplianceEvent.Kind.NOV for e in recent),
            'formals': sum(e.kind == ComplianceEvent.Kind.FORMAL for e in recent),
            'penalties': sum((e.penalty or Decimal(0) for e in recent if e.kind == ComplianceEvent.Kind.FORMAL), Decimal(0)),
            'events': events,
            'shown': events[:SHOWN_EVENTS],
            'more': events[SHOWN_EVENTS:],
            'names': sorted({row.name for row in rows if row.name.strip().upper() != facility.name.strip().upper()}),
        }
    return cache.get_or_set(key('card', facility.pk), compute, stats.CACHE_TIMEOUT)


def area_summary(scope):
    """
    For a region or near-me page: the scope's facilities, how many have a
    matched ICIS row and how many of those carry an unaddressed HPV; None when
    none are tracked (the line isn't shown).
    """
    def compute():
        records = stats.records(scope)
        tracked = records.filter(TRACKED).values('facility_id').distinct().count()
        if not tracked:
            return None
        return {
            'facilities': stats.totals(scope)['facilities'],
            'tracked': tracked,
            'unaddressed': records.filter(UNADDRESSED).values('facility_id').distinct().count(),
        }
    return cache.get_or_set(key('area', scope.key('compliance')), compute, stats.CACHE_TIMEOUT)
```

- [ ] **Step 4: The filter in `stats.facility_table` and the list view**

In `stats.py`, `facility_table` signature becomes `def facility_table(scope, *, sector=None, area=None, q=None, sort='-value', compliance=None):` and after the `q` filter:

```python
    if compliance:
        from camp.apps.emissions import compliance as _compliance  # compliance imports stats
        narrowed = _compliance.filter_q(compliance)
        if narrowed is not None:
            queryset = queryset.filter(narrowed).distinct()
```

In `views.py`, `list_filters` gains `'compliance': get.get('compliance') if get.get('compliance') in compliance.FILTERS else None` (import `compliance` beside `areas, dairies, stats`). `FacilityList.get_context_data` passes `compliance_options=compliance.FILTER_LABELS`. `csv_response` appends `'epa_tracked', 'hpv_status'` to the header and, per record, `['yes' if getattr(record, 'epa_tracked', None) else '', …]` — simplest: build `tracked = {row.facility_id: row for row in AirComplianceFacility.objects.exclude(facility=None).order_by('reported_through')}` once before the loop and write `'yes' if facility.pk in tracked else ''` and `tracked[facility.pk].hpv_status if facility.pk in tracked else ''`.

In `facility-list.html`, after the Sector field:

```django
            <div class="field">
                <label class="label" for="facility-compliance">EPA compliance</label>
                <div class="control"><div class="select is-fullwidth"><select id="facility-compliance" name="compliance">
                    {% for value, label in compliance_options %}<option value="{{ value }}"{% if filters.compliance == value %} selected{% endif %}>{{ label }}</option>{% endfor %}
                </select></div></div>
                <p class="help">About 660 large sources; <a href="{% url 'emissions:about' %}#compliance">what this covers</a>.</p>
            </div>
```

Note `<option value="hpv" selected>` must render exactly so (no space before `>`), which the markup above does.

- [ ] **Step 5: Run the tests**

Run: `$TEST camp/apps/emissions/tests/test_compliance.py camp/apps/emissions/tests/test_lists.py camp/apps/emissions/tests/test_stats.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git -C <worktree> add camp/apps/emissions/tests/test_compliance.py
git -C <worktree> commit -m "feat(emissions): compliance rollups, area counts and a facility list filter" -- camp/apps/emissions/compliance.py camp/apps/emissions/stats.py camp/apps/emissions/views.py camp/templates/emissions/facility-list.html camp/apps/emissions/tests/test_compliance.py camp/apps/emissions/tests/test_lists.py
```

---

### Task 5: The facility card, the region line, About and integrations

**Files:**
- Create: `camp/templates/emissions/includes/compliance-card.html`
- Modify: `camp/apps/emissions/views.py` (`FacilityDetail.get_context_data`, `AreaPage.get_context_data`)
- Modify: `camp/templates/emissions/facility-detail.html` (after the toxics table, before the Source line)
- Modify: `camp/templates/emissions/area.html` (after the Top facilities table)
- Modify: `camp/templates/emissions/about.html`, `datafiles/data-integrations.yaml`
- Test: `camp/apps/emissions/tests/test_compliance.py` (append `PageTests`)

**Interfaces:**
- Context: `compliance_card` (facility page), `compliance_line` (area pages: `area_summary` dict plus `'url'`), `compliance_stamp` (About: `SourceImport | None`).
- `views.compliance_list_url(scope, area) -> str`: the facility list with `compliance=hpv` and the area parameter per refinement 4.

- [ ] **Step 1: Write the failing tests**

Append to `test_compliance.py`:

```python
class PageTests(ComplianceTestCase):
    def detail(self, facility):
        return self.client.get(facility.get_absolute_url()).content.decode()

    def test_no_card_without_a_match(self):
        content = self.detail(self.plant)
        assert 'Compliance (federal Clean Air Act reporting)' not in content
        assert 'No violation' not in content and 'ECHO' not in content

    def test_card(self):
        row = track(self.plant, 'CASJV00006019C0001', hpv='Unaddressed-Local', reported_through=date(2024, 6, 30),
                    title_v=True, pollutant_class='Major', name='TEST PLANT INC')
        event(row, 'inspection', date(2024, 3, 15), action_type='FCE On-Site')
        event(row, 'nov', date(2023, 5, 2), action_type='Notice of Violation')
        event(row, 'formal', date(2024, 6, 30), action_type='Administrative - Formal (Settlement)', penalty=Decimal('12500.50'))
        content = self.detail(self.plant)
        assert 'Compliance (federal Clean Air Act reporting)' in content
        assert '<span class="tag">Title V</span>' in content and '<span class="tag">Major</span>' in content
        assert 'High-priority violation: unaddressed' in content
        assert 'Last 5 years: 1 inspection · 1 notice of violation · 1 formal action, $12,501 in penalties' in content
        assert 'href="https://echo.epa.gov/detailed-facility-report?fid=110000000001">Full record at EPA ECHO →</a>' in content
        assert 'Reported to EPA through June 30, 2024.' in content
        assert 'as reported to EPA: TEST PLANT INC' in content
        table = content[content.index('compliance-events'):]
        assert table.index('Administrative - Formal') < table.index('FCE On-Site') < table.index('Notice of Violation')
        assert '<details' not in content

    def test_show_all_and_addressed_badge(self):
        row = track(self.plant, 'CASJV00006019C0001', hpv='Addressed-EPA', reported_through=date(2024, 1, 1))
        for day in range(1, 31):
            event(row, 'inspection', date(2023, 1, day))
        content = self.detail(self.plant)
        assert 'High-priority violation: addressed' in content
        assert '<details class="compliance-more">' in content and 'Show all 30 events' in content

    def test_none_badge(self):
        track(self.plant, 'CASJV00006019C0001', reported_through=date(2024, 1, 1))
        assert 'No violation identified' in self.detail(self.plant)

    def test_region_line(self):
        from django.urls import reverse
        from camp.apps.regions.models import Region
        fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        assert 'tracked in EPA' not in self.client.get(fresno.get_emissions_url(), {'year': '2024'}).content.decode()
        track(self.plant, 'CASJV00006019C0001', hpv='Unaddressed-Local')
        content = self.client.get(fresno.get_emissions_url(), {'year': '2024'}).content.decode()
        assert "1 of the 1 facilities here are tracked in EPA's air compliance system; 1 have an unaddressed high-priority violation" in content
        assert f'href="{reverse("emissions:facility-list")}?year=2024&amp;compliance=hpv&amp;county=fresno"' in content or \
               f'href="{reverse("emissions:facility-list")}?compliance=hpv&amp;county=fresno"' in content
        assert 'tracked in EPA' not in self.client.get(kern.get_emissions_url(), {'year': '2024'}).content.decode()
        near = self.client.get(reverse('emissions:near-me'), {'lat': '36.737', 'lng': '-119.787', 'radius': '1', 'year': '2024'}).content.decode()
        assert 'tracked in EPA' in near and 'county=' not in near.split('compliance=hpv')[1][:40]

    def test_about_and_integrations(self):
        from django.urls import reverse
        content = self.client.get(reverse('emissions:about')).content.decode()
        assert '<h2 id="compliance">Compliance</h2>' in content
        assert 'Only large sources are here.' in content and 'No compliance data has been imported yet.' in content
        from camp.apps.emissions.models import SourceImport
        SourceImport.objects.create(source='icis-air', data_through=date(2025, 12, 31))
        content = self.client.get(reverse('emissions:about')).content.decode()
        assert 'Reported through Dec. 31, 2025.' in content
        assert 'EPA ECHO' in self.client.get('/about/integrations/').content.decode()
```

(The 2024 explorer year is the latest in the fixture, so `scope.query()` leaves `year` out; the `or` in the region-line assertion covers both spellings.)

- [ ] **Step 2: Run them to verify they fail**

Run: `$TEST camp/apps/emissions/tests/test_compliance.py::PageTests`
Expected: FAIL on the card text.

- [ ] **Step 3: The card include**

`camp/templates/emissions/includes/compliance-card.html`:

```django
{% load humanize %}
{% comment %}
A facility's Clean Air Act compliance record from EPA's ICIS-Air
(compliance.facility_card), shown only when an ICIS row matched this
facility: badges (Title V, the pollutant class, the current HPV status), the
five-year rollups counted back from the newest reported event, the dated
event table (25, then "Show all"), the ECHO link and the reported-through
stamp. Nothing is rendered for a facility with no row -- absence isn't compliance.
{% endcomment %}
{% with card=compliance_card icis=compliance_card.primary %}
<section class="compliance-card mt-5" id="compliance">
    <h3 class="title is-4">Compliance (federal Clean Air Act reporting)</h3>
    <div class="tags are-medium">
        {% if icis.title_v %}<span class="tag">Title V</span>{% endif %}
        {% if icis.pollutant_class %}<span class="tag">{{ icis.pollutant_class }}</span>{% endif %}
        {% if icis.hpv_status == 'unaddressed' %}<span class="tag is-danger is-light">High-priority violation: unaddressed</span>
        {% elif icis.hpv_status == 'addressed' %}<span class="tag is-warning is-light">High-priority violation: addressed</span>
        {% else %}<span class="tag is-light">No violation identified</span>{% endif %}
    </div>
    {% if card.since %}
    <p class="compliance-rollup">Last 5 years: {{ card.inspections|intcomma }} inspection{{ card.inspections|pluralize }} · {{ card.novs|intcomma }} notice{{ card.novs|pluralize }} of violation · {{ card.formals|intcomma }} formal action{{ card.formals|pluralize }}, ${{ card.penalties|floatformat:"0"|intcomma }} in penalties</p>
    {% endif %}
    {% if card.names %}<p class="is-size-7 has-text-grey">Name as reported to EPA: {{ card.names|join:"; " }}</p>{% endif %}
    {% if card.events %}
    <div class="table-container">
    <table class="table is-fullwidth is-narrow compliance-events">
        <thead><tr><th>Date</th><th>What</th><th>By</th><th>Detail</th><th class="has-text-right">Penalty</th></tr></thead>
        <tbody>
        {% for e in card.shown %}{% include 'emissions/includes/compliance-event-row.html' %}{% endfor %}
        </tbody>
    </table>
    {% if card.more %}
    <details class="compliance-more">
        <summary>Show all {{ card.events|length }} events</summary>
        <table class="table is-fullwidth is-narrow compliance-events"><tbody>
        {% for e in card.more %}{% include 'emissions/includes/compliance-event-row.html' %}{% endfor %}
        </tbody></table>
    </details>
    {% endif %}
    </div>
    {% endif %}
    <p><a href="{{ icis.dfr_url }}">Full record at EPA ECHO →</a>{% if card.reported_through %} <span class="has-text-grey">· Reported to EPA through {{ card.reported_through|date:"F j, Y" }}.</span>{% endif %}</p>
    <details class="compliance-caveats is-size-7">
        <summary>What this is, and isn't</summary>
        <p><strong>Only large sources are here.</strong> About 660 of the Valley's 11,000 permitted facilities are tracked in EPA's air compliance system. Smaller sources' inspections and violations aren't published anywhere. A facility with no compliance card isn't known to be in compliance.</p>
        <p><strong>The record runs late.</strong> The district reports to EPA roughly a year or more behind. Recent quarters look quiet because they haven't been reported yet, not because violations stopped.{% if card.reported_through %} Reported through {{ card.reported_through|date:"F j, Y" }}.{% endif %}</p>
        <p><strong>A notice of violation is an allegation.</strong> Many are settled without any admission, and penalties are negotiated amounts.</p>
        <p><strong>Names are as reported to EPA</strong> and may be a previous owner's.</p>
    </details>
</section>
{% endwith %}
```

The test asserts `as reported to EPA: TEST PLANT INC`; the line above reads "Name as reported to EPA: …", which contains it.

`camp/templates/emissions/includes/compliance-event-row.html`:

```django
{% load humanize %}
<tr>
    <td>{{ e.date|date:"Y-m-d" }}</td>
    <td>{{ e.get_kind_display }}</td>
    <td>{{ e.get_agency_display|default:"—" }}</td>
    <td>{{ e.action_type }}{% if e.kind == 'hpv' %}{% if e.pollutant %} · {{ e.pollutant }}{% endif %}{% if e.resolved %} · resolved {{ e.resolved|date:"Y-m-d" }}{% else %} · unresolved{% endif %}{% endif %}</td>
    <td class="has-text-right">{% if e.penalty is not None %}${{ e.penalty|floatformat:"0"|intcomma }}{% else %}—{% endif %}</td>
</tr>
```

In `facility-detail.html`, before the `Source:` paragraph: `{% if compliance_card %}{% include 'emissions/includes/compliance-card.html' %}{% endif %}`.

- [ ] **Step 4: Views**

`FacilityDetail.get_context_data` adds `compliance_card=compliance.facility_card(facility)`.

In `views.py` add, near `area_links`:

```python
def compliance_list_url(scope, area):
    """
    The facility list filtered to unaddressed HPVs, narrowed to the area where
    the list can be: ?county= for a county, ?region= for the types its region
    filter searches (cities, urban areas, CDPs, ZIPs), nothing for the rest.
    """
    params = dict(scope.params(county=None), compliance='hpv')
    region = getattr(area, 'region', None)
    if region is not None:
        if region.type == Region.Type.COUNTY:
            params['county'] = region.slug
        elif region.type in areas.FILTER_REGION_TYPES:
            params['region'] = region.sqid
    return f"{reverse('emissions:facility-list')}?{urlencode(params)}"
```

In `AreaPage.get_context_data`, after computing `scope` and `area`:

```python
        summary = compliance.area_summary(scope)
        compliance_line = dict(summary, url=compliance_list_url(base, area)) if summary else None
```

and pass `compliance_line=compliance_line`. In `area.html`, after the Top facilities block (after the `{% endif %}` closing `{% if top_rows %}`):

```django
{% if compliance_line %}
<p class="compliance-line is-size-7 mt-2">{{ compliance_line.tracked|intcomma }} of the {{ compliance_line.facilities|intcomma }} facilities here are tracked in EPA's air compliance system; {{ compliance_line.unaddressed|intcomma }} have an unaddressed high-priority violation <a href="{{ compliance_line.url }}">→</a></p>
{% endif %}
```

`About.get_context_data` adds `compliance_stamp=compliance.stamp()`.

- [ ] **Step 5: About and integrations**

In `about.html`, before `<h2 id="sources">`:

```django
<h2 id="compliance">Compliance</h2>
<p>Facility pages for the largest sources carry a <strong>Compliance (federal Clean Air Act reporting)</strong> card from EPA's ICIS-Air database, where the Valley Air District reports its inspections, notices of violation, settlements and high-priority violations for the sources federal law requires it to track. {% if compliance_stamp and compliance_stamp.data_through %}Reported through {{ compliance_stamp.data_through|date:"N j, Y" }}.{% else %}No compliance data has been imported yet.{% endif %}</p>
<ul>
    <li><strong>Only large sources are here.</strong> About 660 of the Valley's 11,000 permitted facilities are tracked in EPA's air compliance system. Smaller sources' inspections and violations aren't published anywhere. A facility with no compliance card isn't known to be in compliance.</li>
    <li><strong>The record runs late.</strong> The district reports to EPA roughly a year or more behind. Recent quarters look quiet because they haven't been reported yet, not because violations stopped.</li>
    <li><strong>A notice of violation is an allegation.</strong> Many are settled without any admission, and penalties are negotiated amounts.</li>
    <li><strong>Names are as reported to EPA</strong> and may be a previous owner's.</li>
    <li><strong>How facilities are matched.</strong> The district's facility id is embedded in EPA's id, so the match is exact for the Valley Air District's sources; Eastern Kern sources aren't matched yet. The five-year counts are measured back from the newest event EPA has, not from today.</li>
</ul>
```

Add to the Sources list: `<li><a href="https://echo.epa.gov/tools/data-downloads">EPA ECHO / ICIS-Air data downloads</a></li>`.

In `datafiles/data-integrations.yaml`, under `Emissions Data` after the CARB Pollution Mapping Tool entry:

```yaml
    - name: EPA ECHO (ICIS-Air)
      logo: img/logo/epa-vertical.svg
      url: https://echo.epa.gov/
      description: EPA's Enforcement and Compliance History Online publishes the Clean Air Act compliance record — inspections, notices of violation, settlements and high-priority violations — that air districts report for the largest permitted sources. SJVAir matches those records to the Valley Air District's facilities and shows each one's record on its facility page, stamped with how far the district's reporting reaches.
```

- [ ] **Step 6: Run the tests, then look at a page**

Run: `$TEST camp/apps/emissions/tests/test_compliance.py camp/apps/emissions/tests/test_facility_page.py camp/apps/emissions/tests/test_areas_pages.py camp/apps/emissions/tests/test_views.py`
Expected: PASS.

If the dev DB has data, run `docker exec $(docker ps --filter publish=8003 --format '{{.Names}}') python manage.py import_icis_air --path /path/to/ICIS-AIR_downloads.zip` (copy the zip into the container first with `docker cp`) and open Pastoria Energy Facility's page on :8003: the card, badges and table render; a county page shows the line.

- [ ] **Step 7: Commit**

```bash
git -C <worktree> add camp/templates/emissions/includes/compliance-card.html camp/templates/emissions/includes/compliance-event-row.html
git -C <worktree> commit -m "feat(emissions): the compliance card, the region line and the About section" -- camp/apps/emissions/views.py camp/templates/emissions/includes/compliance-card.html camp/templates/emissions/includes/compliance-event-row.html camp/templates/emissions/facility-detail.html camp/templates/emissions/area.html camp/templates/emissions/about.html datafiles/data-integrations.yaml camp/apps/emissions/tests/test_compliance.py
```

---

### Task 6: Part A full run and PR notes

- [ ] **Step 1: Full suites**

Run: `$TEST camp/apps/emissions camp/api/v2/emissions camp/apps/regions`
Expected: all PASS.

- [ ] **Step 2: Smoke**

Run the smoke script against :8003. Expected: `N/N checks passed`, `no console errors` (this part adds no map code; the run confirms nothing regressed).

- [ ] **Step 3: PR description**

Open a draft PR from the branch (no push until Derek says; write the description into `.superpowers/sdd/…/pr-body.md` for now). It must carry: what the card shows and doesn't; the match rule and rates (607/663 SJVAPCD rows, all 382 operating; EKAPCD unmatched pending `icis_crosswalk.py`); the reporting-lag caveat; Deploy: `migrate`; one-off `python manage.py import_icis_air` (≈70 MB download, a few minutes; or `--path`); the monthly task registers on the next `huey_primary` restart; `compliance.clear_caches()` runs inside the command.

---

# Part B: Phase 6, dairy Water Board compliance (CIWQS)

### Task 7: Models and migration (`DairyWaterEnrollment`, `DairyEnforcementAction`)

**Files:**
- Modify: `camp/apps/emissions/models.py`
- Create: `camp/apps/emissions/migrations/000N_dairy_water_board.py` (generated)
- Modify: `camp/apps/emissions/admin.py`
- Test: `camp/apps/emissions/tests/test_models.py`

**Interfaces:**
- `DairyWaterEnrollment(sqid, dairy FK CASCADE related_name='water_enrollments', reg_measure_id int unique, reg_measure_type, order_number, program, wdid, status, effective_date null, termination_date null, cafo_type, cafo_subtype, cafo_population int null)`; `is_active` property (`status.lower() == 'active'`).
- `DairyEnforcementAction(sqid, dairy FK CASCADE related_name='enforcement_actions', enforcement_id int unique, date, action_type char 40, status char 40, title char 255, description text, program char 64, assessment Decimal(12,2) null, paid Decimal(12,2) null, oldest_violation date null)`; `index (dairy, date)`.
- `Dairy.ciwqs_url` property → `https://ciwqs.waterboards.ca.gov/ciwqs/readOnly/CiwqsReportServlet?inCommand=reset&reportName=RegulatedFacility&placeID=<place_id>`.

- [ ] **Step 0: `SourceImport`**

Run `grep -n "class SourceImport" <worktree>/camp/apps/emissions/models.py`. If it prints nothing (neither Phase 1 nor Part A has merged into this branch), add the `SourceImport` class and its admin exactly as Task 1 Steps 3 and 5 give them, in this task's migration.

- [ ] **Step 1: Write the failing tests**

Append to `test_models.py`:

```python
from camp.apps.emissions.models import DairyEnforcementAction, DairyWaterEnrollment
from camp.apps.emissions.tests.test_dairies import make_dairies


class DairyWaterBoardTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def test_enrollment_action_and_url(self):
        big, small, closed = make_dairies()
        enrollment = DairyWaterEnrollment.objects.create(
            dairy=big, reg_measure_id=1, reg_measure_type='Enrollee', order_number='R5-2013-0122', program='ANIWSTCOWS',
            wdid='5F100001', status='Active', effective_date=date(2014, 1, 1), cafo_type='Dairy', cafo_subtype='Milk cows', cafo_population=1300,
        )
        assert enrollment.is_active and enrollment.sqid
        action = DairyEnforcementAction.objects.create(
            dairy=big, enforcement_id=1, date=date(2023, 5, 1), action_type='Notice of Violation', status='Historical',
            title='Late annual report', program='ANIWSTCOWS',
        )
        assert action.assessment is None and str(action).startswith('Notice of Violation')
        assert big.ciwqs_url.endswith(f'placeID={big.place_id}')
        with pytest.raises(IntegrityError):
            DairyEnforcementAction.objects.create(dairy=small, enforcement_id=1, date=date(2023, 5, 1), action_type='NOV')
```

- [ ] **Step 2: Run to verify failure**

Run: `$TEST camp/apps/emissions/tests/test_models.py::DairyWaterBoardTests`. Expected: `ImportError`.

- [ ] **Step 3: Models**

Add to `Dairy`:

```python
    @property
    def ciwqs_url(self):
        """This dairy's Regulated Facility report at the State Water Board's CIWQS (CADD place_id = CIWQS facility_id)."""
        return ('https://ciwqs.waterboards.ca.gov/ciwqs/readOnly/CiwqsReportServlet'
                f'?inCommand=reset&reportName=RegulatedFacility&placeID={self.place_id}')
```

Append after `Digester`:

```python
class DairyWaterEnrollment(models.Model):
    """
    A dairy's enrollment under a Regional Water Board order (CIWQS "regulatory
    measure"): the Dairy General Order for most. Water quality, not air.
    """

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.DairyWaterEnrollment'))
    dairy = models.ForeignKey(Dairy, verbose_name=_('Dairy'), on_delete=models.CASCADE, related_name='water_enrollments')
    reg_measure_id = models.IntegerField(_('Regulatory measure id'), unique=True)
    reg_measure_type = models.CharField(_('Regulatory measure type'), max_length=64, blank=True)
    order_number = models.CharField(_('Order number'), max_length=32, blank=True)
    program = models.CharField(_('Program'), max_length=32, blank=True)
    wdid = models.CharField(_('WDID'), max_length=32, blank=True)
    status = models.CharField(_('Status'), max_length=32, blank=True)
    effective_date = models.DateField(_('Effective date'), null=True, blank=True)
    termination_date = models.DateField(_('Termination date'), null=True, blank=True)
    cafo_type = models.CharField(_('CAFO type'), max_length=64, blank=True)
    cafo_subtype = models.CharField(_('CAFO subtype'), max_length=64, blank=True)
    # The herd the dairy reported to the Water Board (not CADD's count).
    cafo_population = models.IntegerField(_('Reported herd'), null=True, blank=True)

    def __str__(self):
        return f'{self.dairy.name} {self.order_number} ({self.status})'

    @property
    def is_active(self):
        return self.status.strip().lower() == 'active'


class DairyEnforcementAction(models.Model):
    """One Regional Water Board enforcement action at a dairy (CIWQS): a notice of violation, a letter, a liability."""

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.DairyEnforcementAction'))
    dairy = models.ForeignKey(Dairy, verbose_name=_('Dairy'), on_delete=models.CASCADE, related_name='enforcement_actions')
    enforcement_id = models.IntegerField(_('Enforcement id'), unique=True)
    date = models.DateField(_('Effective date'))
    action_type = models.CharField(_('Action type'), max_length=40, blank=True)
    status = models.CharField(_('Status'), max_length=40, blank=True)
    title = models.CharField(_('Title'), max_length=255, blank=True)
    description = models.TextField(_('Description'), blank=True)
    program = models.CharField(_('Program'), max_length=64, blank=True)
    assessment = models.DecimalField(_('Total assessment'), max_digits=12, decimal_places=2, null=True, blank=True)
    paid = models.DecimalField(_('Liability paid'), max_digits=12, decimal_places=2, null=True, blank=True)
    oldest_violation = models.DateField(_('Oldest linked violation'), null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=['dairy', 'date'])]

    def __str__(self):
        return f'{self.action_type} {self.date} ({self.dairy.name})'
```

- [ ] **Step 4: Migration and admin**

Run `makemigrations emissions --name dairy_water_board` (the Task 1 command). In `admin.py` add both models to the import and:

```python
@admin.register(DairyEnforcementAction)
class DairyEnforcementActionAdmin(ReadOnlyAdminMixin, base_admin.ModelAdmin):
    list_display = ['dairy', 'date', 'action_type', 'status', 'title', 'assessment']
    list_filter = ['action_type', 'status']
    search_fields = ['dairy__name', 'title', 'description']
    raw_id_fields = ['dairy']


@admin.register(DairyWaterEnrollment)
class DairyWaterEnrollmentAdmin(ReadOnlyAdminMixin, base_admin.ModelAdmin):
    list_display = ['dairy', 'order_number', 'status', 'wdid', 'cafo_population', 'effective_date', 'termination_date']
    list_filter = ['status', 'order_number']
    search_fields = ['dairy__name', 'wdid']
    raw_id_fields = ['dairy']
```

- [ ] **Step 5: Run and commit**

Run: `$TEST camp/apps/emissions/tests/test_models.py`. Expected: PASS.

```bash
git -C <worktree> add camp/apps/emissions/migrations/000N_dairy_water_board.py
git -C <worktree> commit -m "feat(dairies): DairyWaterEnrollment and DairyEnforcementAction models" -- camp/apps/emissions/models.py camp/apps/emissions/migrations/000N_dairy_water_board.py camp/apps/emissions/admin.py camp/apps/emissions/tests/test_models.py
```

---

### Task 8: `ciwqs.py`, the command and the task

**Files:**
- Create: `camp/apps/emissions/ciwqs.py`
- Create: `camp/apps/emissions/management/commands/import_ciwqs_dairies.py`
- Modify: `camp/apps/emissions/tasks.py` (create it with only this task if Part A hasn't merged)
- Create: `camp/apps/emissions/tests/data/ciwqs/cafo.csv`, `camp/apps/emissions/tests/data/ciwqs/enforcement.csv`
- Test: `camp/apps/emissions/tests/test_ciwqs.py` (new), `camp/apps/emissions/tests/test_tasks.py`

**Interfaces:**
- `ciwqs.CAFO_RESOURCE = 'c16335af-f2dc-41e6-a429-f19edba5b957'`, `ciwqs.ENFORCEMENT_RESOURCE = '64f25cad-2e10-4a66-8368-79293f56c2f1'`, `ciwqs.REGION = '5'`, `ciwqs.SOURCE = 'ciwqs'`, `ciwqs.WINDOW_YEARS = 5`.
- `ciwqs.resource_url(resource_id) -> str` (CKAN `resource_show`; network; tests patch).
- `ciwqs.download(url) -> str` (temp CSV path; network; tests patch).
- `ciwqs.read_cafo(path) -> list[dict]` (region 5 rows), `ciwqs.read_enforcement(path, place_ids) -> list[dict]` (rows whose `FACILITY ID` is in `place_ids`).
- `ciwqs.apply(cafo_rows, enforcement_rows) -> Report`.
- `ciwqs.window() -> (since: date | None, through: date | None)` from `SourceImport.latest('ciwqs')`, cached under the dairies generation.
- `tasks.import_ciwqs_dairies`: `db_periodic_task(crontab(day='3', hour='11', minute='0'), priority=20)`, lock `import-ciwqs-dairies`.

- [ ] **Step 1: Produce the sample files**

```bash
mkdir -p /tmp/ciwqs && cd /tmp/ciwqs
CAFO=$(curl -s 'https://data.ca.gov/api/3/action/resource_show?id=c16335af-f2dc-41e6-a429-f19edba5b957' | python3 -c 'import json,sys;print(json.load(sys.stdin)["result"]["url"])')
ENF=$(curl -s 'https://data.ca.gov/api/3/action/resource_show?id=64f25cad-2e10-4a66-8368-79293f56c2f1' | python3 -c 'import json,sys;print(json.load(sys.stdin)["result"]["url"])')
curl -sSLo cafo.csv "$CAFO"; curl -sSLo enforcement.csv "$ENF"
OUT=<worktree>/camp/apps/emissions/tests/data/ciwqs; mkdir -p "$OUT"
# Header + 6 region-5 cow-dairy rows + 1 non-region-5 row.
head -1 cafo.csv > "$OUT/cafo.csv"; grep -m6 ',5,.*ANIWSTCOWS' cafo.csv >> "$OUT/cafo.csv"; grep -m1 -v ',5,' cafo.csv | tail -1 >> "$OUT/cafo.csv"
# Header + the enforcement rows for the first two facility ids in the CAFO sample (up to 8 rows).
head -1 enforcement.csv > "$OUT/enforcement.csv"
for id in $(tail -n +2 "$OUT/cafo.csv" | head -2 | python3 -c 'import csv,sys;[print(r["facility_id"]) for r in csv.DictReader(sys.stdin)]'); do grep -m4 "^\"\?$id," enforcement.csv >> "$OUT/enforcement.csv"; done
wc -l "$OUT"/*.csv; head -1 "$OUT"/*.csv
```

Read both headers. This plan's `ciwqs.CAFO_COLUMNS` / `ENFORCEMENT_COLUMNS` below use the names the research recorded; if the real header spells any differently (case, spaces), change the constants to the real spelling. Note the facility ids the sample carries: the tests below use `make_dairy(..., place_id=…)` with them, so read them from the file and put them in `test_ciwqs.SAMPLE_PLACE_IDS`.

- [ ] **Step 2: Write the failing tests**

`make_dairy` in `test_dairies.py` sets `place_id=cadd_id`; extend its signature to `make_dairy(cadd_id, name, lnglat, county, herds=None, digesters=(), city='Riverdale', place_id=None)` and use `place_id=place_id if place_id is not None else cadd_id`.

Create `camp/apps/emissions/tests/test_ciwqs.py`:

```python
import csv
import os
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase

from camp.apps.emissions import ciwqs, dairies
from camp.apps.emissions.models import DairyEnforcementAction, DairyWaterEnrollment, SourceImport
from camp.apps.emissions.tests.test_dairies import IN_KERN, NEAR_PLANT, make_dairies, make_dairy
from camp.apps.regions.models import Region

DATA = Path(__file__).parent / 'data' / 'ciwqs'
# The facility ids in data/ciwqs/cafo.csv, in row order (fill in from the file).
SAMPLE_PLACE_IDS = [...]

CAFO = [
    {'reg_measure_id': '101', 'reg_measure_type': 'Enrollee', 'order_number': 'R5-2013-0122', 'program': 'ANIWSTCOWS', 'wdid': '5F100001',
     'region': '5', 'status': 'Active', 'effective_date': '2014-01-01', 'termination_date': '', 'facility_id': '1', 'facility_name': 'BIG DAIRY',
     'cafo_subtype': 'Milk Cows', 'cafo_type': 'Dairy', 'cafo_population': '1300'},
    {'reg_measure_id': '102', 'reg_measure_type': 'Enrollee', 'order_number': 'R5-2007-0035', 'program': 'ANIWSTCOWS', 'wdid': '5F100001',
     'region': '5', 'status': 'Historical', 'effective_date': '2007-05-03', 'termination_date': '2013-12-31', 'facility_id': '1', 'facility_name': 'BIG DAIRY',
     'cafo_subtype': 'Milk Cows', 'cafo_type': 'Dairy', 'cafo_population': '1000'},
    {'reg_measure_id': '103', 'reg_measure_type': 'Enrollee', 'order_number': 'R5-2013-0122', 'program': 'ANIWSTCOWS', 'wdid': '5D100002',
     'region': '5', 'status': 'Active', 'effective_date': '2014-01-01', 'termination_date': '', 'facility_id': '2', 'facility_name': 'SMALL DAIRY',
     'cafo_subtype': 'Milk Cows', 'cafo_type': 'Dairy', 'cafo_population': ''},
    {'reg_measure_id': '104', 'reg_measure_type': 'Enrollee', 'order_number': 'R8-0001', 'program': 'ANIWSTCOWS', 'wdid': '8A1',
     'region': '8', 'status': 'Active', 'effective_date': '2014-01-01', 'termination_date': '', 'facility_id': '1', 'facility_name': 'ELSEWHERE',
     'cafo_subtype': '', 'cafo_type': '', 'cafo_population': ''},
    {'reg_measure_id': '105', 'reg_measure_type': 'Enrollee', 'order_number': 'R5-2013-0122', 'program': 'ANIWSTCOWS', 'wdid': '5F9',
     'region': '5', 'status': 'Active', 'effective_date': '2014-01-01', 'termination_date': '', 'facility_id': '999', 'facility_name': 'NOT IN CADD',
     'cafo_subtype': '', 'cafo_type': '', 'cafo_population': ''},
]
ENFORCEMENT = [
    {'FACILITY ID': '1', 'ENFORCEMENT ID (EID)': '501', 'ENFORCEMENT ACTION TYPE': 'Notice of Violation', 'ENF ACTION EFFECTIVE DATE': '05/01/2023',
     'ENF ACTION STATUS': 'Historical', 'TITLE': 'Late annual report', 'DESCRIPTION': 'failure to submit Annual Report', 'PROGRAM': 'ANIWSTCOWS',
     'TOTAL ASSESSMENT AMOUNT': '', 'LIABILITY $ PAID': '', 'DATE OF OLDEST VIOLATION LINKED TO ENFORCEMENT ACTION': '02/01/2023'},
    {'FACILITY ID': '1', 'ENFORCEMENT ID (EID)': '502', 'ENFORCEMENT ACTION TYPE': 'Admin Civil Liability', 'ENF ACTION EFFECTIVE DATE': '2019-07-01',
     'ENF ACTION STATUS': 'Historical', 'TITLE': 'ACL', 'DESCRIPTION': 'ponded water east of lagoon', 'PROGRAM': 'ANIWSTCOWS',
     'TOTAL ASSESSMENT AMOUNT': '15000', 'LIABILITY $ PAID': '12000.00', 'DATE OF OLDEST VIOLATION LINKED TO ENFORCEMENT ACTION': ''},
    {'FACILITY ID': '1', 'ENFORCEMENT ID (EID)': '503', 'ENFORCEMENT ACTION TYPE': 'Staff Enforcement Letter', 'ENF ACTION EFFECTIVE DATE': '06/30/2019',
     'ENF ACTION STATUS': 'Historical', 'TITLE': 'Letter', 'DESCRIPTION': '', 'PROGRAM': 'ANIWSTCOWS',
     'TOTAL ASSESSMENT AMOUNT': '', 'LIABILITY $ PAID': '', 'DATE OF OLDEST VIOLATION LINKED TO ENFORCEMENT ACTION': ''},
    {'FACILITY ID': '2', 'ENFORCEMENT ID (EID)': '504', 'ENFORCEMENT ACTION TYPE': 'Notice of Violation', 'ENF ACTION EFFECTIVE DATE': '06/30/2024',
     'ENF ACTION STATUS': 'Active', 'TITLE': 'NOV', 'DESCRIPTION': 'x', 'PROGRAM': 'ANIWSTCOWS',
     'TOTAL ASSESSMENT AMOUNT': '', 'LIABILITY $ PAID': '', 'DATE OF OLDEST VIOLATION LINKED TO ENFORCEMENT ACTION': ''},
    {'FACILITY ID': '999', 'ENFORCEMENT ID (EID)': '505', 'ENFORCEMENT ACTION TYPE': 'Notice of Violation', 'ENF ACTION EFFECTIVE DATE': '01/01/2024',
     'ENF ACTION STATUS': 'Active', 'TITLE': 'NOV', 'DESCRIPTION': '', 'PROGRAM': 'ANIWSTCOWS',
     'TOTAL ASSESSMENT AMOUNT': '', 'LIABILITY $ PAID': '', 'DATE OF OLDEST VIOLATION LINKED TO ENFORCEMENT ACTION': ''},
]


def write_csv(directory, name, rows):
    path = os.path.join(directory, name)
    with open(path, 'w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


class CiwqsTestCase(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.big, self.small, self.closed = make_dairies()  # place_ids 1, 2, 3
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def run_apply(self, cafo=CAFO, enforcement=ENFORCEMENT):
        cafo_rows = ciwqs.read_cafo(write_csv(self.tmp.name, 'cafo.csv', cafo))
        place_ids = set(ciwqs.place_ids())
        enforcement_rows = ciwqs.read_enforcement(write_csv(self.tmp.name, 'enf.csv', enforcement), place_ids)
        return ciwqs.apply(cafo_rows, enforcement_rows)


class ReadTests(CiwqsTestCase):
    def test_region_and_place_filters(self):
        rows = ciwqs.read_cafo(write_csv(self.tmp.name, 'cafo.csv', CAFO))
        assert [row['reg_measure_id'] for row in rows] == ['101', '102', '103', '105']
        rows = ciwqs.read_enforcement(write_csv(self.tmp.name, 'enf.csv', ENFORCEMENT), {1, 2})
        assert [row['ENFORCEMENT ID (EID)'] for row in rows] == ['501', '502', '503', '504']

    def test_the_real_layout(self):
        rows = ciwqs.read_cafo(DATA / 'cafo.csv')
        assert rows and all(row['region'].strip() == '5' for row in rows)
        assert [int(row['facility_id']) for row in rows][:2] == SAMPLE_PLACE_IDS[:2]
        enforcement = ciwqs.read_enforcement(DATA / 'enforcement.csv', set(SAMPLE_PLACE_IDS))
        assert enforcement
        assert all(ciwqs.parse_date(row['ENF ACTION EFFECTIVE DATE']) for row in enforcement)


class ApplyTests(CiwqsTestCase):
    def test_joins_on_place_id_and_ignores_the_rest(self):
        report = self.run_apply()
        assert set(self.big.water_enrollments.values_list('reg_measure_id', flat=True)) == {101, 102}
        active = self.big.water_enrollments.get(reg_measure_id=101)
        assert active.is_active and active.cafo_population == 1300 and active.effective_date == date(2014, 1, 1)
        assert self.small.water_enrollments.get().cafo_population is None
        assert not DairyWaterEnrollment.objects.filter(reg_measure_id__in=[104, 105]).exists()
        acl = self.big.enforcement_actions.get(enforcement_id=502)
        assert (acl.date, acl.assessment, acl.paid, acl.action_type) == (date(2019, 7, 1), Decimal('15000'), Decimal('12000.00'), 'Admin Civil Liability')
        assert self.big.enforcement_actions.get(enforcement_id=501).oldest_violation == date(2023, 2, 1)
        assert not DairyEnforcementAction.objects.filter(enforcement_id=505).exists()
        assert report.enrollments == 3 and report.actions == 4 and report.unmatched_enrollments == 1
        stamp = SourceImport.latest('ciwqs')
        assert stamp.data_through == date(2024, 6, 30)

    def test_rerun_replaces_actions(self):
        self.run_apply()
        self.run_apply(enforcement=[dict(ENFORCEMENT[0], TITLE='Renamed')], cafo=CAFO[:1] + CAFO[2:])
        assert self.big.enforcement_actions.count() == 1 and self.big.enforcement_actions.get().title == 'Renamed'
        assert not self.big.water_enrollments.filter(reg_measure_id=102).exists()
        assert self.small.enforcement_actions.count() == 0

    def test_window_boundary(self):
        # data_through is 2024-06-30, so the window starts 2019-07-01: the ACL on that day is in, the letter on 06-30 out.
        self.run_apply()
        since, through = ciwqs.window()
        assert (since, through) == (date(2019, 7, 1), date(2024, 6, 30))
        rows = {herd.dairy.name: herd for herd in dairies.table(2023)}
        assert rows['BIG DAIRY'].actions_5y == 2 and rows['SMALL DAIRY'].actions_5y == 1
        assert [herd.dairy.name for herd in dairies.table(2023, enforcement='5y')] == ['BIG DAIRY', 'SMALL DAIRY']
        DairyEnforcementAction.objects.filter(dairy=self.small).delete()
        dairies.clear_caches()
        assert [herd.dairy.name for herd in dairies.table(2023, enforcement='5y')] == ['BIG DAIRY']
        assert dairies.summary(2023)['water_actions'] == 1

    def test_no_import_yet(self):
        assert ciwqs.window() == (None, None)
        rows = {herd.dairy.name: herd for herd in dairies.table(2023)}
        assert rows['BIG DAIRY'].actions_5y == 0
        assert dairies.summary(2023)['water_actions'] == 0


class CommandTests(CiwqsTestCase):
    def test_paths(self):
        cafo = write_csv(self.tmp.name, 'cafo.csv', CAFO)
        enforcement = write_csv(self.tmp.name, 'enf.csv', ENFORCEMENT)
        call_command('import_ciwqs_dairies', cafo_path=cafo, enforcement_path=enforcement)
        assert DairyEnforcementAction.objects.count() == 4

    def test_default_resolves_and_downloads(self):
        cafo = write_csv(self.tmp.name, 'cafo.csv', CAFO)
        enforcement = write_csv(self.tmp.name, 'enf.csv', ENFORCEMENT)
        with patch('camp.apps.emissions.ciwqs.resource_url', side_effect=lambda rid: f'https://example.invalid/{rid}.csv') as resolve, \
                patch('camp.apps.emissions.ciwqs.download', side_effect=[cafo, enforcement]) as download:
            call_command('import_ciwqs_dairies')
        assert [c.args[0] for c in resolve.call_args_list] == [ciwqs.CAFO_RESOURCE, ciwqs.ENFORCEMENT_RESOURCE]
        assert download.call_count == 2
        assert DairyWaterEnrollment.objects.count() == 3
```

Append to `test_tasks.py`:

```python
class ImportCiwqsTaskTests(TestCase):
    @patch('camp.apps.emissions.tasks.call_command')
    def test_runs_the_command_under_the_lock(self, call_command):
        tasks.import_ciwqs_dairies.call_local()
        call_command.assert_called_once_with('import_ciwqs_dairies')
```

- [ ] **Step 3: Run to verify failure**

Run: `$TEST camp/apps/emissions/tests/test_ciwqs.py`. Expected: `ImportError: cannot import name 'ciwqs'`.

- [ ] **Step 4: Write `ciwqs.py`**

```python
"""
The Central Valley Regional Water Board's dairy records from the State Water
Board's CIWQS, as data.ca.gov publishes them: each dairy's enrollment under
the Dairy General Order (a "regulatory measure") and its enforcement actions.
Water quality (manure, lagoons, groundwater), not air.

CADD's place_id is CIWQS's facility_id: 1,506 of 1,558 Valley dairies join
exactly. CKAN regenerates the CSVs with a dated filename, so the current URL
is looked up through resource_show each run.
"""
import csv
import tempfile
from dataclasses import dataclass
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

import requests

from django.core.cache import cache
from django.db import transaction

from camp.apps.emissions import stats
from camp.apps.emissions.models import Dairy, DairyEnforcementAction, DairyWaterEnrollment, SourceImport

SOURCE = 'ciwqs'
CKAN = 'https://data.ca.gov/api/3/action/resource_show'
CAFO_RESOURCE = 'c16335af-f2dc-41e6-a429-f19edba5b957'
ENFORCEMENT_RESOURCE = '64f25cad-2e10-4a66-8368-79293f56c2f1'
REGION = '5'
WINDOW_YEARS = 5
CAFO_COLUMNS = ('reg_measure_id', 'reg_measure_type', 'order_number', 'program', 'wdid', 'region', 'status', 'effective_date',
                'termination_date', 'facility_id', 'cafo_subtype', 'cafo_type', 'cafo_population')
ENFORCEMENT_COLUMNS = ('FACILITY ID', 'ENFORCEMENT ID (EID)', 'ENFORCEMENT ACTION TYPE', 'ENF ACTION EFFECTIVE DATE', 'ENF ACTION STATUS',
                       'TITLE', 'DESCRIPTION', 'PROGRAM', 'TOTAL ASSESSMENT AMOUNT', 'LIABILITY $ PAID',
                       'DATE OF OLDEST VIOLATION LINKED TO ENFORCEMENT ACTION')
DATE_FORMATS = ('%m/%d/%Y', '%Y-%m-%d', '%m/%d/%Y %H:%M:%S', '%Y-%m-%d %H:%M:%S', '%m/%d/%Y %I:%M:%S %p')


class CIWQSFormatError(ValueError):
    """A CSV isn't the layout this importer knows: a column is missing."""


def parse_date(value):
    value = (value or '').strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def parse_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def parse_decimal(value):
    value = (value or '').strip().replace(',', '').replace('$', '')
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def resource_url(resource_id):
    """The resource's current CSV URL from CKAN (the filename carries a date). Network."""
    response = requests.get(CKAN, params={'id': resource_id}, timeout=60)
    response.raise_for_status()
    return response.json()['result']['url']


def download(url):
    """Fetch a CSV to a temp file and return its path (the caller unlinks it). Network."""
    response = requests.get(url, timeout=600, stream=True)
    response.raise_for_status()
    with tempfile.NamedTemporaryFile(suffix='.csv', delete=False) as tmp:
        for chunk in response.iter_content(chunk_size=1 << 20):
            tmp.write(chunk)
    return tmp.name


def _reader(path, columns):
    handle = open(path, newline='', encoding='utf-8-sig', errors='replace')
    reader = csv.DictReader(handle)
    # Column names as CKAN exports them, case-insensitively.
    header = {name.strip().upper(): name for name in reader.fieldnames or []}
    missing = [column for column in columns if column.upper() not in header]
    if missing:
        handle.close()
        raise CIWQSFormatError(f"{path} has no {', '.join(missing)} column.")
    rename = {header[column.upper()]: column for column in columns}
    for row in reader:
        yield {rename[name]: value for name, value in row.items() if name in rename}
    handle.close()


def place_ids():
    """Every CADD place_id, the join key."""
    return Dairy.objects.values_list('place_id', flat=True)


def read_cafo(path):
    """The Confined Animal Facilities rows in Water Board region 5, in file order."""
    return [row for row in _reader(path, CAFO_COLUMNS) if row['region'].strip() == REGION]


def read_enforcement(path, place_ids):
    """The enforcement rows whose FACILITY ID is a CADD place_id (the file is statewide, 53k rows), streamed."""
    wanted = set(place_ids)
    return [row for row in _reader(path, ENFORCEMENT_COLUMNS) if parse_int(row['FACILITY ID']) in wanted]


@dataclass
class Report:
    enrollments: int = 0
    unmatched_enrollments: int = 0
    actions: int = 0
    skipped: int = 0
    dairies_with_actions: int = 0
    data_through: object = None

    def lines(self):
        return [
            f'Enrollments: {self.enrollments:,} on {self.enrollments and "CADD dairies" or "none"}; {self.unmatched_enrollments:,} region-5 rows not in CADD.',
            f'Enforcement actions: {self.actions:,} on {self.dairies_with_actions:,} dairies ({self.skipped:,} skipped, no date). Reported through {self.data_through or "—"}.',
        ]


def apply(cafo_rows, enforcement_rows):
    """
    Replace every matched dairy's enrollments and actions with the files', in
    one transaction, and stamp SourceImport('ciwqs') with the newest action date.
    A dairy in CADD but not in the files ends with none (rows no longer present go).
    """
    from camp.apps.emissions import dairies

    report = Report()
    by_place = dict(Dairy.objects.values_list('place_id', 'pk'))
    with transaction.atomic():
        DairyWaterEnrollment.objects.all().delete()
        DairyEnforcementAction.objects.all().delete()
        enrollments = {}
        for row in cafo_rows:
            dairy_id = by_place.get(parse_int(row['facility_id']))
            reg_measure_id = parse_int(row['reg_measure_id'])
            if dairy_id is None or reg_measure_id is None:
                report.unmatched_enrollments += 1
                continue
            enrollments[reg_measure_id] = DairyWaterEnrollment(
                dairy_id=dairy_id, reg_measure_id=reg_measure_id,
                reg_measure_type=row['reg_measure_type'].strip()[:64], order_number=row['order_number'].strip()[:32],
                program=row['program'].strip()[:32], wdid=row['wdid'].strip()[:32], status=row['status'].strip()[:32],
                effective_date=parse_date(row['effective_date']), termination_date=parse_date(row['termination_date']),
                cafo_type=row['cafo_type'].strip()[:64], cafo_subtype=row['cafo_subtype'].strip()[:64],
                cafo_population=parse_int(row['cafo_population']),
            )
        DairyWaterEnrollment.objects.bulk_create(enrollments.values(), batch_size=1000)
        report.enrollments = len(enrollments)
        actions = {}
        for row in enforcement_rows:
            dairy_id = by_place.get(parse_int(row['FACILITY ID']))
            enforcement_id = parse_int(row['ENFORCEMENT ID (EID)'])
            when = parse_date(row['ENF ACTION EFFECTIVE DATE'])
            if dairy_id is None or enforcement_id is None:
                continue
            if when is None:
                report.skipped += 1
                continue
            actions[enforcement_id] = DairyEnforcementAction(
                dairy_id=dairy_id, enforcement_id=enforcement_id, date=when,
                action_type=row['ENFORCEMENT ACTION TYPE'].strip()[:40], status=row['ENF ACTION STATUS'].strip()[:40],
                title=row['TITLE'].strip()[:255], description=row['DESCRIPTION'].strip(), program=row['PROGRAM'].strip()[:64],
                assessment=parse_decimal(row['TOTAL ASSESSMENT AMOUNT']), paid=parse_decimal(row['LIABILITY $ PAID']),
                oldest_violation=parse_date(row['DATE OF OLDEST VIOLATION LINKED TO ENFORCEMENT ACTION']),
            )
        DairyEnforcementAction.objects.bulk_create(actions.values(), batch_size=2000)
        report.actions = len(actions)
        report.dairies_with_actions = len({action.dairy_id for action in actions.values()})
        report.data_through = max((action.date for action in actions.values()), default=None)
        SourceImport.objects.create(source=SOURCE, data_through=report.data_through,
                                    notes={'enrollments': report.enrollments, 'actions': report.actions})
    dairies.clear_caches()
    return report


def years_before(day, years=WINDOW_YEARS):
    """`day` minus `years` years, plus one day: the first day of a window ending on `day`."""
    try:
        start = day.replace(year=day.year - years)
    except ValueError:
        start = day.replace(year=day.year - years, day=28)
    return date.fromordinal(start.toordinal() + 1)


def window():
    """
    (since, through): the five-year window every surface uses, ending on the
    newest action date CIWQS has (SourceImport('ciwqs').data_through), not
    today -- the feed runs late. (None, None) before any import.
    """
    from camp.apps.emissions import dairies

    def compute():
        stamp = SourceImport.latest(SOURCE)
        if stamp is None or stamp.data_through is None:
            return None, None
        return years_before(stamp.data_through), stamp.data_through
    return cache.get_or_set(dairies.key('ciwqs-window'), compute, stats.CACHE_TIMEOUT)
```

- [ ] **Step 5: `dairies.py`: the annotation, filter and summary key**

In `dairies.py`:

- `TABLE_SORTS` gains `'actions_5y', '-actions_5y'`; `ENFORCEMENT_FILTERS = ('5y',)`.
- Add a helper:

```python
def _recent_actions():
    """A Subquery counting the outer herd's dairy's Water Board actions inside ciwqs.window(); 0 before any import."""
    from camp.apps.emissions import ciwqs
    from camp.apps.emissions.models import DairyEnforcementAction

    since, through = ciwqs.window()
    if since is None:
        return Value(0, output_field=IntegerField())
    recent = (
        DairyEnforcementAction.objects.filter(dairy=OuterRef('dairy'), date__gte=since, date__lte=through)
        .order_by().values('dairy').annotate(n=Count('pk')).values('n')[:1]
    )
    return Coalesce(Subquery(recent, output_field=IntegerField()), Value(0))
```

(imports: `Value, IntegerField` from `django.db.models`, `Coalesce` from `django.db.models.functions`.)

- `table(year, *, county=None, area=None, q=None, sort=DEFAULT_SORT, enforcement=None)`: annotate `actions_5y=_recent_actions()` beside `digester`; after the `q` filter, `if enforcement == '5y': queryset = queryset.filter(actions_5y__gt=0)`; the sort `expression` dict gains `'actions_5y': F('actions_5y')`.
- `summary()` gains `'water_actions': queryset.annotate(actions_5y=_recent_actions()).filter(actions_5y__gt=0).count()` (0 when `year is None`), computed inside `compute()`.
- Update `test_dairies.py::test_summary` expected dicts to include `'water_actions': 0`.

- [ ] **Step 6: The command and the task**

`camp/apps/emissions/management/commands/import_ciwqs_dairies.py`:

```python
import os

from django.core.management.base import BaseCommand, CommandError

from camp.apps.emissions import ciwqs


class Command(BaseCommand):
    help = (
        "Import the Central Valley Water Board's dairy enrollments and enforcement actions (CIWQS, via data.ca.gov), "
        'joined to CADD dairies on place_id. Idempotent. Resolves the current CSVs through CKAN unless paths are given.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--cafo-path', help='A locally downloaded Confined Animal Facilities CSV')
        parser.add_argument('--enforcement-path', help='A locally downloaded Wastewater Enforcement Actions CSV')

    def handle(self, *args, **options):
        temp = []
        cafo = options['cafo_path']
        enforcement = options['enforcement_path']
        try:
            if cafo is None:
                url = ciwqs.resource_url(ciwqs.CAFO_RESOURCE)
                self.stdout.write(f'Downloading {url}')
                cafo = ciwqs.download(url)
                temp.append(cafo)
            if enforcement is None:
                url = ciwqs.resource_url(ciwqs.ENFORCEMENT_RESOURCE)
                self.stdout.write(f'Downloading {url}')
                enforcement = ciwqs.download(url)
                temp.append(enforcement)
            try:
                cafo_rows = ciwqs.read_cafo(cafo)
                enforcement_rows = ciwqs.read_enforcement(enforcement, ciwqs.place_ids())
            except ciwqs.CIWQSFormatError as err:
                raise CommandError(str(err))
            report = ciwqs.apply(cafo_rows, enforcement_rows)
        finally:
            for path in temp:
                os.unlink(path)
        for line in report.lines():
            self.stdout.write(line)
```

Append to `tasks.py` (create the file with the imports from Task 3 Step 4 if it doesn't exist):

```python
# The Water Board's CKAN resources refresh weekly or monthly. The 3rd at 11:00 UTC.
@db_periodic_task(crontab(day='3', hour='11', minute='0'), priority=20)
def import_ciwqs_dairies():
    with get_queue('primary').lock_task('import-ciwqs-dairies'):
        call_command('import_ciwqs_dairies')
```

- [ ] **Step 7: Run and commit**

Run: `$TEST camp/apps/emissions/tests/test_ciwqs.py camp/apps/emissions/tests/test_dairies.py camp/apps/emissions/tests/test_tasks.py`
Expected: PASS.

```bash
git -C <worktree> add camp/apps/emissions/ciwqs.py camp/apps/emissions/management/commands/import_ciwqs_dairies.py camp/apps/emissions/tests/test_ciwqs.py camp/apps/emissions/tests/data/ciwqs
git -C <worktree> commit -m "feat(dairies): import CIWQS dairy enrollments and enforcement actions, joined on place_id" -- camp/apps/emissions/ciwqs.py camp/apps/emissions/dairies.py camp/apps/emissions/tasks.py camp/apps/emissions/management/commands/import_ciwqs_dairies.py camp/apps/emissions/tests/test_ciwqs.py camp/apps/emissions/tests/test_dairies.py camp/apps/emissions/tests/test_tasks.py camp/apps/emissions/tests/data/ciwqs
```

(`tasks.py` and `test_tasks.py` are `add`ed too if they are new on this branch.)

---

### Task 9: Table column, filter, popup and tile

**Files:**
- Modify: `camp/apps/emissions/dairy_views.py` (`search_filters`, the filter form context)
- Modify: `camp/templates/emissions/includes/dairy-table.html`, `dairy-stats.html`, `dairy-list.html`, `dairy-area.html`
- Modify: `camp/api/v2/emissions/dairies.py` (`DairyDetail`)
- Modify: `assets/js/emissions/dairy-map.js` (`popupHtml`)
- Test: `camp/apps/emissions/tests/test_dairies_pages.py`, `camp/apps/emissions/tests/test_dairy_area_pages.py`, `camp/api/v2/emissions/tests.py`

**Interfaces:**
- `dairy_views.search_filters(get)` → `{'q', 'sort', 'enforcement'}` where `enforcement` is `'5y'` or `None`; passed through to `dairies.table(**filters)` by both the tab and `DairyAreaPage.rows()` (already `**search_filters(...)`).
- Context on the tab and area pages: `enforcement_window = ciwqs.window()` (a `(since, through)` tuple; templates read `enforcement_window.0` / `.1`).
- `DairyDetail` JSON gains `'water_board': {'enrollment': {...} | None, 'actions_5y': n, 'since': 'YYYY-MM-DD' | None, 'through': 'YYYY-MM-DD' | None, 'recent': [{date, action_type, title}] (3 newest), 'url': dairy.ciwqs_url}`.

- [ ] **Step 1: Write the failing tests**

Append to `test_dairies_pages.py`:

```python
class WaterBoardTests(DairyPageTestCase):
    def setUp(self):
        super().setUp()
        from datetime import date
        from camp.apps.emissions.models import DairyEnforcementAction, SourceImport
        DairyEnforcementAction.objects.create(dairy=self.big, enforcement_id=1, date=date(2023, 5, 1), action_type='Notice of Violation', title='Late report')
        DairyEnforcementAction.objects.create(dairy=self.big, enforcement_id=2, date=date(2015, 1, 1), action_type='Notice of Violation', title='Old')
        SourceImport.objects.create(source='ciwqs', data_through=date(2024, 6, 30))
        dairies.clear_caches()

    def test_column_filter_and_tile(self):
        content = self.get({'year': '2023'}).content.decode()
        assert '>Water Board actions</a>' in content
        big_row = content[content.index('BIG DAIRY</a>'):]
        assert '<td class="has-text-right">1</td>' in big_row[:big_row.index('</tr>')]
        assert '<p class="heading">Water Board action since 2019</p><p class="title">1</p>' in content
        assert 'name="enforcement" value="5y"' in content and 'With a Water Board action in the last 5 years' in content
        content = self.get({'year': '2023', 'enforcement': '5y'}).content.decode()
        assert 'BIG DAIRY' in content and 'SMALL DAIRY' not in content and 'checked' in content

    def test_no_import_shows_dashes_and_no_tile(self):
        from camp.apps.emissions.models import DairyEnforcementAction, SourceImport
        SourceImport.objects.all().delete()
        DairyEnforcementAction.objects.all().delete()
        dairies.clear_caches()
        content = self.get({'year': '2023'}).content.decode()
        assert 'Water Board action since' not in content
        assert 'name="enforcement"' not in content
```

Append to `test_dairy_area_pages.py` (`ContentTests`):

```python
    def test_water_board_tile_on_an_area_page(self):
        from datetime import date
        from camp.apps.emissions.models import DairyEnforcementAction, SourceImport
        DairyEnforcementAction.objects.create(dairy=self.big, enforcement_id=1, date=date(2023, 5, 1), action_type='Notice of Violation')
        SourceImport.objects.create(source='ciwqs', data_through=date(2024, 6, 30))
        dairies.clear_caches()
        content = self.get(self.fresno, {'year': '2023'}).content.decode()
        assert '<p class="heading">Water Board action since 2019</p><p class="title">1</p>' in content
        assert self.get(self.fresno, {'year': '2023', 'enforcement': '5y'}).context['summary']['dairies'] == 1
```

Append to `camp/api/v2/emissions/tests.py` `DairyEndpointTests`:

```python
    def test_detail_carries_the_water_board_block(self):
        from datetime import date
        from camp.apps.emissions.models import DairyEnforcementAction, DairyWaterEnrollment, SourceImport
        DairyWaterEnrollment.objects.create(dairy=self.big, reg_measure_id=1, order_number='R5-2013-0122', wdid='5F1', status='Active', cafo_population=1300)
        for n, when in enumerate([date(2023, 5, 1), date(2022, 1, 1), date(2021, 1, 1), date(2020, 1, 1), date(2010, 1, 1)], 1):
            DairyEnforcementAction.objects.create(dairy=self.big, enforcement_id=n, date=when, action_type='Notice of Violation', title=f'NOV {n}')
        SourceImport.objects.create(source='ciwqs', data_through=date(2024, 6, 30))
        dairies.clear_caches()
        block = self.get('dairy-detail', args=[self.big.sqid]).json()['water_board']
        assert block['enrollment'] == {'order_number': 'R5-2013-0122', 'status': 'Active', 'wdid': '5F1', 'cafo_population': 1300}
        assert block['actions_5y'] == 4 and block['since'] == '2019-07-01' and block['through'] == '2024-06-30'
        assert [a['title'] for a in block['recent']] == ['NOV 1', 'NOV 2', 'NOV 3']
        assert block['url'] == self.big.ciwqs_url
        empty = self.get('dairy-detail', args=[self.small.sqid]).json()['water_board']
        assert empty['enrollment'] is None and empty['actions_5y'] == 0 and empty['recent'] == []
```

(Adapt `self.get(...)` to however `DairyEndpointTests` builds its URLs; the class exists from the dairy region pages plan.)

- [ ] **Step 2: Run to verify failure**

Run: `$TEST camp/apps/emissions/tests/test_dairies_pages.py::WaterBoardTests camp/api/v2/emissions/tests.py::DairyEndpointTests`. Expected: FAIL.

- [ ] **Step 3: `dairy_views.py`**

```python
def search_filters(get):
    """The table's own filters, validated: a name search, the sort, and the Water Board enforcement filter."""
    sort = get.get('sort')
    enforcement = get.get('enforcement')
    return {
        'q': (get.get('q') or '').strip() or None,
        'sort': sort if sort in dairies.TABLE_SORTS else dairies.DEFAULT_SORT,
        'enforcement': enforcement if enforcement in dairies.ENFORCEMENT_FILTERS else None,
    }
```

`DairyScopeMixin.get_context_data` adds `'enforcement_window': ciwqs.window()` (import `ciwqs`). `DairyAreaPage.get_context_data` and `DairyList.get_context_data` already pass `filters`; `summary` on the area page must honour the filter for the test above: in `DairyAreaPage.get_context_data`, `summary = dairies.summary(scope.year, area=area, enforcement=filters['enforcement'])` — add an `enforcement=None` kwarg to `dairies.summary()` (and `_where` must include it in the cache key: `_where(county, area, enforcement)` → append `f':{enforcement or "all"}'`) that filters `queryset` with `annotate(actions_5y=_recent_actions()).filter(actions_5y__gt=0)` when set. Apply the same to `DairyList`.

- [ ] **Step 4: Templates**

`dairy-table.html`: after the `Other cattle` column (both `<th>` and `<td>`, and only `{% if not compact %}`):

```django
            {% if not compact %}<th class="has-text-right">{% if sortable %}{% sort_link 'actions_5y' 'Water Board actions' %}{% else %}Water Board actions{% endif %}
                <span class="icon is-small has-text-grey has-tooltip-multiline has-tooltip-bottom has-tooltip-arrow" data-tooltip="Central Valley Regional Water Board enforcement actions under the Dairy General Order in the last 5 years of reporting (water quality, not air)."><span class="fa-regular fa-circle-info" aria-hidden="true"></span></span></th>{% endif %}
```

```django
            {% if not compact %}<td class="has-text-right">{% if herd.actions_5y %}{{ herd.actions_5y }}{% else %}—{% endif %}</td>{% endif %}
```

and `colspan="7"` becomes `colspan="8"`. The comment block gains a line on the column.

`dairy-stats.html`: after the Total cattle tile, before `carb_estimate`:

```django
    {% if enforcement_window.0 %}
    <div class="level-item has-text-centered"><div>
        <p class="heading">Water Board action since {{ enforcement_window.0.year }}</p><p class="title">{{ summary.water_actions|intcomma }}</p>
        <p class="is-size-7 has-text-grey">water quality, not air</p>
    </div></div>
    {% endif %}
```

`dairy-list.html` and `dairy-area.html`, in the filter form after the Search field:

```django
            {% if enforcement_window.0 %}
            <div class="field">
                <label class="checkbox"><input type="checkbox" name="enforcement" value="5y"{% if filters.enforcement %} checked{% endif %}> With a Water Board action in the last 5 years</label>
                <p class="help">Reported through {{ enforcement_window.1|date:"N j, Y" }}. <a href="{% url 'emissions:about' %}#dairy-compliance">What this is</a>.</p>
            </div>
            {% endif %}
```

- [ ] **Step 5: The popup endpoint and JS**

In `camp/api/v2/emissions/dairies.py`, `DairyDetail.get` adds (import `ciwqs`):

```python
        since, through = ciwqs.window()
        actions = dairy.enforcement_actions.order_by('-date', '-pk')
        recent_count = actions.filter(date__gte=since, date__lte=through).count() if since else 0
        enrollment = dairy.water_enrollments.order_by('-effective_date', '-pk').filter(status__iexact='active').first() \
            or dairy.water_enrollments.order_by('-effective_date', '-pk').first()
        water_board = {
            'enrollment': None if enrollment is None else {
                'order_number': enrollment.order_number, 'status': enrollment.status,
                'wdid': enrollment.wdid, 'cafo_population': enrollment.cafo_population,
            },
            'actions_5y': recent_count,
            'since': since.isoformat() if since else None,
            'through': through.isoformat() if through else None,
            'recent': [{'date': a.date.isoformat(), 'action_type': a.action_type, 'title': a.title} for a in actions[:3]],
            'url': dairy.ciwqs_url,
        }
```

and `'water_board': water_board` in the returned dict.

In `dairy-map.js` `popupHtml`, before the `Counted in` block:

```js
    var wb = data.water_board;
    if (wb && (wb.enrollment || wb.recent.length)) {
      var lines = [];
      if (wb.enrollment) {
        lines.push('Water Board order ' + escapeHtml(wb.enrollment.order_number || '') + ' (' + escapeHtml(wb.enrollment.status || '') + ')' +
          (wb.enrollment.wdid ? ', WDID ' + escapeHtml(wb.enrollment.wdid) : '') +
          (wb.enrollment.cafo_population !== null ? ', reported herd ' + whole(wb.enrollment.cafo_population) : ''));
      }
      if (wb.since) lines.push(wb.actions_5y + ' Water Board action' + (wb.actions_5y === 1 ? '' : 's') + ' since ' + escapeHtml(wb.since.slice(0, 4)));
      wb.recent.forEach(function (a) {
        lines.push(escapeHtml(a.date) + ' · ' + escapeHtml(a.action_type) + (a.title ? ': ' + escapeHtml(a.title) : ''));
      });
      lines.push('<a href="' + escapeHtml(wb.url) + '">Record at CIWQS →</a>' + (wb.through ? ' <span class="has-text-grey">· reported through ' + escapeHtml(wb.through) + '</span>' : ''));
      parts.push('<div class="dairy-popup-water is-size-7"><p>' + lines.join('<br>') + '</p></div>');
    }
```

Update the `popupHtml` comment to mention the Water Board block. Run `node --check assets/js/emissions/dairy-map.js`, then the asset rebuild.

- [ ] **Step 6: Run the tests, check the browser**

Run: `$TEST camp/apps/emissions/tests/test_dairies_pages.py camp/apps/emissions/tests/test_dairy_area_pages.py camp/apps/emissions/tests/test_dairies.py camp/api/v2/emissions/tests.py`
Expected: PASS.

If the dev DB has CADD data, run `import_ciwqs_dairies` in the :8003 container and open `/tools/emissions/dairies/?county=tulare`: the column, the checkbox, the tile; click a dairy: the popup's Water Board lines and the CIWQS link.

- [ ] **Step 7: Commit**

```bash
git -C <worktree> commit -m "feat(dairies): Water Board actions in the dairy table, popup and headline" -- camp/apps/emissions/dairy_views.py camp/apps/emissions/dairies.py camp/templates/emissions/includes/dairy-table.html camp/templates/emissions/includes/dairy-stats.html camp/templates/emissions/dairy-list.html camp/templates/emissions/dairy-area.html camp/api/v2/emissions/dairies.py assets/js/emissions/dairy-map.js camp/apps/emissions/tests/test_dairies_pages.py camp/apps/emissions/tests/test_dairy_area_pages.py camp/api/v2/emissions/tests.py
```

---

### Task 10: About, integrations, full run

**Files:**
- Modify: `camp/templates/emissions/about.html`, `datafiles/data-integrations.yaml`, `camp/apps/emissions/views.py` (`About`)
- Test: `camp/apps/emissions/tests/test_dairies_pages.py` (`AboutDairiesTests`, append)

- [ ] **Step 1: Test**

```python
    def test_about_dairy_compliance_and_integrations(self):
        from datetime import date
        from camp.apps.emissions.models import SourceImport
        content = self.client.get(reverse('emissions:about')).content.decode()
        assert '<h2 id="dairy-compliance">Dairy compliance</h2>' in content
        assert 'not air violations' in content and 'No Water Board data has been imported yet.' in content
        SourceImport.objects.create(source='ciwqs', data_through=date(2024, 6, 30))
        assert 'Reported through June 30, 2024.' in self.client.get(reverse('emissions:about')).content.decode()
        assert 'CIWQS' in self.client.get('/about/integrations/').content.decode()
```

- [ ] **Step 2: Copy**

`About.get_context_data` adds `ciwqs_stamp=SourceImport.latest('ciwqs')` (import `SourceImport`). In `about.html`, after the Dairies list, before `<h2 id="sources">` (or before the Compliance section if Part A is on the branch):

```django
<h2 id="dairy-compliance">Dairy compliance</h2>
<p>These are water-quality actions by the Central Valley Regional Water Board under the Dairy General Order (manure, lagoons, groundwater), not air violations. Air-district dairy permit compliance isn't public. A notice of violation is an allegation; many concern paperwork such as a late annual report. {% if ciwqs_stamp and ciwqs_stamp.data_through %}Reported through {{ ciwqs_stamp.data_through|date:"F j, Y" }}.{% else %}No Water Board data has been imported yet.{% endif %}</p>
<p>Each dairy's Water Board record (its enrollment, reported herd and enforcement actions) comes from the State Water Board's CIWQS through data.ca.gov, joined to CARB's dairy database on the shared facility id (1,506 of 1,558 Valley dairies). "Last 5 years" is measured back from the newest action in the file, not from today.</p>
```

Sources list gains `<li><a href="https://data.ca.gov/dataset/surface-water-water-quality-regulated-facility-information">State Water Board CIWQS (data.ca.gov)</a></li>`. In `data-integrations.yaml` under Emissions Data:

```yaml
    - name: CIWQS (State Water Board)
      logo: img/logo/ca-open-data.png
      url: https://data.ca.gov/dataset/surface-water-water-quality-regulated-facility-information
      description: The State Water Resources Control Board's California Integrated Water Quality System lists every dairy enrolled under the Central Valley Water Board's Dairy General Order and the Board's enforcement actions at each. SJVAir joins those records to CARB's dairy database and shows each dairy's Water Board record — water quality, not air — beside its herd.
```

- [ ] **Step 3: Full run, smoke, PR notes**

Run: `$TEST camp/apps/emissions camp/api/v2/emissions camp/apps/regions`. Expected: PASS.
Run the smoke script (the dairy popup and table changed; `no console errors` must PASS).

PR description: the join (place_id, 1,506/1,558), what the column/filter/tile/popup show, the caveat paragraph, Deploy: `migrate`; one-off `python manage.py import_ciwqs_dairies` (a 46 MB CSV; a minute or two); the monthly task registers on the next `huey_primary` restart.

```bash
git -C <worktree> commit -m "docs(dairies): About and integrations entries for the Water Board data" -- camp/templates/emissions/about.html datafiles/data-integrations.yaml camp/apps/emissions/views.py camp/apps/emissions/tests/test_dairies_pages.py
```

---

## Self-review

- **Spec coverage, Phase 4.** Models with the spec's fields (Task 1; `pollutant_class` free text, refinement 3); the six files, Valley filter, `PGM_SYS_ID` join with the FIPS→CARB map, EKAPCD/R9 via the empty crosswalk, delete+bulk_create per import in one transaction, `SourceImport('icis-air', data_through=max event date)` (Task 2); `--path`, monthly `db_periodic_task(crontab(day='2', hour='11', minute='0'))` under `lock_task('import-icis-air')` (Task 3); card badges, five-year line, 25-row table with Show all, ECHO link, stamp, nothing without a match; list filters `compliance=hpv|any`; region/county line linking the filtered list; About section and integrations entry (Tasks 4–5); the tests the spec lists (Valley filter, the three ids, S/C/N, EKAPCD unmatched, idempotent re-run, `reported_through`, `SourceImport`, rollups, card and absence, list filters, region line, task under lock).
- **Spec coverage, Phase 6.** Models (Task 7); CAFO region 5 + enforcement filtered to CADD place_ids, upsert-by-replace, `SourceImport('ciwqs')`, monthly task `crontab(day='3', hour='11')` (Task 8); table column, `?enforcement=5y` filter, popup block with enrollment, three actions, count, CIWQS link and stamp, the dairy area page tile (Task 9); About paragraph and integrations (Task 10); the tests the spec lists (place_id join, unmatched ignored, idempotent replace, the boundary date, column and filter, popup fields, tile).
- **Placeholders.** `SAMPLE_PLACE_IDS = [...]` and the migration number `000N` are filled at implementation time from the real files; every other step carries its code. `[...]` in the crosswalk test is a real `patch.dict`.
- **Type consistency.** `compliance.facility_card()` keys (`primary`, `since`, `inspections`, `novs`, `formals`, `penalties`, `shown`, `more`, `names`, `reported_through`) match the card template; `area_summary()` keys plus `url` match `area.html`; `dairies.table(enforcement=)` / `summary(enforcement=)` match `search_filters()`'s key and `DairyAreaPage`; `ciwqs.window()` returns a 2-tuple read as `enforcement_window.0/.1` in templates and unpacked in the API; `actions_5y` is the annotation, the sort key and the template attribute.
- **Review Focus.** Each line names its test and task above.
