# Emissions Phase 1: Toxics in Long Format, Weighted — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store every toxic air contaminant CARB reports per facility and year in a long table (`ToxicEmission`) instead of ten fixed columns, weight each pollutant with the CARB/OEHHA Consolidated Table's potency values the way CARB's own Pollution Mapping Tool does, make "Cancer-weighted (relative)" the default toxics view everywhere (map, list, sectors, region pages, near-me, home), give the facility page the full toxics table and a Hot Spots (AB 2588) card, and add the `SourceImport` stamp model every later phase uses. Ammonia (CARB id 7664417) is stored as `kind='precursor'` so Phase 5 can show it; this phase never lists it among toxics.

**Architecture:**
- **Models.** `SourceImport` (one row per finished import, `latest(source)`), `ToxicPollutant` (one row per CARB pollutant id: a CAS without dashes or a 4-digit CARB code; health values and the three derived weights), `ToxicEmission` (facility × year × pollutant → lbs). Three migrations: create + verbose-name fixes, a data migration copying the ten named columns into `ToxicEmission` behind ten placeholder pollutants, then drop the ten columns. `EmissionsRecord` keeps `total_score`, `hra`, `chindex`, `ahindex`.
- **Measures.** `pollutants.Pollutant` grows `weight_field` (the two weighted measures) and `pollutant_id` (one toxic). Its `unit` is `'tons'`, `'lbs'` or `'share'`. Every aggregate in `stats.py` reads one `value` expression (`stats.value_expr`): the criteria column, a correlated subquery on `ToxicEmission` for one toxic, or Σ lbs × weight for a weighted measure. Weighted values are always shown as a **share of the Valley's total for that year** (`stats.scale()` divides by `stats.valley_totals()`), never the raw number. `areas.area_values` and the facility GeoJSON get the new measures through `stats.values(scope)` with no page-specific code.
- **Imports.** `contable.py` parses the Consolidated Table PDF (pdfplumber); `import_health_values` upserts `ToxicPollutant` and recomputes weights; `import_toxics --year` crawls CARB's per-facility `facdet_output.csv` with a thread pool and replaces each facility's rows for the year, county by county in transactions. Both write a `SourceImport` row and bump the explorer cache generation. `import_ceidars` no longer fetches the ten per-pollutant `showpol` CSVs.
- **Pages.** The toxics picker lists Cancer-weighted, Hazard-weighted, then every toxic with Valley pounds in the scope year (by cancer share). Old picker keys (`?toxics=1&pollutant=benzene`) 301 to the slug. The home and area pages get a "What drives it" cancer-weighted breakdown bar; the facility page gets the full toxics table, the Hot Spots card and the caveat panel; the About page a "Toxicity-weighted emissions" section. The map handles a `share` unit (percent classes, legend title, disabled density/per-resident measures).

**Tech Stack:** Django 5.2 / GeoDjango + PostGIS, django-vanilla-views, django-resticus (`CachedEndpointMixin`), pandas + requests (CARB CSVs, existing `ceidars.fetch_csv`), pdfplumber 0.11 (already in `requirements/base.txt`), `concurrent.futures.ThreadPoolExecutor`, MapTiler SDK on the map core (`window.SJVAirMaps`), Bulma + bulma-tooltip, Selenium smoke script.

**Spec:** `docs/superpowers/specs/2026-09-28-emissions-data-expansion-design.md` — read "Shared: SourceImport", "Data model summary" and all of "Phase 1" before any task. Research: `.superpowers/research/toxics.md`.

## Global Constraints

- **Where to work.** Worktree `/home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer` (`<worktree>` below), on a **new branch stacked on `feature/ceidars-explorer`** after the dairy region pages plan (`docs/superpowers/plans/2026-09-28-dairy-region-pages.md`) has landed: `git -C <worktree> switch -c feature/emissions-toxics-weighted feature/ceidars-explorer`. Use absolute paths and `git -C <worktree>` for every git command. Never edit or commit in `/home/derek/dev/ccac/sjvair.com` (the main checkout) or any other worktree. After each commit, verify it with `git -C <worktree> log --oneline -1`.
- **Plan against the post-dairy-pages code.** That plan changes `views.py` (`dairy_block`, `AreaPage.dairy_url`, `RegionLookupMixin`, `NearLookupMixin`, `find_area_places(url_name)`), `area.html` (its Dairies block becomes `includes/dairy-summary.html`) and `dairy_views.py`. Line numbers quoted here are from before it landed; find the code by name. This plan does not touch anything dairy.
- **Tests** use `django.test.TestCase` with plain `assert` (never `self.assertX`); fixtures `regions.yaml`, `emissions.yaml`; `pytest.raises` for exceptions. Tests never hit the network: every fetch is mocked (`patch('requests.get', ...)`, as `camp/apps/emissions/tests/test_import_ceidars.py` does) and every sample file is a small checked-in file under `camp/apps/emissions/tests/data/`.
- **New models use sqids:** `sqid = SqidsField(alphabet=shuffle_alphabet('emissions.<ModelName>'))` beside the integer PK, as `camp/apps/emissions/models.py` does. Verbose names use `_()` as the first positional argument; don't align `=`.
- **Test command** (`$TEST <paths>` below):
  `docker compose -f /home/derek/dev/ccac/sjvair.com/docker-compose.yml --project-directory /home/derek/dev/ccac/sjvair.com run --rm -T -e DATABASE_URL=postgis://sjvair:changeme@db:5432/sjvair_toxics -v /home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer:/app test pytest <paths> -q -p no:cacheprovider --create-db`
  `fatal: not a git repository` in its output is harmless.
- **Management commands against the worktree** (`$MANAGE <args>` below; migrations, `makemigrations`, one-off checks):
  `docker compose -f /home/derek/dev/ccac/sjvair.com/docker-compose.yml --project-directory /home/derek/dev/ccac/sjvair.com run --rm -T -v /home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer:/app web python manage.py <args>`
- **Asset rebuild:** the same prefix as `$MANAGE` but the command is `invoke vendor bundle styles`. Run `node --check` on every JS file touched.
- **Smoke:** `/home/derek/.claude/jobs/d44a9b36/tmp/venv/bin/python scripts/emissions_map_smoke.py --base http://localhost:8003`. The dev server's container is `docker ps --filter publish=8003`; never stop it. It serves this worktree; after Task 1 it needs `migrate` (`docker exec $(docker ps --filter publish=8003 --format '{{.Names}}') python manage.py migrate`), after Task 2 `import_health_values --path /app/.superpowers/contable.pdf`, and for a full smoke `import_toxics --year 2024` (about ten minutes; run it in the background while doing Tasks 4–6).
- **Real sample files.** The research agent left the real Consolidated Table at `/tmp/claude-1000/-home-derek-dev-ccac-sjvair-com/d44a9b36-1d95-48d8-9dc1-7d9a1cd0932f/scratchpad/contable.pdf` (19 pages, "last updated: December 17, 2024"). Copy it to `<worktree>/.superpowers/contable.pdf` (the `.superpowers/` directory is untracked; never `git add` it) so the containers see it at `/app/.superpowers/contable.pdf`. If it is gone, download `https://ww2.arb.ca.gov/sites/default/files/classic/toxics/healthval/contable.pdf` (the host often 503s; retry).
- **Commits:** explicit paths only (`git -C <worktree> add <new files>`, then `git -C <worktree> commit -m "…" -- <every path>`). Never `git add -A`, never `git stash`, never push, no AI attribution or Co-Authored-By trailers. Message style: `feat(emissions): …`, `refactor(emissions): …`, `test(emissions): …`.
- **Deploy notes go in the PR description, not CLAUDE.md.** Task 7 drafts them.
- **Copy, verbatim from the spec** (Phase 1 "What appears where" and "Caveat copy"). Hot Spots card: "High priority above 10"; "public notification at 10, risk reduction required at 100"; for the hazard indices, "1.0 is the reference level" **without** claiming it is district policy (the brief's ruling: the copy says a hazard index above 1, and does not attribute a notification level to SJVAPCD). Areas tooltip: "Weighted toxics are shown as a share of the Valley total, not per square mile."
- **Wording decisions made while planning** (the spec is otherwise followed as written):
  1. The two weighted measures' picker labels are `Cancer-weighted` and `Hazard-weighted`, with the grey names `Cancer-weighted toxics (relative)` and `Non-cancer hazard-weighted toxics (relative)`; the map legend reads "Share of Valley cancer-weighted toxics, 2024" / "Share of Valley hazard-weighted toxics, 2024" by building `'Share of Valley ' + label.toLowerCase() + ' toxics, ' + year`. Picker keys stay `cancer` and `chronic` as the spec says.
  2. Share classes are four breaks (five classes): 0.01%, 0.1%, 1%, 5% ("5% and up"). The spec's fifth break (20%) would need a sixth ramp colour the map core samples at five; one top class above 5% is enough.
  3. The **Valley total** a share is of is every facility's weighted toxics that year, all eight counties, **minor sources included** (the auto-body shops hold much of the PCBTF weight). So a share on a facility page, a popup and a table all agree whatever the scope toggles are, and the home page's headline tile for a weighted measure ("Share of the Valley's cancer-weighted toxics") reads under 100% with minor sources off — that is informative, not a bug.
  4. `ToxicPollutant.slug` is set once, when the row is created, and never rewritten, so URLs are stable. `import_health_values` may rename a pollutant (the table's name, sentence-cased, with a few overrides such as `Diesel PM`); `import_toxics` names a pollutant only when it creates it.
  5. The Consolidated Table lists both PAH codes (`1150`, `1151`) on one row with benzo(a)pyrene's values, so 1151 gets its IUR from the table directly; `contable.IUR_FALLBACKS = {'1151': '50328'}` is kept as a safety net applied only when 1151 has no IUR. 1150 is `weighted=False` (double counting).

## Review Focus

- **The data migration copies exactly the ten columns and nothing else** (`test_toxics_migration.py`, Task 1): every non-null named-toxic value becomes one `ToxicEmission` row under the right placeholder pollutant; nulls create nothing; `EmissionsRecord` counts and the four Hot Spots fields are unchanged; re-running is impossible to double (unique key).
- **A weighted value is never displayed raw.** `stats.values()`, `totals()['value']`, `facility_table().value`, `area_values`, the GeoJSON `value` and `facility_toxics()['share']` are shares (0–1) for `unit == 'share'`. Pinned by `test_weighted_values_are_shares_that_sum_to_one` (Task 4) and the Guardian regression test (Task 3, which reads the raw total only through `stats.valley_totals`).
- **Ammonia never appears among toxics**: not in the picker, not in the breakdown bar, not in the facility toxics table, not in a weighted total (`kind='precursor'`, weights 0). Pinned by `test_precursor_is_not_a_toxic` (Task 4) and `test_ammonia_row_is_not_in_the_toxics_table` (Task 5).
- **Old links keep working**: `?toxics=1&pollutant=benzene` 301s to `?toxics=1&pollutant=<slug>` on every page, and the API endpoints resolve the old key without redirecting. Pinned by `test_legacy_toxic_key_redirects` (Task 5) and `test_legacy_key_resolves` (Task 4).
- **The Areas view for a weighted measure** forces `measure=total`, renders density / per-resident as disabled with the tooltip, and the JS never sends `measure=density` for it (`test_share_measures_are_disabled`, Task 5; smoke, Task 7).
- **`import_toxics` failure isolation**: one failed facility fetch is reported and skipped; the county's other rows still land; that facility's existing rows are kept, not deleted (`test_a_failed_facility_is_skipped_and_the_rest_land`, Task 3).

---

### Task 1: Models, migrations, fixture, admin, and the end of the ten columns

**Files:**
- Modify: `camp/apps/emissions/models.py` (imports at top; after `EmissionsRecord`, before `CountyInventory`)
- Create: `camp/apps/emissions/migrations/0007_toxics_long_format.py` (generated), `camp/apps/emissions/migrations/0008_copy_named_toxics.py` (hand-written), `camp/apps/emissions/migrations/0009_drop_named_toxics.py` (generated)
- Modify: `camp/apps/emissions/ceidars.py` (remove `TOXIC_POLLUTANTS`, the `showpol` branch of `csv_url`, and the per-pollutant loop in `fetch_county`; add `AIR_BASINS`, `facdet_url`)
- Modify: `camp/apps/emissions/management/commands/import_ceidars.py` (`fetch_county` now returns one frame; drop `toxic_ems`)
- Modify: `camp/apps/emissions/admin.py`
- Modify: `fixtures/emissions.yaml`
- Modify: `camp/apps/emissions/tests/test_import_ceidars.py`, `camp/apps/emissions/tests/test_models.py`
- Create: `camp/apps/emissions/tests/test_toxics_migration.py`

**Interfaces:**
- Produces (all in `camp.apps.emissions.models`):
  - `SourceImport(source, imported_at, data_through, version, notes)`, `SourceImport.latest(source) -> SourceImport | None`.
  - `ToxicPollutant(carb_id, cas_number, name, slug, kind, iur, chronic_rel, acute_rel, mwaf, weighted, cancer_weight, chronic_weight, acute_weight, health_values_date)`, `ToxicPollutant.Kind.TOXIC / PRECURSOR`, `ToxicPollutant.set_weights()`, `ToxicPollutant.cas_from_carb_id(carb_id) -> str`, `ToxicPollutant.unique_slug(name, carb_id) -> str`, `ToxicPollutant.create_for(carb_id, name) -> ToxicPollutant`; constants `CANCER_SCALE = 7700.0`, `CHRONIC_SCALE = 0.01712`, `ACUTE_SCALE = 0.1712`, `PRECURSOR_IDS = frozenset({'7664417'})`, `UNWEIGHTED_IDS = frozenset({'1150'})`, `RESERVED_SLUGS = frozenset({'cancer', 'chronic'})`.
  - `ToxicEmission(facility, year, pollutant, lbs)` with `Facility.toxic_emissions` and `ToxicPollutant.emissions` reverse names.
  - `ceidars.AIR_BASINS = {'SJU': 'SJV', 'KER': 'MD'}`, `ceidars.facdet_url(year, county_code, district_code, facid) -> str`, `ceidars.fetch_county(year, county_code) -> DataFrame`.
- Consumed by: every later task.

- [ ] **Step 1: Add the models (keep the ten columns for now)**

In `camp/apps/emissions/models.py`, fix the two verbose names on `EmissionsRecord` (the spec's correction):

```python
    chindex = models.DecimalField(_('Chronic hazard index'), max_digits=10, decimal_places=2, null=True, blank=True)
    ahindex = models.DecimalField(_('Acute hazard index'), max_digits=10, decimal_places=2, null=True, blank=True)
```

Leave the ten named-toxic fields in place for this step. Then add, after `EmissionsRecord` and before `CountyInventory`:

```python
class SourceImport(models.Model):
    """
    One finished run of an external-source import (the Consolidated Table,
    the CEIDARS toxics crawl, later ICIS-Air and the rest): when it ran, what
    it covered. Templates read the newest row per source for their "as of"
    stamps; nothing else depends on it.
    """

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.SourceImport'))
    source = models.CharField(_('Source'), max_length=32, db_index=True)
    imported_at = models.DateTimeField(_('Imported at'), auto_now_add=True)
    data_through = models.DateField(_('Data through'), null=True, blank=True)
    version = models.CharField(_('Version'), max_length=64, blank=True)
    notes = models.JSONField(_('Notes'), default=dict, blank=True)

    class Meta:
        ordering = ['-imported_at', '-pk']

    def __str__(self):
        return f'{self.source} ({self.imported_at:%Y-%m-%d})'

    @classmethod
    def latest(cls, source):
        return cls.objects.filter(source=source).order_by('-imported_at', '-pk').first()


# CARB's toxicity weighting, reverse-engineered from its Pollution Mapping
# Tool and reproduced to within 0.01% on 91 carcinogens (research:
# .superpowers/research/toxics.md, section 2). Cancer weight per pound is
# the inhalation unit risk × the molecular-weight adjustment factor × 7,700;
# chronic and acute weights are a constant over the reference exposure level.
CANCER_SCALE = 7700.0
CHRONIC_SCALE = 0.01712
ACUTE_SCALE = 0.1712
# Ammonia: CARB delivers it in the toxics feed, but it's a PM2.5 precursor,
# not a toxic; stored under kind='precursor', never weighted or listed as one.
PRECURSOR_IDS = frozenset({'7664417'})
# "PAHs, total, with individual components also reported" -- weighting it
# would count the components twice.
UNWEIGHTED_IDS = frozenset({'1150'})
# The toxics picker's own keys; a pollutant slug can't be one of them.
RESERVED_SLUGS = frozenset({'cancer', 'chronic'})


class ToxicPollutant(models.Model):
    """
    A pollutant in CARB's toxics inventory: a CAS number without dashes
    ('71432', benzene) or one of CARB's own 4-digit codes ('9901', diesel
    PM), with the OEHHA health values from the Consolidated Table and the
    per-pound weights derived from them. Rows exist for every table entry
    and for every id a facility has reported, whether or not both.
    """

    class Kind(models.TextChoices):
        TOXIC = 'toxic', _('Toxic air contaminant')
        PRECURSOR = 'precursor', _('Precursor')

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.ToxicPollutant'))
    carb_id = models.CharField(_('CARB pollutant ID'), max_length=12, unique=True)
    cas_number = models.CharField(_('CAS number'), max_length=16, blank=True)
    name = models.CharField(_('Name'), max_length=128)
    # For URLs (?pollutant=diesel-pm). Set when the row is created, never
    # rewritten, so links stay good when a name is corrected.
    slug = models.SlugField(_('Slug'), max_length=140, unique=True)
    kind = models.CharField(_('Kind'), max_length=12, choices=Kind.choices, default=Kind.TOXIC, db_index=True)
    # OEHHA values as the Consolidated Table gives them.
    iur = models.FloatField(_('Inhalation unit risk (µg/m³)⁻¹'), null=True, blank=True)
    chronic_rel = models.FloatField(_('Chronic REL (µg/m³)'), null=True, blank=True)
    acute_rel = models.FloatField(_('Acute REL (µg/m³)'), null=True, blank=True)
    mwaf = models.FloatField(_('Molecular weight adjustment factor'), default=1.0)
    weighted = models.BooleanField(_('Weighted'), default=True)
    # Derived by set_weights(); 0 where there's no value to derive from.
    cancer_weight = models.FloatField(_('Cancer weight per lb'), default=0.0)
    chronic_weight = models.FloatField(_('Chronic hazard weight per lb'), default=0.0)
    acute_weight = models.FloatField(_('Acute hazard weight per lb'), default=0.0)
    health_values_date = models.DateField(_('Health values date'), null=True, blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.carb_id})'

    def set_weights(self):
        """Recompute the three weights from the health values; a precursor or an unweighted id gets none."""
        if self.kind != self.Kind.TOXIC:
            self.cancer_weight = self.chronic_weight = self.acute_weight = 0.0
            return
        self.cancer_weight = self.iur * self.mwaf * CANCER_SCALE if self.weighted and self.iur else 0.0
        self.chronic_weight = CHRONIC_SCALE / self.chronic_rel if self.chronic_rel else 0.0
        self.acute_weight = ACUTE_SCALE / self.acute_rel if self.acute_rel else 0.0

    @staticmethod
    def cas_from_carb_id(carb_id):
        """'71432' -> '71-43-2'; '' for a 4-digit CARB code (a CAS has at least five digits)."""
        carb_id = str(carb_id).strip()
        if len(carb_id) <= 4 or not carb_id.isdigit():
            return ''
        return f'{carb_id[:-3]}-{carb_id[-3:-1]}-{carb_id[-1]}'

    @classmethod
    def unique_slug(cls, name, carb_id):
        """slugify(name), with the CARB id appended when that's taken or reserved."""
        base = slugify(name) or f'pollutant-{carb_id}'
        if base in RESERVED_SLUGS or cls.objects.filter(slug=base).exists():
            return f'{base}-{carb_id}'
        return base

    @classmethod
    def create_for(cls, carb_id, name):
        """A new row for a CARB id first seen in a facility's CSV: no health values yet."""
        carb_id = str(carb_id).strip()
        return cls.objects.create(
            carb_id=carb_id,
            cas_number=cls.cas_from_carb_id(carb_id),
            name=name,
            slug=cls.unique_slug(name, carb_id),
            kind=cls.Kind.PRECURSOR if carb_id in PRECURSOR_IDS else cls.Kind.TOXIC,
        )


class ToxicEmission(models.Model):
    """One facility's reported pounds of one toxic pollutant in one inventory year (CARB's facdet CSV, EMISSIONS_LBS_YR)."""

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.ToxicEmission'))
    facility = models.ForeignKey(Facility, verbose_name=_('Facility'), on_delete=models.CASCADE, related_name='toxic_emissions')
    year = models.IntegerField(_('Year'))
    pollutant = models.ForeignKey(ToxicPollutant, verbose_name=_('Pollutant'), on_delete=models.PROTECT, related_name='emissions')
    lbs = models.DecimalField(_('Emissions (lbs/yr)'), max_digits=25, decimal_places=15)

    class Meta:
        unique_together = [('facility', 'year', 'pollutant')]
        indexes = [
            models.Index(fields=['year', 'pollutant']),
            models.Index(fields=['pollutant', 'year']),
        ]

    def __str__(self):
        return f'{self.facility.name} {self.pollutant.name} ({self.year})'
```

`slugify` is already imported at the top of the module.

- [ ] **Step 2: Generate migration 0007**

```
$MANAGE makemigrations emissions -n toxics_long_format
```

Open `camp/apps/emissions/migrations/0007_toxics_long_format.py` and confirm it contains exactly: `CreateModel` for `SourceImport`, `ToxicPollutant`, `ToxicEmission` (with the two indexes and the unique constraint), and two `AlterField`s for `chindex` / `ahindex`. It must **not** contain any `RemoveField`. If it does, you removed the columns too early; restore them and regenerate.

- [ ] **Step 3: Write the data migration 0008**

Create `camp/apps/emissions/migrations/0008_copy_named_toxics.py`:

```python
"""
Copy the ten named toxic air contaminant columns of EmissionsRecord into the
long ToxicEmission table, behind ten placeholder ToxicPollutant rows (CARB id
and a curated name; no health values -- import_health_values adds them).
About 130k records; under a minute. Reverse is a no-op: 0009's reverse
re-adds the empty columns, and the ToxicEmission rows stay.
"""
from django.db import migrations
from django.utils.text import slugify

# EmissionsRecord field -> (CARB pollutant id, display name). The ids are the
# undashed CAS numbers import_ceidars used to request each column.
NAMED_TOXICS = {
    'acetaldehyde': ('75070', 'Acetaldehyde'),
    'benzene': ('71432', 'Benzene'),
    'butadiene': ('106990', '1,3-Butadiene'),
    'carbon_tetrachloride': ('56235', 'Carbon tetrachloride'),
    'chromium_hexavalent': ('18540299', 'Hexavalent chromium'),
    'dichlorobenzene': ('106467', 'para-Dichlorobenzene'),
    'formaldehyde': ('50000', 'Formaldehyde'),
    'methylene_chloride': ('75092', 'Methylene chloride'),
    'naphthalene': ('91203', 'Naphthalene'),
    'perchloroethylene': ('127184', 'Perchloroethylene'),
}
BATCH = 5000


def cas_number(carb_id):
    return f'{carb_id[:-3]}-{carb_id[-3:-1]}-{carb_id[-1]}'


def copy_named_toxics(apps, schema_editor):
    ToxicPollutant = apps.get_model('emissions', 'ToxicPollutant')
    ToxicEmission = apps.get_model('emissions', 'ToxicEmission')
    EmissionsRecord = apps.get_model('emissions', 'EmissionsRecord')

    pollutants = {}
    for field, (carb_id, name) in NAMED_TOXICS.items():
        pollutants[field], _ = ToxicPollutant.objects.get_or_create(
            carb_id=carb_id,
            defaults={'cas_number': cas_number(carb_id), 'name': name, 'slug': slugify(name), 'kind': 'toxic'},
        )

    fields = list(NAMED_TOXICS)
    batch = []
    rows = EmissionsRecord.objects.order_by('pk').values('facility_id', 'year', *fields).iterator(chunk_size=BATCH)
    for row in rows:
        for field in fields:
            if row[field] is None:
                continue
            batch.append(ToxicEmission(
                facility_id=row['facility_id'], year=row['year'], pollutant=pollutants[field], lbs=row[field],
            ))
        if len(batch) >= BATCH:
            ToxicEmission.objects.bulk_create(batch, ignore_conflicts=True)
            batch = []
    if batch:
        ToxicEmission.objects.bulk_create(batch, ignore_conflicts=True)


class Migration(migrations.Migration):

    dependencies = [
        ('emissions', '0007_toxics_long_format'),
    ]

    operations = [
        migrations.RunPython(copy_named_toxics, migrations.RunPython.noop),
    ]
```

- [ ] **Step 4: Drop the ten columns and generate 0009**

In `models.py`, delete the block from the comment `# Named toxic air contaminants (lbs/yr, ...)` through the `perchloroethylene` field on `EmissionsRecord`, and change its docstring to:

```python
    """
    One facility's CEIDARS emissions for one inventory year: criteria
    pollutants in tons/yr and the AB 2588 Hot Spots summary fields. Its
    toxic air contaminants are ToxicEmission rows.
    """
```

Then:

```
$MANAGE makemigrations emissions -n drop_named_toxics
```

Confirm `0009_drop_named_toxics.py` has exactly ten `RemoveField`s on `emissionsrecord` and depends on `0008_copy_named_toxics`.

- [ ] **Step 5: Retire the per-pollutant CEIDARS fetch**

In `camp/apps/emissions/ceidars.py`:
- Delete `TOXIC_POLLUTANTS` and its comment.
- Replace `csv_url` and add the facdet URL:

```python
# CARB's DIS code -> the air basin its facilities are in (the facdet CSV's
# ab_ parameter is required; Kern's two districts sit in two basins).
AIR_BASINS = {'SJU': 'SJV', 'KER': 'MD'}


def csv_url(kind, year, county_code):
    """kind is 'faccrit' (criteria) or 'factox' (the Hot Spots summary columns)."""
    return f'{BASE_URL}/{kind}_output.csv?dbyr={year}&co_={county_code}'


def facdet_url(year, county_code, district_code, facid):
    """
    One facility's toxics for one year: every pollutant it reported, with
    CARB's pollutant id and pounds per year (columns FACID, CO, AB, DIS,
    POLLUTANT_ID, POLLUTANT, EMISSIONS_LBS_YR). Exhaustive where the
    per-pollutant `showpol` sweep could miss an id.
    """
    basin = AIR_BASINS[district_code]
    return (
        f'{BASE_URL}/facdet_output.csv?&dbyr={year}&ab_={basin}&dis_={district_code}'
        f'&co_={county_code}&sort=T&facid_={facid}'
    )
```

- Rewrite `fetch_county` to return only the merged frame (drop the `on_error` parameter, the `toxic_ems` dict and the per-pollutant loop):

```python
def fetch_county(year, county_code):
    """
    One county and year: the criteria and Hot Spots-summary CSVs outer-joined
    on the facility columns (an empty DataFrame when CARB has nothing).
    Raises requests.RequestException if either request fails. Per-pollutant
    toxics are not here: import_toxics crawls facdet_url() per facility.
    """
    criteria = fetch_csv(csv_url('faccrit', year, county_code))
    toxics = fetch_csv(csv_url('factox', year, county_code))
    frames = [frame for frame in (criteria, toxics) if not frame.empty]
    if not frames:
        return pd.DataFrame()
    if len(frames) == 1:
        return frames[0]
    return pd.merge(criteria, toxics, on=MERGE_KEYS, how='outer', suffixes=('_crit', '_tox')).fillna('')
```

Update the module docstring's last sentence to say rows are identified by `(DIS, FACID)` and that toxics come from `facdet_url`.

In `import_ceidars.py`: change the fetch to `merged = ceidars.fetch_county(year, county_code)` (no `on_error`), and delete the line `emissions_data.update(toxic_ems.get(key, {}))`. Nothing else changes.

- [ ] **Step 6: Admin**

In `camp/apps/emissions/admin.py`:
- Import `SourceImport, ToxicEmission, ToxicPollutant` from `.models`.
- In `EmissionsRecordInline.ALL_FIELDS`, delete the ten named-toxic entries (keep `year`, the seven criteria, and the four Hot Spots fields).
- Add:

```python
class ToxicEmissionInline(admin.TabularInline):
    model = ToxicEmission
    extra = 0
    can_delete = False
    fields = ['year', 'pollutant', 'lbs']
    readonly_fields = fields
    ordering = ['-year', 'pollutant__name']

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ToxicPollutant)
class ToxicPollutantAdmin(ReadOnlyAdminMixin, base_admin.ModelAdmin):
    list_display = ['name', 'carb_id', 'cas_number', 'kind', 'iur', 'chronic_rel', 'acute_rel', 'mwaf', 'weighted', 'cancer_weight', 'chronic_weight', 'health_values_date']
    list_filter = ['kind', 'weighted']
    search_fields = ['name', 'carb_id', 'cas_number', 'slug']


@admin.register(SourceImport)
class SourceImportAdmin(ReadOnlyAdminMixin, base_admin.ModelAdmin):
    list_display = ['source', 'imported_at', 'data_through', 'version']
    list_filter = ['source']
```

and add `ToxicEmissionInline` to `FacilityAdmin.inlines` after `EmissionsRecordInline`.

- [ ] **Step 7: Fixture**

In `fixtures/emissions.yaml`, remove the line `    benzene: "2.0"` from record pk 3, and append:

```yaml
# Toxic pollutants: weights follow ToxicPollutant.set_weights() (iur × mwaf ×
# 7700; 0.01712 / chronic REL; 0.1712 / acute REL). Ammonia is a precursor
# and carries no weights; isopropyl alcohol has no OEHHA values.
- model: emissions.toxicpollutant
  pk: 1
  fields:
    carb_id: "71432"
    cas_number: 71-43-2
    name: Benzene
    slug: benzene
    kind: toxic
    iur: 2.9e-05
    chronic_rel: 3.0
    acute_rel: 27.0
    mwaf: 1.0
    weighted: true
    cancer_weight: 0.2233
    chronic_weight: 0.005706666666666667
    acute_weight: 0.006340740740740741
    health_values_date: 2024-12-17
- model: emissions.toxicpollutant
  pk: 2
  fields:
    carb_id: "9901"
    cas_number: ""
    name: Diesel PM
    slug: diesel-pm
    kind: toxic
    iur: 0.0003
    chronic_rel: 5.0
    acute_rel: null
    mwaf: 1.0
    weighted: true
    cancer_weight: 2.31
    chronic_weight: 0.003424
    acute_weight: 0.0
    health_values_date: 2024-12-17
- model: emissions.toxicpollutant
  pk: 3
  fields:
    carb_id: "7664417"
    cas_number: 7664-41-7
    name: Ammonia
    slug: ammonia
    kind: precursor
    iur: null
    chronic_rel: 200.0
    acute_rel: 3200.0
    mwaf: 1.0
    weighted: true
    cancer_weight: 0.0
    chronic_weight: 0.0
    acute_weight: 0.0
    health_values_date: 2024-12-17
- model: emissions.toxicpollutant
  pk: 4
  fields:
    carb_id: "67630"
    cas_number: 67-63-0
    name: Isopropyl alcohol
    slug: isopropyl-alcohol
    kind: toxic
    iur: null
    chronic_rel: null
    acute_rel: null
    mwaf: 1.0
    weighted: true
    cancer_weight: 0.0
    chronic_weight: 0.0
    acute_weight: 0.0
    health_values_date: null

# 2024 cancer-weighted: plant 2.0 × 0.2233 = 0.4466, cement 10 × 2.31 = 23.1,
# gas station 0.5 × 0.2233 = 0.11165; Valley total 23.65825.
- model: emissions.toxicemission
  pk: 1
  fields: {facility: 1, year: 2024, pollutant: 1, lbs: "2.0"}
- model: emissions.toxicemission
  pk: 2
  fields: {facility: 1, year: 2023, pollutant: 1, lbs: "1.0"}
- model: emissions.toxicemission
  pk: 3
  fields: {facility: 3, year: 2024, pollutant: 2, lbs: "10.0"}
- model: emissions.toxicemission
  pk: 4
  fields: {facility: 2, year: 2024, pollutant: 1, lbs: "0.5"}
- model: emissions.toxicemission
  pk: 5
  fields: {facility: 1, year: 2024, pollutant: 3, lbs: "100.0"}
- model: emissions.toxicemission
  pk: 6
  fields: {facility: 1, year: 2024, pollutant: 4, lbs: "50.0"}
```

- [ ] **Step 8: Tests**

In `camp/apps/emissions/tests/test_import_ceidars.py`:
- Delete `KERN_BENZENE` and `test_toxics_land_on_the_right_district`.
- In `carb()`, drop the `pollutants` parameter and the `cas_id` branch: the stub serves `criteria_by_county` for `faccrit` URLs and `toxics_by_county` otherwise. Drop the `pollutants` kwarg from `run_import` too.
- Add to `ImportCeidarsTests`:

```python
    def test_no_per_pollutant_requests(self):
        urls = []
        self.run_import(county='fresno', urls=urls)
        assert urls and all('showpol' not in url and 'facdet' not in url for url in urls)
```

Append to `camp/apps/emissions/tests/test_models.py` (add `from camp.apps.emissions.models import SourceImport, ToxicPollutant` beside its existing imports; keep `TestCase` from `django.test`):

```python
class ToxicPollutantTests(TestCase):
    def test_cas_from_carb_id(self):
        assert ToxicPollutant.cas_from_carb_id('71432') == '71-43-2'
        assert ToxicPollutant.cas_from_carb_id('18540299') == '18540-29-9'
        assert ToxicPollutant.cas_from_carb_id('9901') == ''

    def test_weights_follow_carbs_formulas(self):
        benzene = ToxicPollutant(carb_id='71432', name='Benzene', slug='benzene', iur=2.9e-5, chronic_rel=3.0, acute_rel=27.0)
        benzene.set_weights()
        assert abs(benzene.cancer_weight - 2.9e-5 * 7700) < 1e-12
        assert abs(benzene.chronic_weight - 0.01712 / 3) < 1e-12
        assert abs(benzene.acute_weight - 0.1712 / 27) < 1e-12
        chromate = ToxicPollutant(carb_id='7789062', name='Strontium chromate', slug='x', iur=0.15, mwaf=0.2554)
        chromate.set_weights()
        assert abs(chromate.cancer_weight - 0.15 * 0.2554 * 7700) < 1e-9

    def test_unweighted_and_precursor_get_no_weights(self):
        pahs = ToxicPollutant(carb_id='1150', name='PAHs', slug='pahs', iur=1.1e-3, chronic_rel=1.0, weighted=False)
        pahs.set_weights()
        assert pahs.cancer_weight == 0 and pahs.chronic_weight > 0
        ammonia = ToxicPollutant(carb_id='7664417', name='Ammonia', slug='ammonia', kind='precursor', chronic_rel=200.0, acute_rel=3200.0)
        ammonia.set_weights()
        assert (ammonia.cancer_weight, ammonia.chronic_weight, ammonia.acute_weight) == (0, 0, 0)

    def test_create_for_sets_kind_cas_and_a_unique_slug(self):
        ammonia = ToxicPollutant.create_for('7664417', 'Ammonia')
        assert ammonia.kind == ToxicPollutant.Kind.PRECURSOR and ammonia.cas_number == '7664-41-7'
        first = ToxicPollutant.create_for('1001', 'Cancer')
        assert first.slug == 'cancer-1001'
        assert ToxicPollutant.create_for('1002', 'Ammonia').slug == 'ammonia-1002'


class SourceImportTests(TestCase):
    def test_latest(self):
        assert SourceImport.latest('contable') is None
        SourceImport.objects.create(source='contable', version='2024-12-17')
        newest = SourceImport.objects.create(source='contable', version='2025-09-25')
        assert SourceImport.latest('contable') == newest
```

Create `camp/apps/emissions/tests/test_toxics_migration.py`:

```python
"""
The 0008 data migration, run for real: migrate back to 0007 (the ten
columns exist again, empty), write records the old way, migrate forward,
and check the copy. A TransactionTestCase because the executor commits.
"""
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [('emissions', '0007_toxics_long_format')]
AFTER = [('emissions', '0009_drop_named_toxics')]


class NamedToxicsMigrationTests(TransactionTestCase):
    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        self.migrate(AFTER)

    def test_named_columns_become_toxic_emission_rows(self):
        apps = self.migrate(BEFORE)
        Region = apps.get_model('regions', 'Region')
        Facility = apps.get_model('emissions', 'Facility')
        EmissionsRecord = apps.get_model('emissions', 'EmissionsRecord')
        district = Region.objects.create(name='SJVAPCD', slug='sjvapcd-mig', type='air_district', external_id='SJU')
        plant = Facility.objects.create(county_code=10, air_district=district, facid=1, name='PLANT', address={})
        EmissionsRecord.objects.create(facility=plant, year=2024, nox=Decimal('1.5'), benzene=Decimal('2.0'),
                                       chromium_hexavalent=Decimal('0.001'), total_score=Decimal('12.5'))
        EmissionsRecord.objects.create(facility=plant, year=2023, nox=Decimal('1.0'))

        apps = self.migrate(AFTER)
        ToxicEmission = apps.get_model('emissions', 'ToxicEmission')
        ToxicPollutant = apps.get_model('emissions', 'ToxicPollutant')
        EmissionsRecord = apps.get_model('emissions', 'EmissionsRecord')

        rows = {(row.year, row.pollutant.carb_id): row.lbs for row in ToxicEmission.objects.select_related('pollutant')}
        assert rows == {(2024, '71432'): Decimal('2.0'), (2024, '18540299'): Decimal('0.001')}
        assert ToxicPollutant.objects.count() == 10
        chromium = ToxicPollutant.objects.get(carb_id='18540299')
        assert (chromium.name, chromium.slug, chromium.cas_number, chromium.kind) == ('Hexavalent chromium', 'hexavalent-chromium', '18540-29-9', 'toxic')
        assert chromium.cancer_weight == 0 and chromium.iur is None
        # Nothing else on the records moved.
        assert EmissionsRecord.objects.count() == 2
        assert EmissionsRecord.objects.get(year=2024).total_score == Decimal('12.5')
        assert not hasattr(EmissionsRecord.objects.get(year=2024), 'benzene')
```

Run:

```
$TEST camp/apps/emissions/tests/test_models.py camp/apps/emissions/tests/test_toxics_migration.py camp/apps/emissions/tests/test_import_ceidars.py
```

Expected: all pass. Other emissions tests will fail until Tasks 4–5 (they still reference `benzene` on records or the old picker); that is expected here and fixed there. Also run `$MANAGE makemigrations --check --dry-run` and confirm "No changes detected".

- [ ] **Step 9: Migrate the dev server and commit**

```
docker exec $(docker ps --filter publish=8003 --format '{{.Names}}') python manage.py migrate
```

Expect 0007–0009 applied; note the row count `ToxicEmission.objects.count()` (via `python manage.py shell -c`) for the PR notes.

```
git -C <worktree> add camp/apps/emissions/migrations/0007_toxics_long_format.py camp/apps/emissions/migrations/0008_copy_named_toxics.py camp/apps/emissions/migrations/0009_drop_named_toxics.py camp/apps/emissions/tests/test_toxics_migration.py
git -C <worktree> commit -m "feat(emissions): store toxics in long format with health values and a SourceImport stamp" -- camp/apps/emissions/models.py camp/apps/emissions/migrations/0007_toxics_long_format.py camp/apps/emissions/migrations/0008_copy_named_toxics.py camp/apps/emissions/migrations/0009_drop_named_toxics.py camp/apps/emissions/ceidars.py camp/apps/emissions/management/commands/import_ceidars.py camp/apps/emissions/admin.py fixtures/emissions.yaml camp/apps/emissions/tests/test_import_ceidars.py camp/apps/emissions/tests/test_models.py camp/apps/emissions/tests/test_toxics_migration.py
```

---

### Task 2: The Consolidated Table parser and `import_health_values`

**Files:**
- Create: `camp/apps/emissions/contable.py`
- Create: `camp/apps/emissions/management/commands/import_health_values.py`
- Create: `camp/apps/emissions/tests/data/contable-sample.pdf` (six real pages), `camp/apps/emissions/tests/data/__init__.py` is **not** needed (data only)
- Create: `camp/apps/emissions/tests/test_health_values.py`
- Modify: `camp/apps/emissions/stats.py` (add `clear_caches()` and the cache generation; the rest of `stats.py` changes in Task 4)

**Interfaces:**
- Produces (`camp.apps.emissions.contable`):
  - `CONTABLE_URL`, `parse(path) -> (rows, date)` where `rows` is `[{'carb_id', 'cas_number', 'name', 'acute_rel', 'chronic_rel', 'iur', 'mwaf'}]` (one per id in a row's id cell, values `float | None`, `mwaf` defaults to `1.0`) and `date` is a `datetime.date | None` from the "last updated" line; `apply(rows, date) -> {'created': int, 'updated': int}` upserting `ToxicPollutant`; `clean_name(cell) -> str`; `number(cell) -> float | None`; `ids(cell) -> [str]`; constants `NAME_OVERRIDES`, `IUR_FALLBACKS = {'1151': '50328'}`, `COL_NAME = 0`, `COL_ID = 1`, `COL_ACUTE = 2`, `COL_CHRONIC = 6`, `COL_IUR = 10`, `COL_MWAF = 15`, `ROW_WIDTH = 16`.
  - `stats.clear_caches()`: bumps a cache generation every `stats`/`areas` key includes (the dairies module's pattern), so an import orphans every explorer aggregate without `cache.clear()`.
- Command: `import_health_values --path FILE | --url [URL] [--dump FILE]`; writes `SourceImport(source='contable', version=<date ISO>, data_through=<date>)`.

- [ ] **Step 1: Make the sample PDF**

The real table's layout, verified with pdfplumber on the 2024-12-17 PDF: `page.extract_table()` returns 16-cell rows; two header rows per page (col 0 `Substance`); data rows have the name in col 0, the id(s) in col 1 (`'71-43-2'`, `'9901'`, or several on one cell separated by newlines: `'7440-38-2\n1016\n[1015]'`, `'1150\n1151'`, `'7440-43-9\n[1045]'`), acute REL col 2, 8-hour col 4, chronic REL col 6, chronic oral col 8, IUR col 10, cancer potency col 11, oral slope col 13, MWAF col 15. Value cells can carry a `TAC` marker (`'2.9E-05TAC'`, `'1.5E-01\nTAC'`) and names can too (`'BENZENETAC'`, `'PARTICULATE EMISSIONS FROM\nDIESEL-FUELED ENGINESTAC, i'`, `'BENZO(A)PYRENEl'` with a footnote letter glued on). Pages 15–19 are notes whose "rows" have one cell. Every page's text has `last updated: December 17, 2024`.

```
mkdir -p <worktree>/camp/apps/emissions/tests/data
cp /tmp/claude-1000/-home-derek-dev-ccac-sjvair-com/d44a9b36-1d95-48d8-9dc1-7d9a1cd0932f/scratchpad/contable.pdf <worktree>/.superpowers/contable.pdf
qpdf <worktree>/.superpowers/contable.pdf --pages . 1-3,9,11,12 -- <worktree>/camp/apps/emissions/tests/data/contable-sample.pdf
```

Pages: 1 (header, Acetaldehyde, Ammonia, Arsenic with three ids), 2 (Benzene with `TAC` suffixes, code `1020`, Cadmium chloride MWAF 0.6132), 3 (Chromium 6+, Strontium chromate MWAF 0.2554, Cobalt `7.7E-3`, PCBTF), 9 (Diesel PM `9901`), 11 (PAH `1150`/`1151`, benzo(a)pyrene `50-32-8` with footnote `l`), 12 (Naphthalene). About 230 KB. Record that command in the test module's docstring.

- [ ] **Step 2: Write `contable.py`**

```python
"""
The CARB/OEHHA Consolidated Table of health values (contable.pdf): the
acute and chronic reference exposure levels, inhalation unit risk and
molecular-weight adjustment factor behind ToxicPollutant's weights.

PDF only. pdfplumber's extract_table() gives 16-cell rows; the columns used
are named below. An id cell can list several ids (a CAS and CARB's own
code, plus a bracketed retired code) that all take the row's values.
"""
import re
from datetime import datetime

import pdfplumber

from camp.apps.emissions.models import ToxicPollutant, UNWEIGHTED_IDS

CONTABLE_URL = 'https://ww2.arb.ca.gov/sites/default/files/classic/toxics/healthval/contable.pdf'

ROW_WIDTH = 16
COL_NAME = 0
COL_ID = 1
COL_ACUTE = 2
COL_CHRONIC = 6
COL_IUR = 10
COL_MWAF = 15

# The table's names are uppercase, marked and footnoted; these read better.
NAME_OVERRIDES = {
    '9901': 'Diesel PM',
    '18540299': 'Hexavalent chromium',
    '1150': 'PAHs (total, components also reported)',
    '1151': 'PAHs (total)',
    '1016': 'Arsenic (inorganic)',
}
# An id that takes another's IUR when the table gives it none: PAHs with no
# components reported are weighted as benzo(a)pyrene.
IUR_FALLBACKS = {'1151': '50328'}

_CAS_RE = re.compile(r'^\d{2,7}-\d{2}-\d$')
_CODE_RE = re.compile(r'^\[?(\d{4})\]?$')
_NUMBER_RE = re.compile(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?')
_DATE_RE = re.compile(r'last updated:?\s*([A-Z][a-z]+ \d{1,2}, \d{4})')


def ids(cell):
    """The CARB pollutant ids in an id cell: a dashed CAS without its dashes, or a 4-digit code (bracketed or not)."""
    result = []
    for token in (cell or '').split():
        token = token.strip()
        if _CAS_RE.match(token):
            result.append(token.replace('-', ''))
        else:
            match = _CODE_RE.match(token)
            if match:
                result.append(match.group(1))
    return result


def number(cell):
    """The first number in a value cell ('2.9E-05TAC', '1.5E-01\\nTAC', '7.7E-3'), or None for a blank."""
    match = _NUMBER_RE.search(cell or '')
    return float(match.group(0)) if match else None


def clean_name(cell):
    """One line, without the TAC marker, the 'values also apply to' tail or a footnote letter; sentence case when the table shouts."""
    name = ' '.join((cell or '').split())
    name = re.sub(r'\s*values also apply to:.*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'TAC\b', '', name)
    name = re.sub(r',\s*[a-z]$', '', name)            # ', i'
    name = re.sub(r'(?<=[A-Z)\]])[a-z]$', '', name)   # 'BENZO(A)PYRENEl'
    name = ' '.join(name.split()).strip(' ,')
    if name.isupper():
        name = name.capitalize()
    return name


def parse(path):
    """([row dicts], last-updated date or None) from the PDF at `path`."""
    rows = []
    date = None
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            if date is None:
                match = _DATE_RE.search(page.extract_text() or '')
                if match:
                    date = datetime.strptime(match.group(1), '%B %d, %Y').date()
            for row in page.extract_table() or []:
                if len(row) < ROW_WIDTH:
                    continue
                carb_ids = ids(row[COL_ID])
                if not carb_ids:
                    continue
                mwaf = number(row[COL_MWAF])
                for carb_id in carb_ids:
                    rows.append({
                        'carb_id': carb_id,
                        'cas_number': ToxicPollutant.cas_from_carb_id(carb_id),
                        'name': clean_name(row[COL_NAME]),
                        'acute_rel': number(row[COL_ACUTE]),
                        'chronic_rel': number(row[COL_CHRONIC]),
                        'iur': number(row[COL_IUR]),
                        'mwaf': mwaf if mwaf is not None else 1.0,
                    })
    return rows, date


def apply(rows, date):
    """
    Upsert ToxicPollutant from parsed rows: create a row for every table
    entry (so the picker can name a pollutant before any facility reports
    it), set the health values, apply the name overrides and IUR fallbacks,
    recompute the weights. The first of two rows for the same id wins.
    Returns {'created', 'updated'}.
    """
    by_id = {}
    for row in rows:
        by_id.setdefault(row['carb_id'], row)
    for carb_id, source in IUR_FALLBACKS.items():
        if carb_id in by_id and by_id[carb_id]['iur'] is None and source in by_id:
            by_id[carb_id]['iur'] = by_id[source]['iur']
    created = updated = 0
    for carb_id, row in by_id.items():
        name = NAME_OVERRIDES.get(carb_id, row['name'])
        pollutant = ToxicPollutant.objects.filter(carb_id=carb_id).first()
        if pollutant is None:
            pollutant = ToxicPollutant.create_for(carb_id, name)
            created += 1
        else:
            updated += 1
        pollutant.name = name
        pollutant.cas_number = row['cas_number']
        pollutant.iur = row['iur']
        pollutant.chronic_rel = row['chronic_rel']
        pollutant.acute_rel = row['acute_rel']
        pollutant.mwaf = row['mwaf']
        pollutant.weighted = carb_id not in UNWEIGHTED_IDS
        pollutant.health_values_date = date
        pollutant.set_weights()
        pollutant.save()
    return {'created': created, 'updated': updated}
```

- [ ] **Step 3: Cache generation in `stats.py`**

The explorer caches its aggregates for a day under `emissions:v{CACHE_VERSION}:…` keys (`stats.Scope.key`, `stats.available_years`, `areas._key`, `views.FIND_AREA_PLACES_KEY`). Memcached can't delete by prefix, so an import must orphan them the way `dairies.clear_caches()` does. In `stats.py`, after `CACHE_TIMEOUT`:

```python
# Every stats/areas key includes the generation; bumping it orphans them all
# (an import just landed). Persistent (no timeout), like the dairies one.
GENERATION_KEY = 'emissions:stats:generation'


def generation():
    return cache.get(GENERATION_KEY, 0)


def clear_caches():
    """Orphan every cached explorer aggregate and area value: they're keyed under the generation."""
    cache.set(GENERATION_KEY, generation() + 1, None)


def prefix():
    return f'emissions:v{CACHE_VERSION}:g{generation()}'
```

Then replace every `f'emissions:v{CACHE_VERSION}'` in `stats.py` (`available_years`'s key and `Scope.key`) with `prefix()`, and in `areas._key` change `f'emissions:v{stats.CACHE_VERSION}'` to `stats.prefix()`. `views.FIND_AREA_PLACES_KEY` is a module constant; leave it (it doesn't depend on toxics).

- [ ] **Step 4: The command**

Create `camp/apps/emissions/management/commands/import_health_values.py`:

```python
import json
import tempfile

import requests
from django.core.management.base import BaseCommand, CommandError

from camp.apps.emissions import contable, stats
from camp.apps.emissions.models import SourceImport


class Command(BaseCommand):
    help = "Import OEHHA health values from CARB's Consolidated Table PDF and recompute the toxic pollutant weights."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--path', help='A downloaded contable.pdf')
        group.add_argument('--url', nargs='?', const=contable.CONTABLE_URL, help=f'Download it (default: {contable.CONTABLE_URL})')
        parser.add_argument('--dump', help='Write the parsed rows as JSON to this path and change nothing')

    def handle(self, *args, **options):
        path = options['path']
        if not path:
            self.stdout.write(f"Downloading {options['url']}")
            response = requests.get(options['url'], timeout=60, headers={'User-Agent': 'Mozilla/5.0 (SJVAir importer)'})
            response.raise_for_status()
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                tmp.write(response.content)
                path = tmp.name
        rows, date = contable.parse(path)
        if not rows:
            raise CommandError('No health-value rows parsed; has the table layout changed?')
        self.stdout.write(f'Parsed {len(rows):,} rows; table dated {date or "unknown"}')
        if options['dump']:
            with open(options['dump'], 'w') as handle:
                json.dump({'date': date.isoformat() if date else None, 'rows': rows}, handle, indent=1)
            self.stdout.write(f"Wrote {options['dump']}")
            return
        result = contable.apply(rows, date)
        SourceImport.objects.create(source='contable', version=date.isoformat() if date else '', data_through=date,
                                    notes={'rows': len(rows), **result})
        stats.clear_caches()
        self.stdout.write(f"{result['created']} pollutants created, {result['updated']} updated")
```

- [ ] **Step 5: Tests**

Create `camp/apps/emissions/tests/test_health_values.py`:

```python
"""
contable-sample.pdf is pages 1-3, 9, 11 and 12 of the real table dated
2024-12-17:  qpdf contable.pdf --pages . 1-3,9,11,12 -- contable-sample.pdf
"""
from datetime import date
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from camp.apps.emissions import contable, stats
from camp.apps.emissions.models import SourceImport, ToxicPollutant

SAMPLE = Path(__file__).parent / 'data' / 'contable-sample.pdf'


class ParserTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.rows, cls.date = contable.parse(SAMPLE)
        cls.by_id = {row['carb_id']: row for row in cls.rows}

    def test_date_and_row_shape(self):
        assert self.date == date(2024, 12, 17)
        assert len(self.rows) > 60
        assert set(self.rows[0]) == {'carb_id', 'cas_number', 'name', 'acute_rel', 'chronic_rel', 'iur', 'mwaf'}

    def test_cas_row_with_tac_suffixes(self):
        benzene = self.by_id['71432']
        assert benzene['name'] == 'Benzene' and benzene['cas_number'] == '71-43-2'
        assert (benzene['acute_rel'], benzene['chronic_rel'], benzene['iur'], benzene['mwaf']) == (27.0, 3.0, 2.9e-5, 1.0)

    def test_carb_code_rows(self):
        diesel = self.by_id['9901']
        assert diesel['cas_number'] == '' and diesel['iur'] == 3.0e-4 and diesel['chronic_rel'] == 5.0 and diesel['acute_rel'] is None
        assert self.by_id['1020']['iur'] == 0.14

    def test_several_ids_share_a_row(self):
        assert self.by_id['7440382']['iur'] == self.by_id['1016']['iur'] == self.by_id['1015']['iur'] == 3.3e-3
        assert self.by_id['1150']['iur'] == self.by_id['1151']['iur'] == 1.1e-3

    def test_blanks_mwaf_and_footnotes(self):
        assert self.by_id['7664417']['iur'] is None and self.by_id['7664417']['chronic_rel'] == 200.0
        assert self.by_id['7789062']['mwaf'] == 0.2554
        assert self.by_id['7440484']['iur'] == 7.7e-3
        assert self.by_id['50328']['name'] == 'Benzo(a)pyrene'

    def test_helpers(self):
        assert contable.ids('7440-38-2\n1016\n[1015]') == ['7440382', '1016', '1015']
        assert contable.ids('Substance') == []
        assert contable.number('1.5E-01\nTAC') == 0.15 and contable.number('') is None
        assert contable.clean_name('PARTICULATE EMISSIONS FROM\nDIESEL-FUELED ENGINESTAC, i') == 'Particulate emissions from diesel-fueled engines'
        assert contable.clean_name('CHROMIUM 6+TAC values also apply to:g') == 'Chromium 6+'
        assert contable.clean_name('Fluorides and compounds') == 'Fluorides and compounds'


class ApplyTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def test_import_upserts_weights_names_and_the_stamp(self):
        ToxicPollutant.objects.filter(carb_id='71432').update(iur=1.0, cancer_weight=99, name='Old benzene')
        call_command('import_health_values', path=str(SAMPLE))
        benzene = ToxicPollutant.objects.get(carb_id='71432')
        assert benzene.name == 'Benzene' and benzene.slug == 'benzene'
        assert abs(benzene.cancer_weight - 2.9e-5 * 7700) < 1e-9
        assert benzene.health_values_date == date(2024, 12, 17)
        diesel = ToxicPollutant.objects.get(carb_id='9901')
        assert diesel.name == 'Diesel PM' and diesel.slug == 'diesel-pm' and abs(diesel.cancer_weight - 2.31) < 1e-9
        assert ToxicPollutant.objects.get(carb_id='1150').weighted is False
        assert ToxicPollutant.objects.get(carb_id='1150').cancer_weight == 0
        assert ToxicPollutant.objects.get(carb_id='1151').cancer_weight > 0
        assert ToxicPollutant.objects.get(carb_id='7664417').kind == 'precursor'
        assert ToxicPollutant.objects.get(carb_id='7664417').chronic_weight == 0
        stamp = SourceImport.latest('contable')
        assert stamp.version == '2024-12-17' and stamp.data_through == date(2024, 12, 17)

    def test_rerun_is_idempotent_and_keeps_slugs(self):
        call_command('import_health_values', path=str(SAMPLE))
        count = ToxicPollutant.objects.count()
        ToxicPollutant.objects.filter(carb_id='9901').update(slug='old-slug')
        call_command('import_health_values', path=str(SAMPLE))
        assert ToxicPollutant.objects.count() == count
        assert ToxicPollutant.objects.get(carb_id='9901').slug == 'old-slug'

    def test_import_bumps_the_cache_generation(self):
        before = stats.generation()
        call_command('import_health_values', path=str(SAMPLE))
        assert stats.generation() == before + 1
```

If `test_helpers`' exact strings differ from what `clean_name` produces on the real cells, fix `clean_name`, not the expectations, unless the expectation is plainly wrong for the cell.

```
$TEST camp/apps/emissions/tests/test_health_values.py camp/apps/emissions/tests/test_models.py
```

- [ ] **Step 6: Load the dev server and commit**

```
docker exec $(docker ps --filter publish=8003 --format '{{.Names}}') python manage.py import_health_values --path /app/.superpowers/contable.pdf
```

Expect roughly 250–300 rows and a `contable` stamp.

```
git -C <worktree> add camp/apps/emissions/contable.py camp/apps/emissions/management/commands/import_health_values.py camp/apps/emissions/tests/data/contable-sample.pdf camp/apps/emissions/tests/test_health_values.py
git -C <worktree> commit -m "feat(emissions): import OEHHA health values from the Consolidated Table" -- camp/apps/emissions/contable.py camp/apps/emissions/management/commands/import_health_values.py camp/apps/emissions/tests/data/contable-sample.pdf camp/apps/emissions/tests/test_health_values.py camp/apps/emissions/stats.py camp/apps/emissions/areas.py
```

---

### Task 3: `import_toxics`: the per-facility crawl

**Files:**
- Create: `camp/apps/emissions/management/commands/import_toxics.py`
- Create: `camp/apps/emissions/tests/data/guardian-2024.csv`, `camp/apps/emissions/tests/data/health-values.json`
- Create: `camp/apps/emissions/tests/test_import_toxics.py`

**Interfaces:**
- Command: `import_toxics --year Y [--county slug] [--workers 8]`. For every `Facility` with an `EmissionsRecord` in `Y` (per covered county, `carb.carb_counties(slug)` as `import_ceidars` uses), fetches `ceidars.facdet_url(...)` with `ceidars.fetch_csv` on a thread pool, then in one `transaction.atomic()` per county deletes the facility's `ToxicEmission` rows for `Y` and bulk-creates the CSV's; unknown `POLLUTANT_ID`s become `ToxicPollutant.create_for(id, name)`. A failed fetch is written to stderr and skipped (its existing rows are kept). Writes `SourceImport(source='ceidars-toxics', version=str(Y), notes={...})`, calls `stats.clear_caches()`. Ends with `CommandError` naming the failed count when any facility failed (rows already committed).
- Produces `camp.apps.emissions.management.commands.import_toxics.parse_rows(frame) -> [(carb_id, name, lbs_str)]`.

- [ ] **Step 1: Write the command**

```python
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from camp.apps.emissions import carb, ceidars, stats
from camp.apps.emissions.models import Facility, SourceImport, ToxicEmission, ToxicPollutant

# CARB's names are abbreviations in mixed case ('1,2,4TriMeBenze'); shouting
# ones are sentence-cased. import_health_values replaces them where the
# Consolidated Table has the pollutant.
def tidy_name(name):
    name = ' '.join(str(name).split())
    return name.capitalize() if name.isupper() else name


def parse_rows(frame):
    """[(carb_id, name, lbs)] from a facdet CSV frame, skipping blank ids and blank or non-positive pounds."""
    rows = []
    if frame.empty:
        return rows
    for _, row in frame.iterrows():
        carb_id = str(row.get('POLLUTANT_ID', '')).strip()
        lbs = ceidars.decimal_or_none(row.get('EMISSIONS_LBS_YR', ''))
        if not carb_id or lbs is None:
            continue
        try:
            if float(lbs) <= 0:
                continue
        except ValueError:
            continue
        rows.append((carb_id, tidy_name(row.get('POLLUTANT', '')) or carb_id, lbs))
    return rows


class Command(BaseCommand):
    help = "Import every toxic air contaminant each CEIDARS facility reported for one year, from CARB's per-facility detail CSVs."

    def status(self, msg):
        self.stdout.write(f'{msg}\033[K', ending='\r')

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, required=True, help='Inventory year (e.g. 2024)')
        parser.add_argument('--county', help='Limit to one covered county, by slug (e.g. fresno)')
        parser.add_argument('--workers', type=int, default=8, help='Parallel requests to CARB (default 8)')

    def handle(self, *args, **options):
        year = options['year']
        try:
            counties = carb.carb_counties(options.get('county'))
        except carb.CountyConfigError as exc:
            raise CommandError(str(exc))

        pollutants = {p.carb_id: p for p in ToxicPollutant.objects.all()}
        total_facilities = total_rows = total_failed = 0
        start = time.monotonic()

        for county_code, county in counties:
            label = f'{county.name} ({county_code})'
            facilities = list(
                Facility.objects.filter(county_code=county_code, emissions__year=year)
                .distinct().select_related('air_district').order_by('facid')
            )
            if not facilities:
                self.stdout.write(f'{label}: no facilities for {year}')
                continue

            def fetch(facility):
                url = ceidars.facdet_url(year, facility.county_code, facility.air_district.external_id, facility.facid)
                try:
                    return facility, ceidars.fetch_csv(url), None
                except requests.RequestException as exc:
                    return facility, None, exc

            self.status(f'{label}: fetching {len(facilities)} facilities...')
            with ThreadPoolExecutor(max_workers=options['workers']) as pool:
                results = list(pool.map(fetch, facilities))

            fetched = failed = rows_written = 0
            with transaction.atomic():
                for facility, frame, exc in results:
                    if exc is not None:
                        failed += 1
                        self.stderr.write(f'{label}: {facility.name} (facid {facility.facid}) fetch failed -- {exc}; kept its existing rows')
                        continue
                    fetched += 1
                    rows = parse_rows(frame)
                    ToxicEmission.objects.filter(facility=facility, year=year).delete()
                    batch = []
                    for carb_id, name, lbs in rows:
                        pollutant = pollutants.get(carb_id)
                        if pollutant is None:
                            pollutant = ToxicPollutant.create_for(carb_id, name)
                            pollutants[carb_id] = pollutant
                        batch.append(ToxicEmission(facility=facility, year=year, pollutant=pollutant, lbs=lbs))
                    ToxicEmission.objects.bulk_create(batch, ignore_conflicts=True)
                    rows_written += len(batch)

            self.stdout.write(f'{label}: {fetched} facilities, {rows_written} toxic rows, {failed} failed')
            total_facilities += fetched
            total_rows += rows_written
            total_failed += failed

        SourceImport.objects.create(
            source='ceidars-toxics', version=str(year),
            notes={'facilities': total_facilities, 'rows': total_rows, 'failed': total_failed},
        )
        stats.clear_caches()
        self.stdout.write(f'\nDone. {total_facilities} facilities, {total_rows} toxic rows, {total_failed} failed [{time.monotonic() - start:.1f}s]')
        if total_failed:
            raise CommandError(f'{total_failed} facilities could not be fetched; re-run for their counties.')
```

Note `ToxicPollutant.create_for` is called inside the transaction; `unique_slug` checks the DB, fine. The URL parsing in the test stub keys on `facid_=` and `co_=`.

- [ ] **Step 2: The regression data files**

Guardian Industries, LLC (Kingsburg glass plant) is `county_code=10`, district `SJU`, `facid=598` in CEIDARS (confirmed in the dev DB: `Facility.objects.get(county_code=10, air_district__external_id='SJU', facid=598)`). CARB's own cancer score for it in 2024 is 7,594.997 (`a24_toxtable3_2026_06_01.xlsx`, CANC_SCORE), which the research reproduced as 7,595 with the formulas above.

```
curl -sS 'https://www.arb.ca.gov/app/emsinv/iframe/facinfo/facdet_output.csv?&dbyr=2024&ab_=SJV&dis_=SJU&co_=10&sort=T&facid_=598' -o <worktree>/camp/apps/emissions/tests/data/guardian-2024.csv
$MANAGE import_health_values --path /app/.superpowers/contable.pdf --dump /app/camp/apps/emissions/tests/data/health-values.json
```

Check `guardian-2024.csv` has the seven columns and a few dozen rows (open it), and `health-values.json` is ~300 rows with `"date": "2024-12-17"`. Both go in the commit.

- [ ] **Step 3: Tests**

Create `camp/apps/emissions/tests/test_import_toxics.py`:

```python
"""
guardian-2024.csv is CARB's real facdet CSV for Guardian Industries (Fresno,
SJU, facid 598), fetched 2026-09-28:
  curl 'https://www.arb.ca.gov/app/emsinv/iframe/facinfo/facdet_output.csv?&dbyr=2024&ab_=SJV&dis_=SJU&co_=10&sort=T&facid_=598'
health-values.json is `import_health_values --dump` of the 2024-12-17 table.
"""
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from camp.apps.emissions import contable, stats
from camp.apps.emissions.models import EmissionsRecord, Facility, SourceImport, ToxicEmission, ToxicPollutant
from camp.apps.emissions.tests.test_import_ceidars import CA_COUNTY_CODES
from camp.apps.regions.models import Region

DATA = Path(__file__).parent / 'data'
HEADER = '"FACID","CO","AB","DIS","POLLUTANT_ID","POLLUTANT","EMISSIONS_LBS_YR"\n'


def facdet(rows_by_facid, failing=()):
    """A requests.get stand-in serving facdet CSVs by facid_=; raises for `failing` facids."""
    def get(url, **kwargs):
        facid = int(url.split('facid_=')[1].split('&')[0])
        if facid in failing:
            raise requests.ConnectionError('boom')
        mock = MagicMock()
        mock.raise_for_status.return_value = None
        mock.text = rows_by_facid.get(facid, HEADER)
        return mock
    return get


class ImportToxicsTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        for county in Region.objects.counties():
            county.metadata['ca_county_code'] = CA_COUNTY_CODES[county.name]
            county.save(update_fields=['metadata'])
        self.plant = Facility.objects.get(name='TEST PLANT')      # Fresno, SJU, facid 1
        self.cement = Facility.objects.get(name='TEST CEMENT')    # Kern, KER, facid 2
        self.gas = Facility.objects.get(name='TEST GAS STATION')  # Kern, SJU, facid 2

    def run_import(self, rows_by_facid, county=None, failing=(), urls=None):
        stub = facdet(rows_by_facid, failing)

        def get(url, **kwargs):
            if urls is not None:
                urls.append(url)
            return stub(url, **kwargs)

        with patch('requests.get', side_effect=get):
            kwargs = {'year': 2024, 'workers': 2}
            if county:
                kwargs['county'] = county
            call_command('import_toxics', **kwargs)

    def test_replaces_a_facilitys_rows_and_creates_unknown_pollutants(self):
        csv = HEADER + '1,10,"SJV","SJU",71432,"Benzene",3.5\n1,10,"SJV","SJU",9901,"Diesel PM",12\n1,10,"SJV","SJU",108883,"TOLUENE",7.25\n'
        self.run_import({1: csv}, county='fresno')
        rows = {row.pollutant.carb_id: row.lbs for row in self.plant.toxic_emissions.filter(year=2024)}
        assert rows == {'71432': Decimal('3.5'), '9901': Decimal('12'), '108883': Decimal('7.25')}
        toluene = ToxicPollutant.objects.get(carb_id='108883')
        assert (toluene.name, toluene.slug, toluene.cas_number, toluene.kind) == ('Toluene', 'toluene', '108-88-3', 'toxic')
        # The fixture's ammonia and isopropyl rows for 2024 were replaced; 2023 is untouched.
        assert self.plant.toxic_emissions.filter(year=2023).count() == 1
        stamp = SourceImport.latest('ceidars-toxics')
        assert stamp.version == '2024' and stamp.notes['facilities'] == 1

    def test_rerun_is_idempotent(self):
        csv = HEADER + '1,10,"SJV","SJU",71432,"Benzene",3.5\n'
        self.run_import({1: csv}, county='fresno')
        self.run_import({1: csv}, county='fresno')
        assert self.plant.toxic_emissions.filter(year=2024).count() == 1

    def test_urls_carry_basin_district_county_and_facid(self):
        urls = []
        self.run_import({}, county='kern', urls=urls)
        assert sorted(urls) == sorted([
            'https://www.arb.ca.gov/app/emsinv/iframe/facinfo/facdet_output.csv?&dbyr=2024&ab_=MD&dis_=KER&co_=15&sort=T&facid_=2',
            'https://www.arb.ca.gov/app/emsinv/iframe/facinfo/facdet_output.csv?&dbyr=2024&ab_=SJV&dis_=SJU&co_=15&sort=T&facid_=2',
        ])

    def test_an_empty_csv_clears_the_year(self):
        self.run_import({}, county='fresno')
        assert not self.plant.toxic_emissions.filter(year=2024).exists()

    def test_a_failed_facility_is_skipped_and_the_rest_land(self):
        # Kern has two facilities with the same facid in two districts; fail both
        # Kern fetches and check Fresno still lands and Kern keeps its old rows.
        before = set(self.cement.toxic_emissions.values_list('pk', flat=True))
        csv = HEADER + '1,10,"SJV","SJU",71432,"Benzene",3.5\n'
        with pytest.raises(CommandError, match='2 facilities'):
            self.run_import({1: csv}, failing={2})
        assert self.plant.toxic_emissions.get(year=2024, pollutant__carb_id='71432').lbs == Decimal('3.5')
        assert set(self.cement.toxic_emissions.values_list('pk', flat=True)) == before
        assert SourceImport.latest('ceidars-toxics').notes['failed'] == 2

    def test_import_bumps_the_cache_generation(self):
        before = stats.generation()
        self.run_import({}, county='fresno')
        assert stats.generation() == before + 1


class GuardianRegressionTests(TestCase):
    """CARB's own 2024 cancer score for Guardian Industries is 7,594.997; ours must land within 1."""

    fixtures = ['regions.yaml', 'emissions.yaml']

    def test_cancer_weighted_score_matches_carb(self):
        with open(DATA / 'health-values.json') as handle:
            table = json.load(handle)
        contable.apply(table['rows'], None)
        ToxicEmission.objects.all().delete()
        for county in Region.objects.counties():
            county.metadata['ca_county_code'] = CA_COUNTY_CODES[county.name]
            county.save(update_fields=['metadata'])
        fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        guardian = Facility.objects.create(
            county_code=10, air_district=Region.objects.get(pk=9001), facid=598, name='GUARDIAN INDUSTRIES, LLC',
            county=fresno, sic_code=3211, sector='glass', address={},
        )
        EmissionsRecord.objects.create(facility=guardian, year=2024, nox=1)
        with patch('requests.get', side_effect=facdet({598: (DATA / 'guardian-2024.csv').read_text()})):
            call_command('import_toxics', year=2024, county='fresno', workers=1)
        assert guardian.toxic_emissions.filter(year=2024).count() > 10
        score = stats.valley_totals('cancer_weight')[2024]
        assert abs(score - 7595) <= 1, score
```

`stats.valley_totals` is written in Task 4; run this module's `ImportToxicsTests` now and `GuardianRegressionTests` again after Task 4 (it will error with `AttributeError` until then, which is expected here). If the Guardian number lands outside ±1 after Task 4, do not widen the tolerance: stop and report the number and the facility's rows in the handoff.

```
$TEST camp/apps/emissions/tests/test_import_toxics.py -k ImportToxicsTests
```

- [ ] **Step 4: Start the dev crawl in the background, commit**

```
docker exec -d $(docker ps --filter publish=8003 --format '{{.Names}}') sh -c 'python manage.py import_toxics --year 2024 > /tmp/import_toxics_2024.log 2>&1'
```

(~10 minutes; check `/tmp/import_toxics_2024.log` in the container before Task 7's smoke.)

```
git -C <worktree> add camp/apps/emissions/management/commands/import_toxics.py camp/apps/emissions/tests/data/guardian-2024.csv camp/apps/emissions/tests/data/health-values.json camp/apps/emissions/tests/test_import_toxics.py
git -C <worktree> commit -m "feat(emissions): import every reported toxic per facility from CARB's detail CSVs" -- camp/apps/emissions/management/commands/import_toxics.py camp/apps/emissions/tests/data/guardian-2024.csv camp/apps/emissions/tests/data/health-values.json camp/apps/emissions/tests/test_import_toxics.py
```

---

### Task 4: One value source: pollutants, stats and areas on the new measures

**Files:**
- Modify: `camp/apps/emissions/pollutants.py` (rewrite)
- Modify: `camp/apps/emissions/stats.py` (most functions)
- Modify: `camp/apps/emissions/areas.py` (`_area_sums`, `area_values`)
- Modify: `camp/apps/emissions/templatetags/emissions_explorer.py` (`amount`, new `share_pct`, `emissions_trend_chart`)
- Modify: `camp/apps/emissions/tests/test_stats.py`, `camp/apps/emissions/tests/test_areas.py`, `camp/apps/emissions/tests/test_templatetags.py`

**Interfaces:**
- `pollutants.Pollutant(key, label, name, toxic=False, weight_field='', pollutant_id=None)`; properties `weighted`, `unit` (`'tons' | 'lbs' | 'share'`), `unit_label` (`'tons/yr' | 'lbs/yr' | 'share of Valley total'`), `slug` (alias of `key`); `CANCER`, `CHRONIC`, `WEIGHTED`, `DEFAULT_TOXIC = 'cancer'`, `LEGACY_TOXIC_KEYS` (old field name → CARB id), `get_pollutant(key)` (criteria only now), `toxic_pollutant(row) -> Pollutant`.
- `stats`: `resolve_toxic(key) -> Pollutant`, `legacy_toxic_slug(get) -> str | None`, `toxic_options(year) -> [Pollutant]`, `value_expr(pollutant)`, `weighted_lbs(weight_field)`, `valley_totals(weight_field) -> {year: raw total}`, `scale(pollutant, year) -> float`, `valued(scope, *, all_years=False)` (a `records()` queryset annotated `raw` and, for one year, `value`), `values(scope, *, sector=None) -> [(facility_id, value)]`, `totals(scope)['value']`, `toxic_rows(scope)`, `toxics_breakdown(scope, top=8) -> dict | None`, `facility_toxics(facility, year)` rows gain `weight`, `share`, `has_cancer_value`, `hazard`, `hot_spots(record) -> dict | None`, `SMALL_BASELINE_FLOOR['share'] = 0.0001`, `CACHE_VERSION = 2`.
- `emissions_explorer` filters: `share_pct(value)`; `amount(value, pollutant)` formats a share as a percent.

- [ ] **Step 1: Rewrite `pollutants.py`**

```python
"""The pollutants the explorer can show: the criteria pollutants, the two weighted toxics measures, and (from the database) every toxic CARB reports."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Pollutant:
    key: str                 # picker key: an EmissionsRecord field, 'cancer' / 'chronic', or a ToxicPollutant slug
    label: str               # short, for pickers and column headers
    name: str                # spelled out
    toxic: bool = False
    weight_field: str = ''   # 'cancer_weight' or 'chronic_weight' for the two weighted measures
    pollutant_id: Optional[int] = None  # ToxicPollutant pk for one toxic

    @property
    def weighted(self):
        return bool(self.weight_field)

    @property
    def slug(self):
        return self.key

    @property
    def unit(self):
        """
        'tons' (criteria, CEIDARS tons/yr), 'lbs' (one toxic, CARB's lbs/yr),
        or 'share' (a weighted measure: the facility's, area's or scope's
        fraction of the Valley's weighted total that year -- it has no unit a
        person can read, so it's never shown raw).
        """
        if self.weighted:
            return 'share'
        return 'lbs' if self.toxic else 'tons'

    @property
    def unit_label(self):
        return {'tons': 'tons/yr', 'lbs': 'lbs/yr', 'share': 'share of Valley total'}[self.unit]

    def display(self, value):
        """The stored value in its display unit -- a passthrough (values are already tons, lbs or a share)."""
        return None if value is None else float(value)


CRITERIA = [
    Pollutant('nox', 'NOx', 'Nitrogen oxides'),
    Pollutant('rog', 'ROG', 'Reactive organic gases'),
    Pollutant('pm', 'Total PM', 'Total particulate matter'),
    Pollutant('pm10', 'PM10', 'Particulate matter under 10 microns'),
    Pollutant('sox', 'SOx', 'Sulfur oxides'),
    Pollutant('co', 'CO', 'Carbon monoxide'),
    Pollutant('tog', 'TOG', 'Total organic gases'),
]

# The two toxicity-weighted measures (pounds × OEHHA potency, CARB's method;
# see models.ToxicPollutant.set_weights). Shown as a share of the Valley
# total, never as a number with a unit.
CANCER = Pollutant('cancer', 'Cancer-weighted', 'Cancer-weighted toxics (relative)', toxic=True, weight_field='cancer_weight')
CHRONIC = Pollutant('chronic', 'Hazard-weighted', 'Non-cancer hazard-weighted toxics (relative)', toxic=True, weight_field='chronic_weight')
WEIGHTED = [CANCER, CHRONIC]

POLLUTANTS = {pollutant.key: pollutant for pollutant in CRITERIA + WEIGHTED}
DEFAULT_CRITERIA = 'nox'
DEFAULT_TOXIC = 'cancer'

# The ten toxics the explorer used to store as columns, by their old picker
# key; old links resolve (and redirect) to the pollutant's slug.
LEGACY_TOXIC_KEYS = {
    'acetaldehyde': '75070', 'benzene': '71432', 'butadiene': '106990', 'carbon_tetrachloride': '56235',
    'chromium_hexavalent': '18540299', 'dichlorobenzene': '106467', 'formaldehyde': '50000',
    'methylene_chloride': '75092', 'naphthalene': '91203', 'perchloroethylene': '127184',
}


def get_pollutant(key):
    """The criteria pollutant for `key`, else the default. Toxics resolve in stats.resolve_toxic (they live in the database)."""
    pollutant = POLLUTANTS.get(key)
    if pollutant is not None and not pollutant.toxic:
        return pollutant
    return POLLUTANTS[DEFAULT_CRITERIA]


def toxic_pollutant(row):
    """A Pollutant for one ToxicPollutant row (or a values() dict with pk, slug, name)."""
    if isinstance(row, dict):
        return Pollutant(row['slug'], row['name'], row['name'], toxic=True, pollutant_id=row['pk'])
    return Pollutant(row.slug, row.name, row.name, toxic=True, pollutant_id=row.pk)
```

- [ ] **Step 2: `stats.py`: the value source**

Imports: add `FloatField, OuterRef, Subquery, ExpressionWrapper` from `django.db.models`, `Cast` from `django.db.models.functions`, `ToxicEmission, ToxicPollutant` from the models, and change the pollutants import to `from camp.apps.emissions.pollutants import CRITERIA, DEFAULT_CRITERIA, DEFAULT_TOXIC, LEGACY_TOXIC_KEYS, POLLUTANTS, WEIGHTED, Pollutant, get_pollutant, toxic_pollutant`. Set `CACHE_VERSION = 2` and `SMALL_BASELINE_FLOOR = {'tons': 1.0, 'lbs': 10.0, 'share': 0.0001}`. Update the module docstring: values are tons/yr for criteria, lbs/yr for one toxic, and a share of the Valley total for the weighted measures.

Replace `resolve_scope` and add the toxics resolution:

```python
def resolve_toxic(key):
    """
    The toxics picker's Pollutant for `key`: a weighted measure ('cancer',
    'chronic'), a ToxicPollutant slug, or one of the ten old column keys
    (LEGACY_TOXIC_KEYS); the default when unknown. Precursors (ammonia)
    aren't toxics and never resolve here.
    """
    if key in POLLUTANTS and POLLUTANTS[key].toxic:
        return POLLUTANTS[key]
    row = None
    if key:
        rows = ToxicPollutant.objects.filter(kind=ToxicPollutant.Kind.TOXIC)
        carb_id = LEGACY_TOXIC_KEYS.get(key)
        row = rows.filter(Q(slug=key) | Q(carb_id=carb_id)).first() if carb_id else rows.filter(slug=key).first()
    return toxic_pollutant(row) if row else POLLUTANTS[DEFAULT_TOXIC]


def legacy_toxic_slug(params):
    """The slug an old `?toxics=1&pollutant=<field>` link should redirect to, or None when it isn't one (or the pollutant is unknown)."""
    key = params.get('pollutant')
    if params.get('toxics') != '1' or key not in LEGACY_TOXIC_KEYS:
        return None
    return ToxicPollutant.objects.filter(carb_id=LEGACY_TOXIC_KEYS[key]).values_list('slug', flat=True).first()


def resolve_scope(params):
    """Scope from a request's GET; anything unknown falls back to its default."""
    years = available_years()
    year = _int(params.get('year'))
    if year not in years:
        year = years[-1] if years else None
    county = None
    if params.get('county'):
        county = Region.objects.counties().filter(slug=params['county']).first()
    toxics = params.get('toxics') == '1'
    key = params.get('pollutant')
    return Scope(
        year=year,
        county=county,
        pollutant=resolve_toxic(key) if toxics else get_pollutant(key),
        minor=params.get('minor') == '1',
    )


def toxic_options(year):
    """
    The toxics picker: the two weighted measures, then every toxic with any
    Valley pounds in `year`, by its share of the cancer-weighted total (then
    name). Precursors are left out.
    """
    def compute():
        rows = (
            ToxicEmission.objects.filter(year=year, pollutant__kind=ToxicPollutant.Kind.TOXIC)
            .values('pollutant_id', 'pollutant__slug', 'pollutant__name')
            .annotate(weight=Sum(weighted_lbs('cancer_weight')), lbs=Sum('lbs'))
            .filter(lbs__gt=0)
        )
        rows = sorted(rows, key=lambda row: (-(row['weight'] or 0), row['pollutant__name'].lower()))
        return [toxic_pollutant({'pk': r['pollutant_id'], 'slug': r['pollutant__slug'], 'name': r['pollutant__name']}) for r in rows]
    return WEIGHTED + cache.get_or_set(f'{prefix()}:toxic-options:{year}', compute, CACHE_TIMEOUT)
```

Then the value machinery, placed after `records()`:

```python
def weighted_lbs(weight_field):
    """lbs × the pollutant's weight, as a float expression on a ToxicEmission queryset."""
    return ExpressionWrapper(Cast('lbs', FloatField()) * F(f'pollutant__{weight_field}'), output_field=FloatField())


def value_expr(pollutant):
    """
    The un-scaled `value` of one EmissionsRecord row for `pollutant`: its
    column for a criteria pollutant; for one toxic, that facility-year's
    ToxicEmission pounds; for a weighted measure, Σ lbs × weight over the
    facility-year's toxics (precursors excluded by kind). Null where the
    facility reported none.
    """
    if not pollutant.toxic:
        return F(pollutant.key)
    rows = ToxicEmission.objects.filter(facility_id=OuterRef('facility_id'), year=OuterRef('year'))
    if pollutant.weighted:
        rows = (
            rows.filter(pollutant__kind=ToxicPollutant.Kind.TOXIC).order_by().values('facility_id')
            .annotate(total=Sum(weighted_lbs(pollutant.weight_field))).values('total')
        )
        return Subquery(rows[:1], output_field=FloatField())
    return Subquery(rows.filter(pollutant_id=pollutant.pollutant_id).values('lbs')[:1], output_field=FloatField())


def valley_totals(weight_field):
    """{year: the Valley's raw weighted total} over every facility (minor sources included) and county. What a share is a share of."""
    def compute():
        rows = (
            ToxicEmission.objects.filter(pollutant__kind=ToxicPollutant.Kind.TOXIC)
            .values('year').annotate(total=Sum(weighted_lbs(weight_field)))
        )
        return {row['year']: float(row['total'] or 0) for row in rows}
    return cache.get_or_set(f'{prefix()}:valley-totals:{weight_field}', compute, CACHE_TIMEOUT)


def scale(pollutant, year):
    """What a raw value is multiplied by for display: 1 for tons and lbs; 1 / the Valley's total that year for a weighted measure (0 when there's none)."""
    if not pollutant.weighted:
        return 1.0
    total = valley_totals(pollutant.weight_field).get(year)
    return 1.0 / total if total else 0.0


def valued(scope, *, all_years=False):
    """records(scope) annotated with `raw` (value_expr) and, for the scope year, `value` (raw × scale, a float)."""
    queryset = records(scope, all_years=all_years).annotate(raw=value_expr(scope.pollutant))
    if not all_years:
        factor = Value(scale(scope.pollutant, scope.year), output_field=FloatField())
        queryset = queryset.annotate(value=ExpressionWrapper(Cast('raw', FloatField()) * factor, output_field=FloatField()))
    return queryset


def values(scope, *, sector=None):
    """[(facility_id, value)] for the scope: the one source the map, list, sectors, areas and region pages share."""
    queryset = valued(scope)
    if sector:
        queryset = queryset.filter(facility__sector=sector)
    return list(queryset.values_list('facility_id', 'value'))
```

Now rewrite the aggregates to read `raw` / `value`:

```python
def totals(scope):
    """The scope's facility count, each criteria pollutant's total, and `value`: the scope pollutant's total in its display unit (for a weighted measure, the shown facilities' summed share of the Valley total)."""
    def compute():
        row = valued(scope).aggregate(
            facilities=Count('facility', distinct=True),
            value=Sum('raw'),
            **{pollutant.key: Sum(pollutant.key) for pollutant in CRITERIA},
        )
        result = {key: (value if key == 'facilities' else _float(value)) for key, value in row.items()}
        if result['value'] is not None:
            result['value'] = result['value'] * scale(scope.pollutant, scope.year)
        return result
    return cache.get_or_set(scope.key('totals'), compute, CACHE_TIMEOUT)


def ranks(scope):
    def compute():
        pairs = valued(scope).filter(raw__gt=0).order_by('-raw').values_list('facility_id', 'raw')
        return _competition_ranks(pairs)
    return cache.get_or_set(scope.key('ranks'), compute, CACHE_TIMEOUT)
```

`facility_table`: replace `field = scope.pollutant.key` and the `records(scope)...annotate(value=F(field))` chain with `queryset = valued(scope).select_related('facility', 'facility__county', 'facility__city', 'facility__air_district')`; in the sort branches use `F('value')` where it used `F(field)`, and `Q(raw__gt=0)` in `unranked`. Everything else stays.

`sector_breakdown` / `county_breakdown`: drop `field = ...`; use `valued(scope)` (`valued(everywhere)` in county_breakdown) with `.annotate(facilities=Count('facility', distinct=True), value=Sum('raw'))`, and multiply every `float(row['value'] or 0)` by a `factor = scale(scope.pollutant, scope.year)` computed once inside `compute()`.

`by_year`: the `facility` branch becomes `EmissionsRecord.objects.filter(facility=facility).annotate(raw=value_expr(scope.pollutant))`; the other branch `valued(scope, all_years=True)`; then

```python
        rows = queryset.values('year').annotate(value=Sum('raw')).order_by('year')
        return [{'year': row['year'], 'value': float(row['value'] or 0) * scale(scope.pollutant, row['year'])} for row in rows]
```

`sector_trends`: `valued(scope, all_years=True).values('facility__sector', 'year').annotate(value=Sum('raw'))` and the same per-year `scale` multiplication. `county_context`: unchanged (it reads `totals(scope)[field]` for criteria only).

- [ ] **Step 3: `stats.py`: facility-page and breakdown helpers**

Replace `facility_toxics` and add `toxic_rows`, `toxics_breakdown`, `hot_spots`:

```python
def toxic_rows(scope):
    """ToxicEmission rows in the scope (its year, county, area and minor toggle -- the same filters as records()), toxics only."""
    queryset = ToxicEmission.objects.filter(year=scope.year, pollutant__kind=ToxicPollutant.Kind.TOXIC)
    if scope.county is not None:
        queryset = queryset.filter(facility__county=scope.county)
    if scope.area is not None:
        queryset = queryset.filter(scope.area.q())
    if not scope.minor:
        queryset = queryset.exclude(facility__sic_code__in=MINOR_SOURCE_SIC_CODES)
    return queryset


def toxics_breakdown(scope, top=8):
    """
    What drives the scope's cancer-weighted total, by pollutant: the top
    `top` and an "Other" bucket, each with its share of the scope's total
    (and the total's share of the Valley's). None when nothing is weighted.
    """
    def compute():
        rows = (
            toxic_rows(scope).values('pollutant__slug', 'pollutant__name')
            .annotate(weight=Sum(weighted_lbs('cancer_weight'))).filter(weight__gt=0).order_by('-weight', 'pollutant__name')
        )
        rows = list(rows)
        total = sum(row['weight'] for row in rows)
        if not total:
            return None
        parts = [{'slug': row['pollutant__slug'], 'name': row['pollutant__name'], 'share': row['weight'] / total} for row in rows[:top]]
        rest = sum(row['weight'] for row in rows[top:])
        if rest:
            parts.append({'slug': None, 'name': 'Other', 'share': rest / total})
        return {'parts': parts, 'pollutants': len(rows), 'valley_share': total * scale(POLLUTANTS['cancer'], scope.year)}
    return cache.get_or_set(scope.key('toxics-breakdown', top), compute, CACHE_TIMEOUT)


def facility_toxics(facility, year):
    """
    Every toxic the facility reported in `year` (precursors left out), in
    lbs/yr with the year before when it has one, its share of the Valley's
    cancer-weighted total (None when the pollutant has no cancer value) and
    whether it carries a non-cancer hazard weight; sorted by cancer weight,
    then pounds.
    """
    current = list(
        facility.toxic_emissions.filter(year=year, pollutant__kind=ToxicPollutant.Kind.TOXIC).select_related('pollutant')
    )
    if not current:
        return []
    previous = dict(facility.toxic_emissions.filter(year=year - 1).values_list('pollutant_id', 'lbs'))
    total = valley_totals('cancer_weight').get(year) or 0
    rows = []
    for row in current:
        lbs = float(row.lbs)
        weight = lbs * row.pollutant.cancer_weight
        rows.append({
            'pollutant': row.pollutant,
            'value': lbs,
            'previous': _float(previous.get(row.pollutant_id)),
            'previous_year': year - 1 if previous else None,
            'weight': weight,
            'share': weight / total if total and weight else None,
            'has_cancer_value': row.pollutant.cancer_weight > 0,
            'hazard': row.pollutant.chronic_weight > 0,
        })
    rows.sort(key=lambda row: (-row['weight'], -row['value']))
    return rows


def hot_spots(record):
    """The AB 2588 Hot Spots fields on a record as floats, or None when none is set (no card)."""
    if record is None:
        return None
    fields = {name: _float(getattr(record, name)) for name in ('total_score', 'hra', 'chindex', 'ahindex')}
    return fields if any(value is not None for value in fields.values()) else None
```

- [ ] **Step 4: `areas.py`**

Replace `_area_sums` and its use in `area_values`:

```python
def _area_sums(scope, level, sector, index):
    """{region pk: summed value} over every facility in `scope` that falls in `level`, through stats.values()."""
    sums, counts = {}, {}
    for facility_id, value in stats.values(scope, sector=sector):
        region = index.get(facility_id)
        if region is None:
            continue
        counts[region] = counts.get(region, 0) + 1
        sums[region] = sums.get(region, 0.0) + float(value or 0)
    return counts, sums
```

In `area_values`: drop `field = scope.pollutant.key`; call `counts, sums = _area_sums(scope, level, sector, index)` and `_, compare_sums = _area_sums(replace(scope, year=compare), level, sector, index)`; for the `without_point` count use `rows = stats.records(scope)` (with the sector filter applied) as before — build it explicitly: `rows = stats.records(scope); if sector: rows = rows.filter(facility__sector=sector)`. For `unit == 'share'`, the two rates are meaningless: set `per_sq_mi` and `per_1k_residents` (and their `_prev`) to `None` when `scope.pollutant.unit == 'share'`. The docstring gains one sentence saying so.

- [ ] **Step 5: Template filters**

In `camp/apps/emissions/templatetags/emissions_explorer.py`:

```python
@register.filter
def share_pct(value):
    """
    A share of the Valley total (0-1) as a percent with the precision small
    shares need: '24%', '1.2%', '0.03%', '<0.01%', '0%', '—'.
    """
    if value is None:
        return '—'
    value = float(value)
    if value == 0:
        return '0%'
    pct = value * 100
    if pct < 0.01:
        return '<0.01%'
    if pct < 0.1:
        return f'{pct:.2f}%'
    if pct < 10:
        return f'{pct:.1f}%'
    return f'{pct:.0f}%'


@register.filter
def amount(value, pollutant):
    """A pollutant amount (already in its display unit) formatted: a percent for a weighted measure, else quantity()."""
    if pollutant.unit == 'share':
        return share_pct(pollutant.display(value))
    return quantity(pollutant.display(value))
```

In `emissions_trend_chart`, a weighted measure charts percent: after `values = [...]`, add

```python
    unit = pollutant.unit
    if unit == 'share':
        values = [value * 100 for value in values]
        unit = '%'
```

and use `unit` in the `chart['unit']` and the default title (`f'{pollutant.label} by year ({unit}/yr)'` → for share: `f'{pollutant.label} toxics, share of Valley total by year (%)'`). Check `assets/js/pesticides/charts.js` `amount(value, unit)`: if an unknown unit isn't appended to the value, add a `'%'` branch there (`if (unit === '%') return full(value) + '%';`) and note it for Task 6's asset rebuild.

- [ ] **Step 6: Tests**

`camp/apps/emissions/tests/test_stats.py`:
- `PollutantTests.test_units`: replace the two `benzene` lines with `assert POLLUTANTS['cancer'].unit == 'share' and POLLUTANTS['cancer'].unit_label == 'share of Valley total'` and `assert POLLUTANTS['chronic'].weighted and not POLLUTANTS['nox'].weighted`.
- `test_get_pollutant_falls_back_to_the_kind_default`: replace the two toxic lines with `assert get_pollutant('cancer').key == 'nox'` (criteria only) and add a new class:

```python
class ToxicResolutionTests(StatsTestCase):
    def test_weighted_keys_slugs_and_legacy_keys(self):
        assert stats.resolve_toxic('cancer').weight_field == 'cancer_weight'
        assert stats.resolve_toxic('chronic').unit == 'share'
        benzene = stats.resolve_toxic('benzene')
        assert benzene.key == 'benzene' and benzene.pollutant_id == 1 and benzene.unit == 'lbs'
        ToxicPollutant.objects.filter(pk=1).update(slug='benzene-x')
        assert stats.resolve_toxic('benzene').key == 'benzene-x'          # a legacy key resolves by CARB id
        assert stats.legacy_toxic_slug({'toxics': '1', 'pollutant': 'benzene'}) == 'benzene-x'
        assert stats.legacy_toxic_slug({'pollutant': 'benzene'}) is None
        assert stats.legacy_toxic_slug({'toxics': '1', 'pollutant': 'cancer'}) is None

    def test_unknown_and_precursor_fall_back_to_cancer(self):
        assert stats.resolve_toxic('bogus').key == 'cancer'
        assert stats.resolve_toxic('ammonia').key == 'cancer'
        assert scope(toxics=1).pollutant.key == 'cancer'
        assert scope(toxics=1, pollutant='diesel-pm').pollutant.key == 'diesel-pm'

    def test_toxic_options_order_and_precursor_exclusion(self):
        keys = [p.key for p in stats.toxic_options(2024)]
        assert keys == ['cancer', 'chronic', 'diesel-pm', 'benzene', 'isopropyl-alcohol']
        assert [p.key for p in stats.toxic_options(2023)] == ['cancer', 'chronic', 'benzene']

    def test_query_drops_the_toxics_default(self):
        assert scope(toxics=1).query() == '?toxics=1'
        assert scope(toxics=1, pollutant='benzene').query() == '?pollutant=benzene&toxics=1'
```

Add `from camp.apps.emissions.models import ToxicPollutant` to the imports. Add to `TotalsAndRanksTests`:

```python
    def test_one_toxic_in_pounds(self):
        s = scope(toxics=1, pollutant='benzene')
        assert stats.totals(s)['value'] == 2.0
        assert stats.totals(scope(toxics=1, pollutant='benzene', minor=1))['value'] == 2.5
        assert stats.ranks(s) == {self.plant.pk: 1}
        # The cement plant has no benzene row: its value is None, not missing.
        assert dict(stats.values(s)) == {self.plant.pk: 2.0, self.cement.pk: None}

    def test_weighted_values_are_shares_that_sum_to_one(self):
        # 2024 cancer weights: plant 0.4466, cement 23.1, gas station 0.11165 (fixture comments).
        total = 23.65825
        everyone = scope(toxics=1, minor=1)
        shares = dict(stats.values(everyone))
        assert abs(shares[self.cement.pk] - 23.1 / total) < 1e-9
        assert abs(shares[self.plant.pk] - 0.4466 / total) < 1e-9
        assert abs(sum(shares.values()) - 1.0) < 1e-9
        assert abs(stats.totals(everyone)['value'] - 1.0) < 1e-9
        # Minor sources off: the shares are of the same Valley total, so they no longer sum to one.
        assert abs(stats.totals(scope(toxics=1))['value'] - (23.1 + 0.4466) / total) < 1e-9
        assert stats.ranks(scope(toxics=1)) == {self.cement.pk: 1, self.plant.pk: 2}
        totals = stats.valley_totals('cancer_weight')
        assert set(totals) == {2023, 2024}
        assert abs(totals[2023] - 0.2233) < 1e-9 and abs(totals[2024] - total) < 1e-9

    def test_chronic_measure(self):
        shares = dict(stats.values(scope(toxics=1, pollutant='chronic', minor=1)))
        total = 2.0 * 0.005706666666666667 + 10 * 0.003424 + 0.5 * 0.005706666666666667
        assert abs(shares[self.cement.pk] - 0.03424 / total) < 1e-9

    def test_precursor_is_not_a_toxic(self):
        # Ammonia has weights 0 and kind precursor: 100 lbs of it move nothing.
        ToxicPollutant.objects.filter(carb_id='7664417').update(cancer_weight=5.0)
        cache.clear()
        assert abs(stats.valley_totals('cancer_weight')[2024] - 23.65825) < 1e-9

    def test_facility_table_sorts_on_the_measure(self):
        names = [r.facility.name for r in stats.facility_table(scope(toxics=1))]
        assert names == ['TEST CEMENT', 'TEST PLANT']
        assert [r.facility.name for r in stats.facility_table(scope(toxics=1), sort='value')] == ['TEST PLANT', 'TEST CEMENT']
        assert abs(stats.facility_table(scope(toxics=1))[0].value - 23.1 / 23.65825) < 1e-9

    def test_share_baseline_floor(self):
        assert stats.comparable_baseline(0.0002, 'share') and not stats.comparable_baseline(0.00005, 'share')
```

Add to `BreakdownTests`:

```python
    def test_by_year_and_breakdowns_for_a_weighted_measure(self):
        s = scope(toxics=1, minor=1)
        assert [(row['year'], round(row['value'], 6)) for row in stats.by_year(s)] == [(2023, 1.0), (2024, 1.0)]
        assert round(stats.by_year(scope(toxics=1), facility=self.plant)[1]['value'], 6) == round(0.4466 / 23.65825, 6)
        sectors = {row['sector']: row for row in stats.sector_breakdown(s)}
        assert round(sectors['cement-minerals']['value'], 6) == round(23.1 / 23.65825, 6)
        assert round(sectors['cement-minerals']['share'], 6) == round(23.1 / 23.65825, 6)
        counties = {row['county']: row['value'] for row in stats.county_breakdown(s)}
        assert round(counties[self.kern], 6) == round((23.1 + 0.11165) / 23.65825, 6)

    def test_toxics_breakdown(self):
        breakdown = stats.toxics_breakdown(scope(toxics=1))
        assert [part['name'] for part in breakdown['parts']] == ['Diesel PM', 'Benzene']
        assert round(breakdown['parts'][0]['share'], 6) == round(23.1 / (23.1 + 0.4466), 6)
        assert breakdown['parts'][1]['slug'] == 'benzene'
        assert round(breakdown['valley_share'], 6) == round((23.1 + 0.4466) / 23.65825, 6)
        assert stats.toxics_breakdown(scope(toxics=1, county='fresno', year=2023))['parts'][0]['name'] == 'Benzene'
        assert stats.toxics_breakdown(scope(toxics=1, county='fresno', year=2023, pollutant='benzene')) is not None  # any toxics scope, not only the weighted ones
        top = stats.toxics_breakdown(scope(toxics=1, minor=1), top=1)
        assert [part['name'] for part in top['parts']] == ['Diesel PM', 'Other']
```

Replace `FacilityDetailStatsTests.test_facility_toxics_in_lbs` with:

```python
    def test_facility_toxics_rows(self):
        rows = stats.facility_toxics(self.plant, 2024)
        assert [row['pollutant'].slug for row in rows] == ['benzene', 'isopropyl-alcohol']   # no ammonia; weighted first
        benzene, isopropyl = rows
        assert (benzene['value'], benzene['previous'], benzene['previous_year']) == (2.0, 1.0, 2023)
        assert round(benzene['share'], 6) == round(0.4466 / 23.65825, 6)
        assert benzene['has_cancer_value'] and benzene['hazard']
        assert isopropyl['share'] is None and not isopropyl['has_cancer_value'] and not isopropyl['hazard']
        assert isopropyl['previous'] is None and isopropyl['previous_year'] == 2023
        assert stats.facility_toxics(self.cement, 2023) == []

    def test_hot_spots(self):
        record = self.plant.emissions.get(year=2024)
        assert stats.hot_spots(record) is None
        EmissionsRecord.objects.filter(pk=record.pk).update(total_score=12.5, hra=4.27)
        record.refresh_from_db()
        assert stats.hot_spots(record) == {'total_score': 12.5, 'hra': 4.27, 'chindex': None, 'ahindex': None}
        assert stats.hot_spots(None) is None
```

`camp/apps/emissions/tests/test_areas.py`: replace `test_toxics_in_pounds` with

```python
    def test_toxics_in_pounds_and_weighted_shares(self):
        tract = make(Region.Type.TRACT, 'T1', AROUND_PLANT, population=2000)
        lbs = stats.resolve_scope({'year': '2024', 'toxics': '1', 'pollutant': 'benzene'})
        values = areas.area_values(lbs, Region.Type.TRACT)
        assert values['unit'] == 'lbs' and values['areas'][0]['total'] == 2.0
        share = stats.resolve_scope({'year': '2024', 'toxics': '1'})
        values = areas.area_values(share, Region.Type.TRACT)
        assert values['unit'] == 'share'
        [area] = values['areas']
        assert abs(area['total'] - 0.4466 / 23.65825) < 1e-9
        assert area['per_sq_mi'] is None and area['per_1k_residents'] is None
```

`camp/apps/emissions/tests/test_templatetags.py`: add

```python
from camp.apps.emissions.pollutants import CANCER, POLLUTANTS
from camp.apps.emissions.templatetags.emissions_explorer import amount, share_pct


class SharePctTests(TestCase):
    def test_formats(self):
        assert share_pct(None) == '—' and share_pct(0) == '0%'
        assert share_pct(0.00005) == '<0.01%' and share_pct(0.0003) == '0.03%'
        assert share_pct(0.012) == '1.2%' and share_pct(0.2437) == '24%' and share_pct(1) == '100%'
        assert amount(0.012, CANCER) == '1.2%' and amount(2, POLLUTANTS['nox']) == '2.0'
```

(Adjust the import style to the module's existing one.)

```
$TEST camp/apps/emissions/tests/test_stats.py camp/apps/emissions/tests/test_areas.py camp/apps/emissions/tests/test_templatetags.py camp/apps/emissions/tests/test_import_toxics.py camp/apps/emissions/tests/test_lists.py
```

`GuardianRegressionTests` now runs for real: it must pass within ±1 (see Review Focus). Views tests still fail until Task 5.

- [ ] **Step 7: Commit**

```
git -C <worktree> commit -m "refactor(emissions): one value source for criteria, toxics and weighted measures" -- camp/apps/emissions/pollutants.py camp/apps/emissions/stats.py camp/apps/emissions/areas.py camp/apps/emissions/templatetags/emissions_explorer.py camp/apps/emissions/tests/test_stats.py camp/apps/emissions/tests/test_areas.py camp/apps/emissions/tests/test_templatetags.py
```

---

### Task 5: Pages: picker, redirects, breakdown bar, facility toxics table, Hot Spots card, About, API

**Files:**
- Modify: `camp/apps/emissions/views.py` (`ScopeMixin`, `Home`, `FacilityList.csv_response`, `FacilityDetail`, `map_view`, `facility_map_config`, `AreaPage.get_context_data`, `RegionPage` / `NearMe` map config calls, `About`)
- Modify: `camp/templates/emissions/includes/scope-picker.html`, `includes/map-toolbar.html`, `includes/facility-table.html`, `home.html`, `area.html`, `facility-detail.html`, `sector-detail.html`, `about.html`
- Create: `camp/templates/emissions/includes/toxics-breakdown.html`, `camp/templates/emissions/includes/toxics-caveats.html`, `camp/templates/emissions/includes/hot-spots.html`
- Modify: `datafiles/data-integrations.yaml` (Emissions Data section)
- Modify: `camp/api/v2/emissions/geojson.py` (`cache_key_version = 3`, docstring), `camp/api/v2/emissions/areas.py` (`cache_key_version = 3`)
- Modify: `camp/apps/emissions/tests/test_views.py`, `test_facility_page.py`, `camp/api/v2/emissions/tests.py`

**Interfaces:**
- `views.map_view(get, default_level=..., year=None, *, share=False)`: `measure` is forced to `'total'` when `share`.
- `views.facility_map_config(...)` gains `disabled_measures` (template-only): `{'density': tooltip, 'per_resident': tooltip}` when `scope.pollutant.unit == 'share'`, else `{}`. `SHARE_MEASURE_TOOLTIP = 'Weighted toxics are shown as a share of the Valley total, not per square mile.'`
- `ScopeMixin.dispatch` 301s legacy toxic keys via `stats.legacy_toxic_slug`.
- Context: `pollutant_options` (from `stats.toxic_options(scope.year)` for toxics), `toxics_breakdown` (home and area pages when `scope.toxics`), `toxics_rows`, `hot_spots`, `health_values` (`SourceImport.latest('contable')`) on the facility page and About.
- Includes: `toxics-breakdown.html` (context `toxics_breakdown`, `pollutant`, `year`), `toxics-caveats.html` (context `health_values`, optional `compact`), `hot-spots.html` (context `hot_spots`, `shown_year`).

- [ ] **Step 1: `views.py`**

Imports: `from camp.apps.emissions.models import Facility, SourceImport`; keep `CRITERIA`, drop `TOXICS` (gone). Add near `PAGE_SIZE`:

```python
SHARE_MEASURE_TOOLTIP = 'Weighted toxics are shown as a share of the Valley total, not per square mile.'
```

`ScopeMixin`:

```python
    def dispatch(self, request, *args, **kwargs):
        # The ten toxics that used to be columns had their own picker keys;
        # an old link 301s to the pollutant's slug (the API resolves the
        # old key quietly instead).
        slug = stats.legacy_toxic_slug(request.GET)
        if slug:
            params = request.GET.copy()
            params['pollutant'] = slug
            return redirect(f'{request.path}?{params.urlencode()}', permanent=True)
        return super().dispatch(request, *args, **kwargs)
```

and in `get_context_data`: `'pollutant_options': stats.toxic_options(scope.year) if scope.toxics else CRITERIA`.

`Home.get_context_data`: `total=totals['value']`, and add `toxics_breakdown=stats.toxics_breakdown(scope) if scope.toxics else None`.

`About.get_context_data`: add `health_values=SourceImport.latest('contable')`, `toxics_import=SourceImport.latest('ceidars-toxics')`.

`FacilityList.csv_response`: the header becomes

```python
        toxic_column = [] if not scope.toxics else [f"{scope.pollutant.key}_{'share' if scope.pollutant.weighted else 'lbs'}"]
        writer.writerow(
            ['rank', 'facility', 'id', 'air_district', 'county', 'city', 'sector', 'sic_code', 'year']
            + [f'{pollutant.key}_tons' for pollutant in CRITERIA] + toxic_column
        )
```

and each row's values are `[pollutant.display(getattr(record, pollutant.key)) for pollutant in CRITERIA] + ([record.value] if scope.toxics else [])`.

`FacilityDetail.get_context_data`: add `hot_spots=stats.hot_spots(record)` and `health_values=SourceImport.latest('contable')`; `toxics_rows` stays (`stats.facility_toxics(facility, shown_year)`); drop `criteria=CRITERIA` only if nothing in the template uses it (it doesn't; remove it).

`map_view`: signature `def map_view(get, default_level=areas.DEFAULT_LEVEL, year=None, *, share=False)`; the measure line becomes

```python
    measure = measure if measure in areas.MEASURES else areas.DEFAULT_MEASURE
    if share:
        measure = 'total'
```

`facility_map_config`: after `'measure_options': ...` add `'disabled_measures': {'density': SHARE_MEASURE_TOOLTIP, 'per_resident': SHARE_MEASURE_TOOLTIP} if scope.pollutant.unit == 'share' else {},` and add `'disabled_measures'` to `template_only`. Also pass the pollutant's name for legends: add `'name': scope.pollutant.name,` beside `'label'` (the JS may use it; harmless as a data attribute).

Every `map_view(...)` call that has a year (`MapPage`, `RegionPage.get_map_config`, `NearMe.get_map_config`) passes `share=scope.pollutant.unit == 'share'` (in `MapPage` the scope is `self.get_scope()`).

`AreaPage.get_context_data`: `total = totals['value'] or 0`, `county_total = stats.totals(county_scope)['value'] if county else None`; drop `field = scope.pollutant.key`; add `toxics_breakdown=stats.toxics_breakdown(scope) if scope.toxics else None` and `share_unit=scope.pollutant.unit == 'share'`.

- [ ] **Step 2: Picker and toolbar templates**

`includes/scope-picker.html`, inside the pollutant dropdown's `{% for option in pollutant_options %}` loop, after the `{% endif %}` that closes the disabled/enabled item, add:

```django
                {% if option.key == 'chronic' %}<hr class="dropdown-divider">{% endif %}
```

`includes/map-toolbar.html`, the measure dropdown's items:

```django
            {% for value, label in map_config.measure_options %}{% if value in map_config.disabled_measures %}<span class="dropdown-item is-disabled has-tooltip-left has-tooltip-multiline has-tooltip-arrow" aria-disabled="true" data-tooltip="{{ map_config.disabled_measures|lookup:value }}">{{ label }}</span>{% else %}<a href="#" class="dropdown-item{% if value == map_config.measure %} is-active{% endif %}" data-measure="{{ value }}">{{ label }}</a>{% endif %}{% endfor %}
```

(`lookup` is in `emissions_explorer`; add `{% load emissions_explorer %}` at the top of the toolbar template if it isn't loaded.)

- [ ] **Step 3: Unit labels in the shared templates**

- `includes/facility-table.html`: `{% with heading=pollutant.label|add:" ("|add:pollutant.unit_label|add:")" %}`.
- `home.html` stat row: the second tile becomes
  ```django
  <div class="level-item has-text-centered"><div><p class="heading">{% if pollutant.weighted %}Share of the Valley's {{ pollutant.label|lower }} toxics{% else %}{{ pollutant.name }}{% endif %}</p><p class="title">{{ total|amount:pollutant }}{% if not pollutant.weighted %} <span class="is-size-5">{{ pollutant.unit_label }}</span>{% endif %}</p></div></div>
  ```
  and after the `{% if context_bar %}` line add `{% if toxics_breakdown %}{% include 'emissions/includes/toxics-breakdown.html' %}{% endif %}`.
- `area.html` stat row: the same tile change; wrap the "Per square mile" tile in `{% if not share_unit %}…{% endif %}`; after the top facilities table (`{% include 'emissions/includes/facility-table.html' with rows=top_rows sortable=False %}` and its `{% else %}…{% endif %}`) add `{% if toxics_breakdown %}{% include 'emissions/includes/toxics-breakdown.html' %}{% endif %}`. Don't touch the dairy lines.
- `sector-detail.html`: `{{ pollutant.unit }}/yr` → `{{ pollutant.unit_label }}` in the tile (hide the span for `pollutant.weighted` as on home), and the county table header `{{ pollutant.unit|capfirst }}/yr` → `{{ pollutant.unit_label|capfirst }}`.
- `map.html`: the sentence "its area shows the facility's {{ pollutant.name|lower }} in {{ year }}" is fine for the weighted names ("cancer-weighted toxics (relative)"); leave it.

Create `includes/toxics-breakdown.html`:

```django
{% load emissions_explorer %}
{% comment %}
"What drives it": the scope's cancer-weighted toxics by pollutant (stats.toxics_breakdown), on the home and area pages in the toxics scope.
{% endcomment %}
<div class="box emissions-context toxics-breakdown">
    <p><strong>What drives it.</strong> The cancer-weighted toxics of the facilities shown, by pollutant, {{ year }}{% if toxics_breakdown.pollutants > toxics_breakdown.parts|length %} (top {{ toxics_breakdown.parts|length|add:"-1" }} of {{ toxics_breakdown.pollutants }}){% endif %}.
       Together they hold <strong>{{ toxics_breakdown.valley_share|share_pct }}</strong> of the Valley's total.</p>
    <div class="emissions-context-bar" role="img" aria-label="{% for part in toxics_breakdown.parts %}{{ part.name }} {{ part.share|percent }}{% if not forloop.last %}, {% endif %}{% endfor %}">
        {% for part in toxics_breakdown.parts %}<span class="segment is-toxic-{{ forloop.counter }}" style="width: {{ part.share|width_pct }}" title="{{ part.name }}: {{ part.share|percent }}"></span>{% endfor %}
    </div>
    <p class="emissions-legend">
        {% for part in toxics_breakdown.parts %}<span><span class="swatch is-toxic-{{ forloop.counter }}"></span>{% if part.slug %}<a href="{% qs_replace toxics=1 pollutant=part.slug page=None %}">{{ part.name }}</a>{% else %}{{ part.name }}{% endif %} {{ part.share|percent }}</span>{% endfor %}
    </p>
    <p class="is-size-7"><a href="{% url 'emissions:about' %}#weighted-toxics">How toxics are weighted, and what this isn't</a></p>
</div>
```

(`qs_replace` is in `pesticides_explorer`; load it too: `{% load emissions_explorer pesticides_explorer %}`.)

- [ ] **Step 4: The facility page**

Create `includes/hot-spots.html`:

```django
{% load emissions_explorer %}
{% comment %}AB 2588 Hot Spots results CARB carries for the facility (stats.hot_spots): the district's prioritization score, the approved HRA's cancer risk, and the hazard indices.{% endcomment %}
<div class="card hot-spots">
    <header class="card-header"><p class="card-header-title">Hot Spots (AB 2588), {{ shown_year }}</p></header>
    <div class="card-content content">
        <dl class="hot-spots-values">
            {% if hot_spots.total_score is not None %}<dt>Prioritization score</dt><dd><strong>{{ hot_spots.total_score|quantity }}</strong> <span class="has-text-grey">High priority above 10</span></dd>{% endif %}
            {% if hot_spots.hra is not None %}<dt>HRA cancer risk</dt><dd><strong>{{ hot_spots.hra|quantity }}</strong> per million <span class="has-text-grey">public notification at 10, risk reduction required at 100</span></dd>{% endif %}
            {% if hot_spots.chindex is not None %}<dt>Chronic hazard index</dt><dd><strong>{{ hot_spots.chindex|quantity }}</strong> <span class="has-text-grey">1.0 is the reference level</span></dd>{% endif %}
            {% if hot_spots.ahindex is not None %}<dt>Acute hazard index</dt><dd><strong>{{ hot_spots.ahindex|quantity }}</strong> <span class="has-text-grey">1.0 is the reference level</span></dd>{% endif %}
        </dl>
        <p class="is-size-7 has-text-grey">These are the official measures. CARB notes the risk data may not come from the same year's emissions and that risk may have been substantially reduced since. The district publishes its <a href="https://www.valleyair.org/permitting/air-toxics-program/information-for-the-public/air-toxics-annual-reports/">Air Toxics annual reports</a>.</p>
    </div>
</div>
```

Create `includes/toxics-caveats.html` (the spec's caveat copy, verbatim; `{{ date }}` is the table's date):

```django
{% comment %}"What this is, and isn't": the caveat panel for the weighted toxics measures (facility page, About). `health_values` is SourceImport.latest('contable').{% endcomment %}
<div class="content toxics-caveats{% if compact %} is-size-7{% endif %}">
    <p class="heading">What this is, and isn't</p>
    <ul>
        <li><strong>Not a health risk.</strong> This ranks pounds released × how toxic each chemical is. It ignores stack height, weather, distance to homes and how long anyone is exposed. A tall stack in open land can score higher than a small source next to a school.</li>
        <li><strong>Relative, not absolute.</strong> The number is a share of the Valley total. It has no units and isn't a risk "in a million".</li>
        <li><strong>The official measures are CARB's Hot Spots scores.</strong> Where a facility has one, it's shown. As of the district's 2025 report, no Valley facility exceeds the public-notification threshold.</li>
        <li><strong>Toxics may be from earlier years.</strong> CARB carries a facility's toxics forward from its last inventory.</li>
        <li><strong>Diesel PM here is from permitted stationary engines only.</strong> Trucks, trains and farm equipment, the main sources of diesel exposure in the Valley, aren't permitted facilities.</li>
        <li><strong>Chemicals with no state cancer value count as zero.</strong> Health values change: this uses OEHHA's table dated {% if health_values.version %}{{ health_values.version }}{% else %}(not yet loaded){% endif %}.</li>
    </ul>
</div>
```

In `facility-detail.html`: in the "Where" card's parent `<div class="columns facility-cards">`, add a second column after the Where column:

```django
    {% if hot_spots %}<div class="column is-half">{% include 'emissions/includes/hot-spots.html' %}</div>{% endif %}
```

Replace the `{% if toxics_rows %}…{% endif %}` toxics table block with:

```django
{% if toxics_rows %}
<h3 class="title is-4">Toxic air contaminants in {{ shown_year }}</h3>
<div class="table-container">
<table class="table is-fullwidth is-narrow toxics-table">
    <thead><tr>
        <th>Contaminant</th>
        <th class="has-text-right">Lbs/yr</th>
        <th class="has-text-right">Year before</th>
        <th class="has-text-right">Share of the Valley's cancer-weighted total
            <span class="icon is-small has-text-grey has-tooltip-multiline has-tooltip-bottom has-tooltip-end has-tooltip-arrow" data-tooltip="This pollutant's pounds × its OEHHA cancer potency, as a share of the same sum over every permitted facility in the eight counties in {{ shown_year }}. Not a risk to anyone."><span class="fa-regular fa-circle-info" aria-hidden="true"></span></span></th>
        <th>Non-cancer hazard
            <span class="icon is-small has-text-grey has-tooltip-multiline has-tooltip-bottom has-tooltip-end has-tooltip-arrow" data-tooltip="Marked when OEHHA has set a chronic reference exposure level for the chemical."><span class="fa-regular fa-circle-info" aria-hidden="true"></span></span></th>
    </tr></thead>
    <tbody>
        {% for row in toxics_rows %}
        <tr>
            <td><a href="{% qs_replace toxics=1 pollutant=row.pollutant.slug %}">{{ row.pollutant.name }}</a></td>
            <td class="has-text-right">{{ row.value|quantity }}</td>
            <td class="has-text-right">{% if row.previous is not None %}{{ row.previous|quantity }}{% else %}—{% endif %}</td>
            <td class="has-text-right">{% if row.has_cancer_value %}{{ row.share|share_pct }}{% else %}<span class="has-text-grey">no OEHHA cancer value</span>{% endif %}</td>
            <td>{% if row.hazard %}<span class="hazard-dot" title="Has a chronic reference exposure level" aria-label="non-cancer hazard"></span>{% endif %}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
</div>
{% include 'emissions/includes/toxics-caveats.html' with compact=True %}
{% endif %}
```

- [ ] **Step 5: About page and integrations**

In `about.html`, change the units bullet to: `<li>Criteria pollutants are in <strong>tons per year</strong>. <strong>Toxic air contaminants</strong> are in <strong>pounds per year</strong>, because the amounts are small; see <a href="#weighted-toxics">Toxicity-weighted emissions</a> for how they're compared.</li>`. Add before `<h2 id="dairies">`:

```django
<h2 id="weighted-toxics">Toxicity-weighted emissions</h2>
<p>CARB's inventory lists every toxic air contaminant a facility reports, in pounds. Pounds alone rank ammonia and solvents above diesel particulate and hexavalent chromium, so the explorer's default toxics view weights each pollutant by how toxic it is, the way CARB's own Pollution Mapping Tool does: <strong>cancer-weighted</strong> is pounds × the OEHHA inhalation unit risk × a molecular-weight adjustment factor × 7,700; <strong>hazard-weighted</strong> is pounds ÷ the chronic reference exposure level × 0.01712. The values come from the CARB/OEHHA <a href="https://ww2.arb.ca.gov/resources/documents/consolidated-table-oehha-arb-approved-risk-assessment-health-values">Consolidated Table of health values</a>{% if health_values %}, dated {{ health_values.version }}{% endif %}. A facility's or area's number is shown as its share of the Valley total that year, and every facility that reported a pollutant is included, whether or not the table has a value for it (those without one count as zero). PAHs reported as a total alongside their components aren't weighted, to avoid counting them twice.{% if toxics_import %} Toxics were last fetched from CARB for {{ toxics_import.version }}.{% endif %}</p>
{% include 'emissions/includes/toxics-caveats.html' %}
```

In the Sources list add `<li><a href="https://ww2.arb.ca.gov/resources/documents/consolidated-table-oehha-arb-approved-risk-assessment-health-values">CARB/OEHHA Consolidated Table of health values</a></li>` after the CEIDARS item.

In `datafiles/data-integrations.yaml`, under `category: Emissions Data`, after the CEIDARS entry add:

```yaml
    - name: OEHHA Consolidated Table
      logo: img/logo/carb-vertical.png
      url: https://ww2.arb.ca.gov/resources/documents/consolidated-table-oehha-arb-approved-risk-assessment-health-values
      description: The Consolidated Table of OEHHA/CARB-approved health values lists, for each toxic air contaminant, the cancer potency and the reference exposure levels California's Hot Spots program uses in risk assessments. SJVAir uses it to weight facilities' reported toxics by toxicity, so diesel particulate and hexavalent chromium rank above high-volume, low-toxicity solvents.
```

(Reuse the CARB logo the CEIDARS entry uses; the about-page memory rule prefers a repo logo over a new download.)

- [ ] **Step 6: API cache versions**

`camp/api/v2/emissions/geojson.py`: `FacilityGeoJSON.cache_key_version = 3`; docstring: `value`/`value_prev` are tons/yr, lbs/yr for one toxic, or a share (0–1) of the Valley total for a weighted measure (`properties.unit` says which). `camp/api/v2/emissions/areas.py`: `AreaValues.cache_key_version = 3`.

- [ ] **Step 7: Tests**

`camp/apps/emissions/tests/test_views.py`:
- `FacilityListTests.test_csv`: replace the `benzene_lbs` assertion with a second request: `rows = list(csv.DictReader(io.StringIO(self.get('facility-list', params={'format': 'csv', 'toxics': 1, 'pollutant': 'benzene'}).content.decode())))`, `assert float(rows[0]['benzene_lbs']) == 2.0 and rows[0]['facility'] == 'TEST PLANT'`, and `assert 'benzene_lbs' not in list(csv.DictReader(...default csv...))[0]`.
- `HomeTests.test_renders_for_every_scope`: add `{'toxics': 1, 'pollutant': 'diesel-pm'}`, `{'toxics': 1, 'pollutant': 'chronic'}` to the params list.
- Add:

```python
class ToxicsPagesTests(ViewTestCase):
    def test_legacy_toxic_key_redirects(self):
        # Benzene's slug happens to equal its old key; a renamed slug shows the redirect for real.
        ToxicPollutant.objects.filter(carb_id='71432').update(slug='benzene-2')
        response = self.client.get(reverse('emissions:home'), {'toxics': 1, 'pollutant': 'benzene', 'year': 2024})
        assert response.status_code == 301
        location = response['Location']
        assert location.startswith(reverse('emissions:home') + '?')
        assert parse_qs(location.split('?', 1)[1]) == {'toxics': ['1'], 'pollutant': ['benzene-2'], 'year': ['2024']}
        # Not a toxics scope, or not an old key: no redirect.
        assert self.client.get(reverse('emissions:facility-list'), {'pollutant': 'benzene'}).status_code == 200
        assert self.client.get(reverse('emissions:facility-list'), {'toxics': 1, 'pollutant': 'benzene-2'}).status_code == 200

    def test_picker_lists_weighted_measures_then_toxics(self):
        content = self.get('home', params={'toxics': 1}).content.decode()
        assert content.index('pollutant=chronic') < content.index('pollutant=diesel-pm') < content.index('pollutant=benzene')
        assert 'pollutant=ammonia' not in content
        assert '<span class="explorer-scope-label">Cancer-weighted</span>' in content

    def test_home_shows_shares_and_the_breakdown(self):
        content = self.get('home', params={'toxics': 1}).content.decode()
        assert "Share of the Valley's cancer-weighted toxics" in content
        assert '99.5%' in content            # (23.1 + 0.4466) / 23.65825, minor sources off
        assert 'What drives it' in content and 'Diesel PM' in content
        assert 'share/yr' not in content and 'share of Valley total</span>' not in content

    def test_region_page_shows_the_breakdown_and_no_per_square_mile(self):
        kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        content = self.client.get(kern.get_emissions_url(), {'toxics': 1}).content.decode()
        assert 'What drives it' in content and 'Per square mile' not in content
        content = self.client.get(kern.get_emissions_url()).content.decode()
        assert 'What drives it' not in content and 'Per square mile' in content

    def test_share_measures_are_disabled(self):
        content = self.get('map', params={'toxics': 1, 'view': 'areas', 'measure': 'density'}).content.decode()
        # Only Total is a live item; density and per-resident are disabled spans with the tooltip.
        assert re.search(r'class="dropdown-item is-active" data-measure="total"', content)
        assert 'data-measure="density"' not in content and 'data-measure="per_resident"' not in content
        assert content.count(views.SHARE_MEASURE_TOOLTIP) == 2
        assert 'data-unit="share"' in content and 'data-measure="total"' in content
        assert views.map_view({'measure': 'density'}, year=2024, share=True)['measure'] == 'total'
        plain = self.get('map', params={'view': 'areas'}).content.decode()
        assert 'data-measure="density"' in plain and views.SHARE_MEASURE_TOOLTIP not in plain
```

Import `ToxicPollutant` in that module. Simplify the first redirect assertion to `assert response['Location'].endswith('?toxics=1&pollutant=benzene&year=2024')` (order follows the QueryDict copy; if Django orders differently, assert with `parse_qs` on the query instead).

`camp/apps/emissions/tests/test_facility_page.py`: add

```python
class FacilityToxicsTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.plant = Facility.objects.get(name='TEST PLANT')

    def detail(self, facility):
        return self.client.get(facility.get_absolute_url()).content.decode()

    def test_toxics_table_order_flags_and_links(self):
        content = self.detail(self.plant)
        table = content[content.index('toxics-table'):content.index('toxics-caveats')]
        assert table.index('Benzene') < table.index('Isopropyl alcohol')
        assert 'pollutant=benzene' in table and 'no OEHHA cancer value' in table
        assert table.count('hazard-dot') == 1
        assert '1.9%' in table  # 0.4466 / 23.65825
        assert 'What this is, and isn' in content

    def test_ammonia_row_is_not_in_the_toxics_table(self):
        content = self.detail(self.plant)
        table = content[content.index('toxics-table'):content.index('toxics-caveats')]
        assert 'Ammonia' not in table

    def test_hot_spots_card_and_its_absence(self):
        assert 'Hot Spots (AB 2588)' not in self.detail(self.plant)
        EmissionsRecord.objects.filter(facility=self.plant, year=2024).update(total_score=12.5, hra=4.27)
        content = self.detail(self.plant)
        assert 'Hot Spots (AB 2588)' in content and 'High priority above 10' in content
        assert 'public notification at 10, risk reduction required at 100' in content
        assert 'Chronic hazard index' not in content
        assert 'air-toxics-annual-reports' in content

    def test_no_toxics_no_table(self):
        cement = Facility.objects.get(name='TEST CEMENT')
        ToxicEmission.objects.filter(facility=cement).delete()
        assert 'toxics-table' not in self.detail(cement)
```

Import `EmissionsRecord, ToxicEmission` there. `AboutTests.test_about`: add `assert 'id="weighted-toxics"' in content and 'Consolidated Table' in content`.

`camp/api/v2/emissions/tests.py`: find the facility GeoJSON and area values tests and add one each:

```python
    def test_weighted_measure_is_a_share(self):
        data = self.client.get(reverse('api:v2:emissions:geojson'), {'toxics': '1', 'minor': '1'}).json()
        assert data['properties']['unit'] == 'share' and data['properties']['pollutant'] == 'cancer'
        values = {f['properties']['name']: f['properties']['value'] for f in data['features']}
        assert abs(sum(values.values()) - 1.0) < 1e-9 and values['TEST CEMENT'] > 0.9
        old = self.client.get(reverse('api:v2:emissions:geojson'), {'toxics': '1', 'pollutant': 'benzene'}).json()
        assert old['properties']['unit'] == 'lbs' and old['properties']['pollutant'] == 'benzene'
```

(Adapt the request helper to the module's existing style; the endpoint does not redirect legacy keys, it resolves them.)

```
$TEST camp/apps/emissions camp/api/v2/emissions
```

Everything in both trees must pass now.

- [ ] **Step 8: Commit**

```
git -C <worktree> add camp/templates/emissions/includes/toxics-breakdown.html camp/templates/emissions/includes/toxics-caveats.html camp/templates/emissions/includes/hot-spots.html
git -C <worktree> commit -m "feat(emissions): cancer-weighted toxics as the default view, the full facility toxics table and the Hot Spots card" -- camp/apps/emissions/views.py camp/templates/emissions/includes/scope-picker.html camp/templates/emissions/includes/map-toolbar.html camp/templates/emissions/includes/facility-table.html camp/templates/emissions/home.html camp/templates/emissions/area.html camp/templates/emissions/facility-detail.html camp/templates/emissions/sector-detail.html camp/templates/emissions/about.html camp/templates/emissions/includes/toxics-breakdown.html camp/templates/emissions/includes/toxics-caveats.html camp/templates/emissions/includes/hot-spots.html datafiles/data-integrations.yaml camp/api/v2/emissions/geojson.py camp/api/v2/emissions/areas.py camp/apps/emissions/tests/test_views.py camp/apps/emissions/tests/test_facility_page.py camp/api/v2/emissions/tests.py
```

---

### Task 6: The map handles a share unit; styles

**Files:**
- Modify: `assets/js/emissions/facility-map.js`
- Modify: `assets/sass/sjvair/pages/emissions.sass`
- Modify (only if Task 4 Step 5 found it necessary): `assets/js/pesticides/charts.js`

**Interfaces:**
- Consumes the container's `data-unit="share"`, `data-label`, `data-year`, and GeoJSON / area values whose `unit` is `share`.
- Produces: `SHARE_BREAKS = [0.0001, 0.001, 0.01, 0.05]` in `CLASS_BREAKS.share` and `AREA_BREAKS.total.share`; `sharePct(value)`; `valueText(value)`; legend titles `'Share of Valley <label> toxics, <year>'`; the Areas measure forced to `total` for share; popups print percents.

- [ ] **Step 1: Breaks, formatters**

After `var CLASS_BREAKS = …;` add the share classes and change the two tables:

```js
  // A weighted toxics measure has no unit: it's shown as a share of the
  // Valley total, on fixed percent classes (0.01%, 0.1%, 1%, 5% and up).
  var SHARE_BREAKS = [0.0001, 0.001, 0.01, 0.05];
  var CLASS_BREAKS = { tons: [0.1, 1, 10, 100], lbs: [1, 10, 100, 1000], share: SHARE_BREAKS };
  var AREA_BREAKS = {
    density: { tons: [0.01, 0.1, 1, 10], lbs: [0.1, 1, 10, 100] },
    total: { tons: [1, 10, 100, 1000], lbs: [10, 100, 1000, 10000], share: SHARE_BREAKS },
    per_resident: { tons: [0.1, 1, 10, 100], lbs: [1, 10, 100, 1000] },
  };
```

After `function pctRound(...)`, add:

```js
  // A share of the Valley total (0-1) as a percent: '0.01%', '0.1%', '1%',
  // '5%', '24%' -- two significant digits, no trailing zeros.
  function sharePct(value) {
    if (value === null || value === undefined) return '—';
    return String(Number((value * 100).toPrecision(2))) + '%';
  }

  // A data value with its unit as the popups and legends write it.
  function valueText(value, unit) {
    if (unit === 'share') return sharePct(value) + ' of Valley total';
    return quantity(value) + ' ' + escapeHtml(unit) + '/yr';
  }
```

`sizeCircle(r, value, color)` gains a fourth parameter `round` and uses `(round || roundLabel)(...)` for its label; `sizeKeyHtml(max, color, round)` passes it through. `facilityBins(breaks, swatchClass, round)` passes `round` as `M.classes.bins`' fourth argument.

- [ ] **Step 2: Legends and popups**

In `FacilityMap.prototype.legend`: compute `var share = this.data.unit === 'share'; var round = share ? sharePct : undefined;` at the top; pass `round` to `sizeKeyHtml(max, color, round)` in both branches and to `facilityBins(breaks, undefined, round)`; the plain title becomes

```js
    var label = share
      ? 'Share of Valley ' + escapeHtml(this.data.label).toLowerCase() + ' toxics, ' + escapeHtml(String(this.data.year || ''))
      : escapeHtml(this.data.label) + ' (' + escapeHtml(this.data.unit) + '/yr)';
```

and after the `'None reported'` line append, for share only, `'<p class="legend-note">Pounds × OEHHA toxicity, relative to the Valley total. Not a health risk: stack height, weather and distance are ignored.</p>'`.

In `areaLegend`: `var share = data.values.unit === 'share';` and the plain title becomes the same `'Share of Valley … toxics, <year>'` string when `share` (no `/yr` or suffix), `facilityBins(breaks, 'is-area', share ? sharePct : undefined)`; the compare title drops `AREA_SUFFIX` for share.

In `openPopup`: `var value = noneReported ? 'none reported' : valueText(p.value, this.data.unit);` and the compared-year line uses `valueText(p.value_prev, this.data.unit)`.

In `openAreaPopup`: `var share = this.data.unit === 'share';` and `line` becomes

```js
    var line = function (label, value, suffix) {
      return '<p>' + label + ': <strong>' + (value === null || value === undefined ? '—' : valueText(value, self.data.unit) + suffix) + '</strong></p>';
    };
```

and the three measure lines become `line('Total', p.total, '') + (share ? '' : line('Per square mile', p.per_sq_mi, '') + line('Per 1,000 residents', p.per_1k_residents, ''))` (for share, label the first line `'Share of Valley total'` instead of `'Total'`, and `valueText` then already says "of Valley total" — so use `line('Share', p.total, '')`).

- [ ] **Step 3: The measure for a share unit**

In `readViewState`, after `this.measure = this.data.measure || 'density';` add:

```js
    // A weighted toxics measure is a share: only Total means anything (the
    // server renders density and per-resident disabled).
    if (this.data.unit === 'share') this.measure = 'total';
```

In `syncUrl`/`url` handling (the block that writes `measure` into the URL, around `if (areas && this.measure !== 'density') params.set('measure', …)`), nothing changes: `total` is written as usual. In `setMeasure`, add a guard at the top: `if (this.data.unit === 'share' && measure !== 'total') return;`.

`node --check assets/js/emissions/facility-map.js` (and `charts.js` if touched).

- [ ] **Step 4: Styles**

In `assets/sass/sjvair/pages/emissions.sass`, after the `.segment, .swatch` colour block add the breakdown palette (nine steps: eight pollutants and Other, ColorBrewer-ish blues to greys):

```sass
  .toxics-breakdown
    .segment, .swatch
      &.is-toxic-1
        background: #08306b
      &.is-toxic-2
        background: #08519c
      &.is-toxic-3
        background: #2171b5
      &.is-toxic-4
        background: #4292c6
      &.is-toxic-5
        background: #6baed6
      &.is-toxic-6
        background: #9ecae1
      &.is-toxic-7
        background: #c6dbef
      &.is-toxic-8
        background: #deebf7
      &.is-toxic-9
        background: #bdbdbd
  .hazard-dot
    display: inline-block
    width: 0.6rem
    height: 0.6rem
    border-radius: 50%
    background: #d35400
  .hot-spots-values
    dt
      font-weight: 600
      margin-top: 0.5rem
    dd
      margin-left: 0
```

Rebuild the assets:

```
docker compose -f /home/derek/dev/ccac/sjvair.com/docker-compose.yml --project-directory /home/derek/dev/ccac/sjvair.com run --rm -T -v /home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer:/app web invoke vendor bundle styles
```

Commit only source files (check `git -C <worktree> status --short` for what the build wrote; if built bundles are tracked in this repo, include the ones the build changed, as earlier emissions commits did — look at `git -C <worktree> log --stat -1 -- assets/js/emissions/facility-map.js` for the precedent).

- [ ] **Step 5: Commit**

```
git -C <worktree> commit -m "feat(emissions): the facility map shows weighted toxics as a share of the Valley total" -- assets/js/emissions/facility-map.js assets/sass/sjvair/pages/emissions.sass <built files per the precedent> <assets/js/pesticides/charts.js if touched>
```

---

### Task 7: Smoke checks, the full run, deploy notes

**Files:**
- Modify: `scripts/emissions_map_smoke.py` (docstring; new checks before the Dairies block)

**Interfaces:**
- Consumes: `?toxics=1` on the map page, the legend card, a facility popup, the Areas view's measure dropdown; `window.EmissionsFacilityMap.instances()[0]`.

- [ ] **Step 1: Add the toxics checks**

Before the Dairies block (`driver.get(args.base + '/tools/emissions/dairies/…')`), add:

```python
        # Toxics scope: the default is the cancer-weighted share; the legend
        # names it, the popup prints a percent, and the Areas view only
        # offers Total.
        driver.get(args.base + '/tools/emissions/map/?toxics=1')
        check(results, 'toxics map loads (cancer-weighted default)', wait_loaded(driver) and feature_count(driver) > 0)
        legend = driver.execute_script("return document.querySelector('.facility-map-legend').textContent;")
        check(results, 'the legend names the share measure and its year',
              'Share of Valley cancer-weighted toxics' in legend and '%' in legend and 'Not a health risk' in legend, legend[:200])
        check(results, 'the URL carries no pollutant (cancer is the default)', 'pollutant=' not in driver.current_url, driver.current_url)
        # Open the largest facility's popup from its feature.
        popup = driver.execute_script("""
            var m = window.EmissionsFacilityMap.instances()[0];
            var fs = m.map.querySourceFeatures('facilities').filter(function (f) { return f.properties.value > 0; });
            fs.sort(function (a, b) { return b.properties.value - a.properties.value; });
            if (!fs.length) return '';
            m.openPopup(fs[0], fs[0].geometry.coordinates);
            var el = document.querySelector('.facility-popup');
            return el ? el.textContent : '';
        """)
        check(results, 'a popup shows the share as a percent of the Valley total', '% of Valley total' in popup and '#1' in popup, popup[:160])
        driver.get(args.base + '/tools/emissions/map/?toxics=1&view=areas&measure=density')
        check(results, 'areas view for a share forces Total and disables density', wait_areas(driver) and 'measure=' not in driver.current_url.replace('measure=total', '')
              and driver.execute_script("return document.querySelectorAll('.facility-map-measure .dropdown-item.is-disabled').length;") == 2, driver.current_url)
        legend = driver.execute_script("return document.querySelector('.facility-map-legend .legend-title').textContent;")
        check(results, 'the areas legend is the share title', 'Share of Valley cancer-weighted toxics' in legend, legend)
        # One toxic in pounds still works, and the old key redirects to it.
        driver.get(args.base + '/tools/emissions/map/?toxics=1&pollutant=benzene')
        check(results, 'benzene in pounds', wait_loaded(driver) and 'lbs/yr' in driver.execute_script("return document.querySelector('.facility-map-legend').textContent;"))
```

Update the module docstring's summary with one sentence about the toxics checks. Run:

```
/home/derek/.claude/jobs/d44a9b36/tmp/venv/bin/python scripts/emissions_map_smoke.py --base http://localhost:8003
```

Before running, confirm the dev crawl finished (`docker exec $(docker ps --filter publish=8003 --format '{{.Names}}') tail -3 /tmp/import_toxics_2024.log` shows `Done.`) and the dev server picked up the rebuilt assets. Every check must pass; a failing pre-existing check that is unrelated (dairies) is reported, not fixed here.

- [ ] **Step 2: Full test run**

```
$TEST camp -q
```

Everything must pass. A transient failure that passes alone is the shared test DB contention (the memory's note); re-run once before treating it as real. Also `$MANAGE makemigrations --check --dry-run` → "No changes detected".

- [ ] **Step 3: Commit and write the deploy notes**

```
git -C <worktree> commit -m "test(emissions): smoke the weighted toxics map, legend, popup and areas measures" -- scripts/emissions_map_smoke.py
```

Put this in the handoff for the PR description (not in CLAUDE.md):

```
Deploy (in order):
1. `migrate` — creates SourceImport/ToxicPollutant/ToxicEmission, copies the ten named toxic columns (~130k records, under a minute), drops them. Until step 2 the site shows the same ten toxics as before, unweighted.
2. `python manage.py import_health_values --path contable.pdf` — download https://ww2.arb.ca.gov/sites/default/files/classic/toxics/healthval/contable.pdf by hand if the host 503s (`--url` also works). Re-run whenever CARB updates the table (check yearly).
3. One-off dyno: `python manage.py import_toxics --year 2024` (~8,650 requests, ~10 min with 8 workers), then `--year 2023`, `2022`, `2021`, `2020` (the last five years; older years on request). Run it after each year's `import_ceidars` from now on.
4. Caches: both commands bump the explorer cache generation; `CACHE_VERSION` in stats.py was bumped to 2 as well. The facility GeoJSON and area values endpoints are on cache_key_version 3.
Notes: `import_ceidars` no longer fetches the ten per-pollutant CSVs (10 fewer requests per county). `import_carbtac` (pesticides) keeps its own contable parser; folding it onto emissions/contable.py is a later cleanup.
```

## Self-review

- **Spec coverage.** Models (SourceImport, ToxicPollutant with kind/precursor, ToxicEmission, verbose names) — Task 1. Migrations create / copy / drop — Task 1. `import_health_values` with pdfplumber parser, CARB codes, weights, 1150/1151, date, SourceImport — Task 2. `import_toxics` with facdet URL, 8 workers, retry via `fetch_csv`, replace per facility, unknown pollutants, failure isolation, SourceImport — Task 3. Picker order and keys, legacy redirects, `stats.values` as the one source, shares everywhere, disabled Areas measures, share classes, `SMALL_BASELINE_FLOOR['share']`, `toxics_breakdown` — Tasks 4–6. Home bar, facility table with flags and no ammonia, Hot Spots card and copy, region/near-me bar, map legend, About section and integrations, caveat panel — Tasks 5–6. Tests listed in the spec: contable fixture (Task 2), import_toxics (Task 3), data migration (Task 1), stats values/shares/Guardian/ranks/areas/legacy (Tasks 3–5), pages (Task 5), smoke (Task 7). Deploy notes (Task 7).
- **Decisions the implementer should not revisit:** the Valley total includes minor sources; four share breaks; `Cancer-weighted` / `Hazard-weighted` labels; slugs frozen at creation; `stats.clear_caches()` is a generation bump, not `cache.clear()`.
- **Known gaps left for the PR notes:** the smoke script can't check the disabled-measure tooltip text (it asserts the two disabled items); the migration test is a `TransactionTestCase` (slower, runs last); `import_carbtac` still has its own parser.
