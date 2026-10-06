# Emissions Phase 9: Methane — Carbon Mapper sources, digester grants — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put observed methane on the Facility Emissions Explorer. Carbon Mapper's public catalog of methane point sources (about 730 CH4 sources in the Valley's bounding box: plume clusters seen from aircraft and satellite passes since 2016, each with Carbon Mapper's instantaneous emission-rate estimate) is imported monthly into a `MethaneSource` table, each source linked to the nearest CADD dairy and the nearest CEIDARS facility with a trusted point within 1 km. The facility map, the dairy map and the region and dairy-region maps gain a "Methane sources (Carbon Mapper)" overlay; facility pages get a "Methane plumes observed nearby" card; dairy tables, popups and headline tiles say which dairies have an observed source, with a `?methane=1` filter; the oil-gas sector page lists the Valley's oil & gas sources. **Optionally** (Task 7, only if the PDF parses cleanly in an afternoon), CDFA's Dairy Digester Research and Development Program (DDRDP) project list is parsed into `DigesterGrant` rows shown in dairy popups and as county totals. The Carbon Mapper data is served **only to our own pages** (a same-origin GeoJSON view under `/tools/emissions/`, not `/api/2.0/`, no CSV, not in the API docs), every place it shows carries "Data by Carbon Mapper®" and the non-commercial terms, and the licence is recorded on the model and in every import.

**Architecture:**
- **Models.** `MethaneSource` (sqid; `source_name` unique; `gas`; `point`; `ipcc_sector`, `sector_label`; `persistence`; `emission_kg_h`, `uncertainty_kg_h`; `observations`, `detections`; `county` FK; `dairy` FK and `facility` FK, each the nearest within 1 km or null; `distance_m`; `fetched_at`) with the licence and attribution as class constants (`MethaneSource.LICENSE`, `.ATTRIBUTION`, `.LICENSE_URL`, `.HOME_URL`) and a `group` property (livestock / oil-gas / waste / other, from the IPCC sector code) the map colours by. Task 7 adds `DigesterGrant`. One migration each.
- **Import.** `camp/apps/emissions/carbonmapper.py` fetches the sources CSV for the Valley bbox (the one network call, patched in tests), parses it, keeps CH4 rows whose point is inside a covered county (prepared GEOS geometries, no per-row query), resolves the nearest dairy and trusted-point facility with PostGIS (`dwithin` prefilter, `Distance` in metres), upserts on `source_name`, deletes rows no longer returned, writes `SourceImport('carbon-mapper')` with the licence in its notes, and bumps the methane **and** dairies cache generations. Command `import_carbon_mapper [--path CSV]`; monthly task on the `primary` queue under `lock_task`, the Phase 4/7 pattern.
- **Read side.** `camp/apps/emissions/methane.py`: the cache generation (`generation()`, `key()`, `clear_caches()`, the dairies pattern), `stamp()`, `collection()` (the GeoJSON, with `attribution` and `license` in its properties), `near_facility(facility)` (the FK rows, `[]` for oil-gas permit groupings), `oil_gas_sources()`. `dairies.table()` and `dairies.summary()` gain a `methane` annotation, filter and key.
- **Serving.** `GET /tools/emissions/methane/geojson/` (`emissions:methane-geojson`, `methane_views.MethaneGeoJSON`): a Django view, cached under the methane generation, `X-Robots-Tag: noindex`, `Cache-Control: private`. **Not** an `/api/2.0/` endpoint, no CSV, not documented as an API: the provisional ruling on the spec's open question 1 (serve the layer only to our own pages until Carbon Mapper confirms in writing). Popups read the feature's own properties (about 730 features carry everything), so there is no detail endpoint.
- **Map overlay.** One shared module, `assets/js/emissions/methane-overlay.js` (`window.EmissionsMethaneOverlay`), used by both `facility-map.js` and `dairy-map.js`: a `methane` GeoJSON source **with a MapLibre `attribution`** (so the map's attribution control shows "Data by Carbon Mapper®" whenever the layer is on), one circle layer sized by √rate and coloured by group, a legend checkbox row (the wells overlay's markup, Phase 7), `?methane=1|0` in the URL, a popup with the attribution line. Pages pass `methane_url` / `methane` / `methane_default` through `facility_map_config(methane=...)` and `dairy_map_config(methane=...)`; nothing is offered until an import has run (`methane.stamp()`).
- **Pages.** Facility page card; dairy table column, filter checkbox and headline tile; dairy popup block; oil-gas sector page list; About "Methane" section with the caveat and licence line; `datafiles/data-integrations.yaml` entries.

**Tech Stack:** Django 5 / GeoDjango + PostGIS (`dwithin` prefilter in degrees, `Distance` annotation in metres on a geodetic geometry field, `D(m=…)`), prepared GEOS geometries, django-vanilla-views, django-huey (`db_periodic_task`, `lock_task`), `requests`, stdlib `csv`, pdfplumber 0.11 (Task 7, already in `requirements/base.txt`), MapTiler SDK (MapLibre GL) on the map core (`assets/js/maps/`), Bulma + bulma-tooltip, Selenium smoke script.

**Spec:** `docs/superpowers/specs/2026-09-28-emissions-data-expansion-design.md` — read "Shared: SourceImport", "Data model summary", all of "Phase 9" and open question 1 before any task. Research: `.superpowers/research/ammonia-ghg.md` section 3.

## Global Constraints

- **Where to work.** Worktree `/home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer` (`<worktree>` below), on a **new branch stacked on Phase 8's branch** (the chain is phase 1 → 2 → 3 → 4 → 6 → 5 → 7 → 8 → 9): `git -C <worktree> switch -c feature/emissions-methane <phase-8-branch>`. Use absolute paths and `git -C <worktree>` for every git command. Never edit or commit in `/home/derek/dev/ccac/sjvair.com` (the main checkout) or any other worktree. After each commit, verify it with `git -C <worktree> log --oneline -1`.
- **Plan against the post-chain code.** This plan assumes: `SourceImport` and `stats.clear_caches()` (Phase 1); `Facility.point_source`, `Facility.TRUSTED_POINT_SOURCES`, `Facility.has_trusted_point` (Phase 2; if it somehow isn't there, the facility rule falls back to "has a point" — say so in the commit); `camp/apps/emissions/tasks.py` and `tests/test_tasks.py` (Phase 4); `dairy_views.search_filters` returning `enforcement` and `dairies.summary(..., enforcement=None)` (Phase 6); the wells overlay in `facility-map.js`, `views.wells_overlay`, the `.legend-overlay` / `.legend-toggle` styles and `WellsCachedEndpointMixin` (Phase 7). Line numbers quoted here are from before the chain landed; find code by name.
- **Migrations number sequentially along the chain.** Task 1's is `0016_methanesource.py` and Task 7's `0017_digestergrant.py` **if** Phase 8 added exactly one migration (`0015_ghgreport.py`); use whatever number `makemigrations` gives and fix the names in this plan's commit commands accordingly. Run `ls <worktree>/camp/apps/emissions/migrations/` first.
- **Licence (Carbon Mapper, `https://carbonmapper.org/terms`), carried verbatim from the spec:** show "Data by Carbon Mapper®" wherever the data is drawn or listed (map attribution control, the facility and dairy blocks, the About page), linked to `https://carbonmapper.org`; non-commercial use only; redistribution carries the same terms (the GeoJSON's collection `properties` include `"license": "Carbon Mapper non-commercial terms, https://carbonmapper.org/terms"` and `"attribution": "Data by Carbon Mapper®"`); no CSV download of the methane layer; every emission rate is labelled "Carbon Mapper estimate". **Derek must confirm the licence before this ships to production** — Task 6's PR notes say so in their first line, and the PR stays a draft until he does.
- **Tests** use `django.test.TestCase` with plain `assert` (never `self.assertX`); fixtures `regions.yaml`, `emissions.yaml`; `pytest.raises` for exceptions. Tests never hit the network: the fetch (`carbonmapper.fetch_csv`) is patched and every sample file is a small checked-in file under `camp/apps/emissions/tests/data/` (Task 2 Step 2 and Task 7 Step 2 say exactly how to produce them).
- **New models use sqids:** `sqid = SqidsField(alphabet=shuffle_alphabet('emissions.<ModelName>'))` beside the integer PK, as `camp/apps/emissions/models.py` does. Verbose names use `_()` as the first positional argument; don't align `=`.
- **Test command** (`$TEST <paths>` below):
  `docker compose -f /home/derek/dev/ccac/sjvair.com/docker-compose.yml --project-directory /home/derek/dev/ccac/sjvair.com run --rm -T -e DATABASE_URL=postgis://sjvair:changeme@db:5432/sjvair_methane -v /home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer:/app test pytest <paths> -q -p no:cacheprovider --create-db`
  `fatal: not a git repository` in its output is harmless.
- **Management commands against the worktree** (`$MANAGE <args>` below):
  `docker compose -f /home/derek/dev/ccac/sjvair.com/docker-compose.yml --project-directory /home/derek/dev/ccac/sjvair.com run --rm -T -v /home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer:/app web python manage.py <args>`
- **Asset rebuild:** the same prefix as `$MANAGE` but the command is `invoke vendor bundle styles`. Run `node --check` on every JS file touched.
- **Smoke:** `/home/derek/.claude/jobs/d44a9b36/tmp/venv/bin/python scripts/emissions_map_smoke.py --base http://localhost:8003`. The dev server's container is `docker ps --filter publish=8003`; never stop it. It serves this worktree; after Task 1 it needs `migrate` (`docker exec $(docker ps --filter publish=8003 --format '{{.Names}}') python manage.py migrate`), after Task 2 `import_carbon_mapper` (network, under a minute).
- **Commits:** explicit paths only (`git -C <worktree> add <new files>`, then `git -C <worktree> commit -m "…" -- <every path>`). Never `git add -A`, never `git stash`, never push, no AI attribution or Co-Authored-By trailers. Message style: `feat(emissions): …`, `test(emissions): …`, `docs(emissions): …`.
- **Deploy notes go in the PR description, not CLAUDE.md.** Task 6 drafts them; Task 7 appends.
- **Copy, verbatim from the spec** (Phase 9 "What appears where" and "Caveat copy"). Overlay label `Methane sources (Carbon Mapper)`. Facility card title `Methane plumes observed nearby`. Dairy marker `Methane observed`; dairy filter label `With an observed methane source`; headline tile `N with observed methane plumes` (rendered as heading `With observed methane plumes`, title `N`). Popup link `View at Carbon Mapper →` to `https://data.carbonmapper.org/#<lat>,<lng>`. Rates read `<rate> ± <uncertainty> kg/h (Carbon Mapper estimate)`. The caveat panel (Task 6) is the spec's paragraph word for word. Digester grant line (Task 7) `CDFA DDRDP grant, $X (year), estimated N t CO2e/yr reduction`.
- **Decisions made while planning** (the spec is otherwise followed as written):
  1. **No public endpoint.** The spec's `GET /api/2.0/emissions/methane/geojson/` becomes `GET /tools/emissions/methane/geojson/`, an app view for our pages only (the ruling on open question 1). It still carries `license` and `attribution` in the body. If Carbon Mapper later confirms in writing, moving it under `/api/2.0/` is a one-line URL change plus docs.
  2. **CH4 only.** The CSV also lists 37 CO2 sources; the import counts and skips them (`Report.co2`). The `gas` field stays so the model matches the spec and a later import can keep CO2 without a migration.
  3. **The facility link is the FK.** A facility's card lists the sources whose *nearest trusted-point facility* it is (what the import computes), not every source within 1 km; the dairy link likewise. One definition, pinned by tests, no second spatial query on page load.
  4. **Overlay default is off everywhere**, `?methane=1` and the legend checkbox turn it on; it's offered only after an import exists. A facility's own (compact) map offers it too, since its card says a source is nearby.
  5. **Popups read the feature.** No detail endpoint: ~730 features with a dozen properties are under 200 KB.
  6. **Colour groups** from the IPCC code's prefix: `4B` livestock, `1B2` oil & gas, `6A`/`6B` waste, everything else other. The label comes from the same table (`MethaneSource.SECTORS`); an unknown code keeps the code as its label.
  7. **Oil & gas list on the sector page** groups by county and shows the nearest facility where the import matched one (141 of 395 in research), else the coordinates. The spec's "by field name where Carbon Mapper's name carries one" depends on the `source_name` format, which the research didn't record: Task 5 Step 1 says to look at the real sample and add a field-name column only if the names carry one.
  8. **DDRDP is Task 7 and optional**: its own migration, module, command and tests, so dropping it is `git reset` of one commit. Ship criterion in the task.

## Review Focus

- **Attribution and licence are everywhere the data is:** the GeoJSON body (`test_collection_carries_the_licence`, Task 3), the map source's `attribution` and the popup (`smoke`, Task 6), the facility card, the dairy popup and table tooltip, the About page (`test_about_has_the_methane_section`, Task 6), and `SourceImport.notes['license']` on every import (`test_import_records_the_licence`, Task 2). A reviewer should grep the diff for `Carbon Mapper` and find it next to every rendering.
- **Nothing public.** No new path under `camp/api/`, no `format=csv` for methane, no line in the API docs. Pinned by `test_no_api_route` (Task 3), which asserts `reverse('api:v2:emissions:methane-geojson')` raises `NoReverseMatch`.
- **The 1 km rule and the trusted-point rule** are pinned with a boundary case on each side (`test_nearest_within_a_kilometre`, `test_an_untrusted_point_never_matches`, Task 2).
- **Removal is deletion, not orphaning:** a source missing from the feed is deleted and its dairy/facility no longer show it (`test_removed_sources_are_deleted`, Task 2; `test_no_import_shows_nothing`, Task 4).
- **Oil-gas suppression:** an oil-gas facility never renders the card even when the import linked a source to it (`test_card_is_hidden_for_oil_gas_groupings`, Task 5).
- **Both maps share one overlay module** and neither duplicates its layer code (`node --check` both files; the smoke ticks the checkbox on the dairies tab and a region page).

## Task list

1. `MethaneSource`, migration, admin, `methane.py` cache generation and stamp
2. `carbonmapper.py`: fetch, parse, county clip, nearest dairy/facility, apply; `import_carbon_mapper`; monthly task; the sample CSV
3. The read side and the same-origin GeoJSON view
4. Dairies: table column, `?methane=1` filter, headline tile, popup block
5. The facility card, its oil-gas suppression, and the oil-gas sector page list
6. The map overlay (shared module, both maps), About, integrations, smoke, PR notes
7. Optional: `DigesterGrant`, `ddrdp.py`, `import_ddrdp`, popup line and county totals

---

### Task 1: `MethaneSource`, migration, admin, `methane.py` cache generation and stamp

**Files:**
- Modify: `camp/apps/emissions/models.py` (append after the last model Phase 8 added)
- Create: `camp/apps/emissions/migrations/0016_methanesource.py` (generated; see Global Constraints on the number)
- Modify: `camp/apps/emissions/admin.py`
- Create: `camp/apps/emissions/methane.py` (only the generation and `stamp()` for now; Task 3 fills it)
- Modify: `camp/apps/emissions/tests/test_models.py` (append)

**Interfaces:**
- `MethaneSource(sqid, source_name unique, gas, point, ipcc_sector, sector_label, persistence, emission_kg_h, uncertainty_kg_h, observations, detections, county FK, dairy FK null, facility FK null, distance_m, fetched_at)`; `MethaneSource.Gas` (`CH4`, `CO2`); `MethaneSource.Group` (`LIVESTOCK='livestock'`, `OIL_GAS='oil-gas'`, `WASTE='waste'`, `OTHER='other'`); `MethaneSource.SECTORS` (`{ipcc code: (group, label)}`); constants `ATTRIBUTION`, `LICENSE`, `LICENSE_URL`, `HOME_URL`, `VIEWER_URL`; classmethod `sector_for(code) -> (group, label)`; properties `group`, `viewer_url`, `rate_text`.
- `methane.SOURCE = 'carbon-mapper'`, `methane.generation()`, `methane.key(*parts)`, `methane.clear_caches()`, `methane.stamp() -> SourceImport | None`, `methane.enabled() -> bool`.

- [ ] **Step 1: Write the failing tests**

Append to `camp/apps/emissions/tests/test_models.py`:

```python
class MethaneSourceTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def make(self, **overrides):
        from django.contrib.gis.geos import Point
        from camp.apps.emissions.models import MethaneSource
        from camp.apps.regions.models import Region
        values = dict(
            source_name='CH4-test-1', gas='CH4', point=Point(-119.786, 36.736, srid=4326),
            ipcc_sector='4B', sector_label='Livestock', persistence=0.6,
            emission_kg_h=120.0, uncertainty_kg_h=40.0, observations=12, detections=5,
            county=Region.objects.get(type=Region.Type.COUNTY, slug='fresno'),
        )
        values.update(overrides)
        return MethaneSource.objects.create(**values)

    def test_sector_groups_and_labels(self):
        from camp.apps.emissions.models import MethaneSource
        assert MethaneSource.sector_for('4B') == ('livestock', 'Livestock')
        assert MethaneSource.sector_for('1B2') == ('oil-gas', 'Oil & gas')
        assert MethaneSource.sector_for('6A') == ('waste', 'Solid waste')
        assert MethaneSource.sector_for('6B') == ('waste', 'Wastewater')
        assert MethaneSource.sector_for('1B1') == ('other', 'Coal mining')
        assert MethaneSource.sector_for('9Z') == ('other', '9Z')
        assert MethaneSource.sector_for('') == ('other', 'Unknown sector')
        assert self.make().group == 'livestock'
        assert self.make(source_name='x', ipcc_sector='1B2').group == 'oil-gas'

    def test_viewer_url_rate_text_and_licence(self):
        from camp.apps.emissions.models import MethaneSource
        source = self.make()
        assert source.viewer_url == 'https://data.carbonmapper.org/#36.73600,-119.78600'
        assert source.rate_text == '120 ± 40 kg/h'
        assert self.make(source_name='y', uncertainty_kg_h=None).rate_text == '120 kg/h'
        assert self.make(source_name='z', emission_kg_h=None).rate_text == 'rate not estimated'
        assert MethaneSource.ATTRIBUTION == 'Data by Carbon Mapper®'
        assert MethaneSource.LICENSE == 'Carbon Mapper non-commercial terms, https://carbonmapper.org/terms'
        assert MethaneSource.LICENSE_URL == 'https://carbonmapper.org/terms'
        assert source.sqid and str(source) == 'CH4-test-1 (Livestock)'

    def test_methane_generation(self):
        from django.core.cache import cache
        from camp.apps.emissions import methane
        from camp.apps.emissions.models import SourceImport
        cache.clear()
        first = methane.generation()
        assert methane.key('a', 1).endswith(f':{first}:a:1')
        methane.clear_caches()
        assert methane.generation() == first + 1
        assert methane.stamp() is None and not methane.enabled()
        SourceImport.objects.create(source='carbon-mapper')
        assert methane.stamp() is not None and methane.enabled()
```

- [ ] **Step 2: Run to verify failure**

`$TEST camp/apps/emissions/tests/test_models.py::MethaneSourceTests` — `ImportError: cannot import name 'MethaneSource'`.

- [ ] **Step 3: The model**

Append to `camp/apps/emissions/models.py`:

```python
class MethaneSource(models.Model):
    """
    A methane point source in Carbon Mapper's public catalog: the durable
    cluster of plumes seen at one spot across aircraft and satellite passes
    since 2016, with Carbon Mapper's estimate of its emission rate. Each rate
    is an instantaneous estimate with wide uncertainty, not an annual total,
    and a site with no source hasn't been shown to be clean (see the About
    page's Methane section). Refreshed monthly by import_carbon_mapper,
    which links each source to the nearest CADD dairy and the nearest
    CEIDARS facility with a trusted point within 1 km.

    Licence: Carbon Mapper's custom non-commercial terms (LICENSE). The data
    is shown only on our own pages, never re-licensed or offered as a
    download, and every rendering carries ATTRIBUTION.
    """

    ATTRIBUTION = 'Data by Carbon Mapper®'
    LICENSE = 'Carbon Mapper non-commercial terms, https://carbonmapper.org/terms'
    LICENSE_URL = 'https://carbonmapper.org/terms'
    HOME_URL = 'https://carbonmapper.org'
    VIEWER_URL = 'https://data.carbonmapper.org/#{lat:.5f},{lng:.5f}'

    class Gas(models.TextChoices):
        CH4 = 'CH4', _('Methane')
        CO2 = 'CO2', _('Carbon dioxide')

    class Group(models.TextChoices):
        LIVESTOCK = 'livestock', _('Livestock')
        OIL_GAS = 'oil-gas', _('Oil & gas')
        WASTE = 'waste', _('Waste & wastewater')
        OTHER = 'other', _('Other')

    # IPCC 2006 source categories as Carbon Mapper codes them, longest
    # prefix wins: the map's colour group and the label shown for the sector.
    SECTORS = {
        '4B': (Group.LIVESTOCK, 'Livestock'),
        '1B2': (Group.OIL_GAS, 'Oil & gas'),
        '1B1': (Group.OTHER, 'Coal mining'),
        '1A1': (Group.OTHER, 'Energy industries'),
        '1A2': (Group.OTHER, 'Manufacturing & construction'),
        '6A': (Group.WASTE, 'Solid waste'),
        '6B': (Group.WASTE, 'Wastewater'),
        '4C': (Group.OTHER, 'Rice cultivation'),
    }

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.MethaneSource'))
    source_name = models.CharField(_('Source name'), max_length=64, unique=True)
    gas = models.CharField(_('Gas'), max_length=3, choices=Gas.choices, db_index=True)
    point = models.PointField(_('Point'))
    ipcc_sector = models.CharField(_('IPCC sector'), max_length=8, blank=True)
    sector_label = models.CharField(_('Sector'), max_length=32, blank=True)
    persistence = models.FloatField(_('Persistence'), null=True, blank=True)
    emission_kg_h = models.FloatField(_('Emission rate (kg/h)'), null=True, blank=True)
    uncertainty_kg_h = models.FloatField(_('Emission uncertainty (kg/h)'), null=True, blank=True)
    observations = models.IntegerField(_('Observation dates'), default=0)
    detections = models.IntegerField(_('Detection dates'), default=0)
    county = models.ForeignKey('regions.Region', verbose_name=_('County'), on_delete=models.PROTECT, related_name='methane_sources')
    dairy = models.ForeignKey(Dairy, verbose_name=_('Nearest dairy'), null=True, blank=True, on_delete=models.SET_NULL, related_name='methane_sources')
    facility = models.ForeignKey(Facility, verbose_name=_('Nearest facility'), null=True, blank=True, on_delete=models.SET_NULL, related_name='methane_sources')
    distance_m = models.FloatField(_('Distance to the match (m)'), null=True, blank=True)
    fetched_at = models.DateTimeField(_('Fetched at'), auto_now=True)

    class Meta:
        ordering = [F('emission_kg_h').desc(nulls_last=True), 'source_name']
        indexes = [models.Index(fields=['county', 'gas'])]

    def __str__(self):
        return f'{self.source_name} ({self.sector_label or self.ipcc_sector or "?"})'

    @classmethod
    def sector_for(cls, code):
        """(group, label) for an IPCC code: the longest listed prefix, else other with the code itself as the label."""
        code = (code or '').strip().upper()
        if not code:
            return cls.Group.OTHER, 'Unknown sector'
        for prefix in sorted(cls.SECTORS, key=len, reverse=True):
            if code.startswith(prefix):
                return cls.SECTORS[prefix]
        return cls.Group.OTHER, code

    @property
    def group(self):
        return self.sector_for(self.ipcc_sector)[0]

    @property
    def viewer_url(self):
        return self.VIEWER_URL.format(lat=self.point.y, lng=self.point.x)

    @property
    def rate_text(self):
        """`120 ± 40 kg/h`; without an uncertainty `120 kg/h`; without a rate `rate not estimated`. Always shown beside "Carbon Mapper estimate"."""
        if self.emission_kg_h is None:
            return 'rate not estimated'
        text = f'{self.emission_kg_h:,.0f}'
        if self.uncertainty_kg_h is not None:
            text += f' ± {self.uncertainty_kg_h:,.0f}'
        return f'{text} kg/h'
```

(`F` is already imported in `models.py` for the dairies queryset; check the import line.) The `sector_for` test for `'6B'` expects `'Wastewater'` and for `'6A'` `'Solid waste'` — both are `Group.WASTE`; `test_sector_groups_and_labels` compares against the string values, which `TextChoices` members equal.

- [ ] **Step 4: Migration and admin**

`$MANAGE makemigrations emissions -n methanesource`; confirm the file is `0016_methanesource.py` (or note the real number) and read it once: one `CreateModel`, the two FKs, the index.

In `admin.py`, import `MethaneSource` and append:

```python
@admin.register(MethaneSource)
class MethaneSourceAdmin(ReadOnlyAdminMixin, base_admin.ModelAdmin):
    list_display = ['source_name', 'gas', 'sector_label', 'emission_kg_h', 'uncertainty_kg_h', 'persistence', 'detections', 'observations', 'county', 'dairy', 'facility', 'distance_m', 'fetched_at']
    list_filter = ['gas', 'sector_label', 'county']
    search_fields = ['source_name', 'dairy__name', 'facility__name']
    raw_id_fields = ['dairy', 'facility']
```

- [ ] **Step 5: `methane.py`, the generation only**

Create `camp/apps/emissions/methane.py`:

```python
"""
The read side of Carbon Mapper's methane sources (carbonmapper.py writes
them): the GeoJSON our maps draw, the facility card's rows, the oil & gas
list. Everything is cached a day under a generation number that
import_carbon_mapper bumps (clear_caches), the dairies pattern. The data is
Carbon Mapper's, under its non-commercial terms: every dict leaving this
module that reaches a page carries MethaneSource.ATTRIBUTION.
"""
import time

from django.core.cache import cache

from camp.apps.emissions.models import MethaneSource, SourceImport

SOURCE = 'carbon-mapper'
CACHE_VERSION = 1
GENERATION_KEY = 'emissions:methane:generation'
CACHE_TIMEOUT = 60 * 60 * 24


def generation():
    value = cache.get(GENERATION_KEY)
    if value is None:
        value = int(time.time())
        cache.set(GENERATION_KEY, value, None)
    return value


def clear_caches():
    """Orphan every cached methane aggregate and the GeoJSON: they're keyed under the generation."""
    cache.set(GENERATION_KEY, generation() + 1, None)


def key(*parts):
    return ':'.join(str(part) for part in (f'emissions:methane:v{CACHE_VERSION}', generation(), *parts))


def stamp():
    return SourceImport.latest(SOURCE)


def enabled():
    """Whether anything methane is offered: only after an import has run."""
    return stamp() is not None
```

- [ ] **Step 6: Run, migrate the dev server, commit**

`$TEST camp/apps/emissions/tests/test_models.py` — all pass; `$MANAGE makemigrations --check --dry-run` → no changes. Then `docker exec $(docker ps --filter publish=8003 --format '{{.Names}}') python manage.py migrate`.

```bash
git -C <worktree> add camp/apps/emissions/migrations/0016_methanesource.py camp/apps/emissions/methane.py
git -C <worktree> commit -m "feat(emissions): MethaneSource model for Carbon Mapper's methane point sources" -- camp/apps/emissions/models.py camp/apps/emissions/migrations/0016_methanesource.py camp/apps/emissions/admin.py camp/apps/emissions/methane.py camp/apps/emissions/tests/test_models.py
```

---

### Task 2: `carbonmapper.py`: fetch, parse, county clip, nearest dairy/facility, apply; `import_carbon_mapper`; monthly task; the sample CSV

**Files:**
- Create: `camp/apps/emissions/carbonmapper.py`
- Create: `camp/apps/emissions/management/commands/import_carbon_mapper.py`
- Modify: `camp/apps/emissions/tasks.py` (append)
- Create: `camp/apps/emissions/tests/data/carbon-mapper-sources.csv` (real, trimmed; Step 2)
- Create: `camp/apps/emissions/tests/test_carbonmapper.py`; modify `camp/apps/emissions/tests/test_tasks.py` (append)

**Interfaces:**
- `carbonmapper.URL`, `carbonmapper.BBOX = (-121.6, 34.8, -118.5, 38.3)`, `carbonmapper.SOURCE = 'carbon-mapper'`, `carbonmapper.MATCH_METERS = 1000`, `carbonmapper.COARSE_DEGREES = 0.012`, `carbonmapper.COLUMNS` (the ten CSV columns), `carbonmapper.CarbonMapperError`.
- `carbonmapper.fetch_csv() -> str` (network; tests patch it), `carbonmapper.read_rows(text) -> list[dict]` (validates the header), `carbonmapper.parse_row(row) -> dict | None`, `carbonmapper.county_index() -> list[(Region, prepared geometry)]`, `carbonmapper.county_for(point, index) -> Region | None`, `carbonmapper.nearest(queryset, point) -> (pk | None, metres | None)`, `carbonmapper.trusted_facilities() -> QuerySet`, `carbonmapper.apply(rows) -> Report`.
- `Report(fetched, co2, outside, skipped, created, updated, deleted, dairy_matches, facility_matches)` with `lines()`.
- Command `import_carbon_mapper [--path CSV]`; task `tasks.import_carbon_mapper`: `db_periodic_task(crontab(day='4', hour='11', minute='0'), priority=20)` under `lock_task('import-carbon-mapper')`.

- [ ] **Step 1: Write the failing tests**

Create `camp/apps/emissions/tests/test_carbonmapper.py`:

```python
"""
data/carbon-mapper-sources.csv is the header and the first eight data rows
of the real sources CSV for the Valley bbox, fetched 2026-09-28 (Task 2
Step 2). It pins the column names and value shapes; the match tests build
their own rows near the fixture's facilities and dairies with `row()`.
"""
import csv
import io
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from camp.apps.emissions import carbonmapper, dairies, methane
from camp.apps.emissions.models import Facility, MethaneSource, SourceImport
from camp.apps.emissions.tests.test_dairies import make_dairies
from camp.apps.regions.models import Region

SAMPLE = Path(__file__).parent / 'data' / 'carbon-mapper-sources.csv'

# TEST PLANT is at (-119.787, 36.737), BIG DAIRY at (-119.785, 36.735).
NEAR_BOTH = (-119.786, 36.736)          # ~130 m from each
JUST_INSIDE = (-119.785, 36.7435)       # 0.0085° north of BIG DAIRY: ~945 m
JUST_OUTSIDE = (-119.785, 36.7445)      # 0.0095° north: ~1,056 m
AT_GAS_STATION = (-119.018, 35.373)     # TEST GAS STATION (untrusted point); SMALL DAIRY is ~380 m away
OFFSHORE = (-121.0, 34.9)               # inside the bbox, outside every covered county


def row(name='CH4-test-1', lnglat=NEAR_BOTH, gas='CH4', sector='4B', rate='120.5', unc='40.2', **overrides):
    values = {
        'source_name': name, 'source_latitude': str(lnglat[1]), 'source_longitude': str(lnglat[0]), 'gas': gas,
        'observation_date_count': '12', 'detection_date_count': '5', 'source_persistence': '0.4167',
        'source_emission': rate, 'source_emission_uncertainty': unc, 'ipcc_sector': sector,
    }
    values.update(overrides)
    return values


def csv_text(rows):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(carbonmapper.COLUMNS))
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


class ParseTests(TestCase):
    def test_the_real_file(self):
        rows = carbonmapper.read_rows(SAMPLE.read_text())
        assert len(rows) == 8
        parsed = [carbonmapper.parse_row(r) for r in rows]
        assert all(p is not None for p in parsed)
        first = parsed[0]
        assert set(first) == {'source_name', 'gas', 'point', 'ipcc_sector', 'sector_label', 'persistence',
                              'emission_kg_h', 'uncertainty_kg_h', 'observations', 'detections'}
        assert first['point'].srid == 4326 and -122 < first['point'].x < -118 and 34 < first['point'].y < 39
        assert {p['gas'] for p in parsed} <= {'CH4', 'CO2'}
        assert all(isinstance(p['observations'], int) and p['observations'] >= p['detections'] for p in parsed)

    def test_parse_row_shapes(self):
        parsed = carbonmapper.parse_row(row())
        assert parsed['emission_kg_h'] == 120.5 and parsed['uncertainty_kg_h'] == 40.2
        assert (parsed['ipcc_sector'], parsed['sector_label']) == ('4B', 'Livestock')
        assert (parsed['observations'], parsed['detections']) == (12, 5)
        assert carbonmapper.parse_row(row(rate='', unc=''))['emission_kg_h'] is None
        assert carbonmapper.parse_row(row(name='')) is None
        assert carbonmapper.parse_row(row(source_latitude='x')) is None
        assert carbonmapper.parse_row(row(lnglat=(0, 0))) is None

    def test_a_wrong_header_is_an_error(self):
        with pytest.raises(carbonmapper.CarbonMapperError, match='source_emission'):
            carbonmapper.read_rows('source_name,gas\nCH4-1,CH4\n')


class ApplyTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.big, self.small, self.closed = make_dairies()
        self.plant = Facility.objects.get(name='TEST PLANT')
        self.plant.point_source = Facility.PointSource.CENSUS
        self.plant.save()

    def test_import_creates_links_and_records_the_licence(self):
        report = carbonmapper.apply([row()])
        source = MethaneSource.objects.get(source_name='CH4-test-1')
        assert source.county.slug == 'fresno'
        assert source.dairy == self.big and source.facility == self.plant
        assert 100 < source.distance_m < 200
        assert (report.created, report.dairy_matches, report.facility_matches) == (1, 1, 1)
        stamp = SourceImport.latest('carbon-mapper')
        assert stamp.notes['license'] == MethaneSource.LICENSE
        assert stamp.notes['attribution'] == MethaneSource.ATTRIBUTION
        assert stamp.notes['sources'] == 1

    def test_nearest_within_a_kilometre(self):
        carbonmapper.apply([row(name='in', lnglat=JUST_INSIDE), row(name='out', lnglat=JUST_OUTSIDE)])
        inside, outside = MethaneSource.objects.get(source_name='in'), MethaneSource.objects.get(source_name='out')
        assert inside.dairy == self.big and 900 < inside.distance_m < 1000
        assert outside.dairy is None and outside.facility is None and outside.distance_m is None

    def test_an_untrusted_point_never_matches(self):
        # TEST GAS STATION has a point but point_source '' (untrusted): the source keeps the dairy only.
        carbonmapper.apply([row(name='gs', lnglat=AT_GAS_STATION, sector='1B2')])
        source = MethaneSource.objects.get(source_name='gs')
        assert source.facility is None and source.dairy == self.small and source.county.slug == 'kern'
        Facility.objects.filter(name='TEST GAS STATION').update(point_source=Facility.PointSource.CARB)
        carbonmapper.apply([row(name='gs', lnglat=AT_GAS_STATION, sector='1B2')])
        assert MethaneSource.objects.get(source_name='gs').facility.name == 'TEST GAS STATION'

    def test_clip_co2_and_duplicates(self):
        report = carbonmapper.apply([
            row(), row(name='co2', gas='CO2'), row(name='off', lnglat=OFFSHORE), row(name='CH4-test-1', rate='1'),
        ])
        assert MethaneSource.objects.count() == 1
        assert (report.fetched, report.co2, report.outside, report.skipped) == (4, 1, 1, 1)
        assert MethaneSource.objects.get().emission_kg_h == 120.5  # the first of a duplicated name wins

    def test_removed_sources_are_deleted_and_updates_land(self):
        carbonmapper.apply([row(name='a'), row(name='b', lnglat=JUST_INSIDE)])
        assert MethaneSource.objects.count() == 2
        report = carbonmapper.apply([row(name='a', rate='200', detection_date_count='7')])
        assert (report.updated, report.deleted) == (1, 1)
        a = MethaneSource.objects.get()
        assert a.source_name == 'a' and a.emission_kg_h == 200 and a.detections == 7

    def test_import_bumps_both_generations(self):
        before = (methane.generation(), dairies.generation())
        carbonmapper.apply([row()])
        assert methane.generation() == before[0] + 1 and dairies.generation() == before[1] + 1


class CommandTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        make_dairies()

    def test_fetches_and_reports(self):
        with patch('camp.apps.emissions.carbonmapper.fetch_csv', return_value=csv_text([row(), row(name='co2', gas='CO2')])):
            call_command('import_carbon_mapper')
        assert MethaneSource.objects.count() == 1

    def test_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'sources.csv')
            Path(path).write_text(csv_text([row(name='p')]))
            call_command('import_carbon_mapper', path=path)
        assert MethaneSource.objects.filter(source_name='p').exists()

    def test_an_empty_feed_changes_nothing(self):
        carbonmapper.apply([row()])
        with patch('camp.apps.emissions.carbonmapper.fetch_csv', return_value=csv_text([])):
            with pytest.raises(CommandError, match='no sources'):
                call_command('import_carbon_mapper')
        assert MethaneSource.objects.count() == 1
```

Append to `camp/apps/emissions/tests/test_tasks.py`:

```python
class ImportCarbonMapperTaskTests(TestCase):
    @patch('camp.apps.emissions.tasks.call_command')
    def test_runs_the_command_under_the_lock(self, call_command):
        tasks.import_carbon_mapper.call_local()
        call_command.assert_called_once_with('import_carbon_mapper')
```

- [ ] **Step 2: The real sample file**

The header and the first eight data rows of the real CSV, so the parser is tested against Carbon Mapper's column names and value shapes:

```bash
curl -sS 'https://api.carbonmapper.org/api/v1/catalog/sources-csv?bbox=-121.6&bbox=34.8&bbox=-118.5&bbox=38.3' \
  | head -n 9 > /home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer/camp/apps/emissions/tests/data/carbon-mapper-sources.csv
head -n 2 /home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer/camp/apps/emissions/tests/data/carbon-mapper-sources.csv
```

Read the two printed lines. The header must be exactly the ten `COLUMNS` below (in any order); if Carbon Mapper renamed one, change `COLUMNS` to the real name and say so in the commit. Note the `source_name` format for Task 5 (does it carry a field or site name, or is it an opaque id?). If the first eight rows are all one gas or one sector that's fine — `test_the_real_file` only asserts shapes. (`tests/data/` exists from Phase 1; if it doesn't, create it.)

- [ ] **Step 3: `carbonmapper.py`**

```python
"""
Carbon Mapper's public catalog of methane point sources, for the Valley
bbox: fetch the sources CSV, keep the CH4 sources inside a covered county,
link each to the nearest CADD dairy and the nearest CEIDARS facility with a
trusted point within MATCH_METERS, and write MethaneSource rows. methane.py
is the read side.

Licence: custom non-commercial terms (MethaneSource.LICENSE). Every import
records them in SourceImport.notes; the pages carry the attribution.
"""
import csv
import io
import math
from dataclasses import dataclass
from datetime import date

import requests
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.db import transaction

from camp.apps.emissions.models import Dairy, Facility, MethaneSource, SourceImport
from camp.apps.regions.models import Region

URL = 'https://api.carbonmapper.org/api/v1/catalog/sources-csv'
BBOX = (-121.6, 34.8, -118.5, 38.3)
SOURCE = 'carbon-mapper'
MATCH_METERS = 1000
# The index prefilter around a source, in degrees (a little over 1 km of latitude).
COARSE_DEGREES = 0.012
COLUMNS = (
    'source_name', 'source_latitude', 'source_longitude', 'gas', 'observation_date_count',
    'detection_date_count', 'source_persistence', 'source_emission', 'source_emission_uncertainty', 'ipcc_sector',
)
FIELDS = ('gas', 'point', 'ipcc_sector', 'sector_label', 'persistence', 'emission_kg_h', 'uncertainty_kg_h',
          'observations', 'detections', 'county', 'dairy', 'facility', 'distance_m')


class CarbonMapperError(Exception):
    pass


def fetch_csv():
    """The sources CSV for BBOX (requests repeats `bbox` for each value, as the API expects). The one network call; tests patch it."""
    response = requests.get(URL, params={'bbox': list(BBOX)}, timeout=120)
    response.raise_for_status()
    return response.text


def read_rows(text):
    reader = csv.DictReader(io.StringIO(text))
    missing = [column for column in COLUMNS if column not in (reader.fieldnames or [])]
    if missing:
        raise CarbonMapperError(f'sources CSV is missing columns: {", ".join(missing)}')
    return list(reader)


def _float(value):
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int(value):
    number = _float(value)
    return int(number) if number is not None else 0


def parse_row(row):
    """A MethaneSource's field values (county and links left to apply), or None without a name or usable coordinates."""
    name = (row.get('source_name') or '').strip()[:64]
    lat, lng = _float(row.get('source_latitude')), _float(row.get('source_longitude'))
    if not name or lat is None or lng is None or not (-90 <= lat <= 90 and -180 <= lng <= 180) or (lat == 0 and lng == 0):
        return None
    code = (row.get('ipcc_sector') or '').strip().upper()[:8]
    group, label = MethaneSource.sector_for(code)
    return {
        'source_name': name,
        'gas': (row.get('gas') or '').strip().upper()[:3],
        'point': Point(lng, lat, srid=4326),
        'ipcc_sector': code,
        'sector_label': label[:32],
        'persistence': _float(row.get('source_persistence')),
        'emission_kg_h': _float(row.get('source_emission')),
        'uncertainty_kg_h': _float(row.get('source_emission_uncertainty')),
        'observations': _int(row.get('observation_date_count')),
        'detections': _int(row.get('detection_date_count')),
    }


def county_index():
    """[(Region, prepared geometry)] for the covered counties: ~730 point-in-polygon tests run in GEOS, not SQL."""
    return [(region, region.boundary.geometry.prepared) for region in Region.objects.counties().select_related('boundary') if region.boundary]


def county_for(point, index):
    for region, prepared in index:
        if prepared.contains(point):
            return region
    return None


def nearest(queryset, point):
    """(pk, metres) of the queryset's nearest row within MATCH_METERS of `point`, or (None, None). `point` is the model's PointField name."""
    match = (
        queryset.filter(point__dwithin=(point, COARSE_DEGREES), point__distance_lte=(point, D(m=MATCH_METERS)))
        .annotate(metres=Distance('point', point)).order_by('metres').values_list('pk', 'metres').first()
    )
    if match is None:
        return None, None
    return match[0], match[1].m


def trusted_facilities():
    """Facilities whose point can be trusted to be the site (Phase 2's rule), never an address geocode or a legacy point."""
    return Facility.objects.filter(point__isnull=False, point_source__in=Facility.TRUSTED_POINT_SOURCES)


@dataclass
class Report:
    fetched: int = 0
    co2: int = 0
    outside: int = 0
    skipped: int = 0
    created: int = 0
    updated: int = 0
    deleted: int = 0
    dairy_matches: int = 0
    facility_matches: int = 0

    def lines(self):
        return [
            f'Carbon Mapper: {self.fetched:,} rows; {self.co2:,} CO2 skipped, {self.outside:,} outside the covered counties, '
            f'{self.skipped:,} unparseable or duplicate.',
            f'{self.created:,} sources created, {self.updated:,} updated, {self.deleted:,} removed (no longer in the catalog); '
            f'{self.dairy_matches:,} linked to a dairy and {self.facility_matches:,} to a facility within {MATCH_METERS:,} m.',
        ]


def apply(rows):
    """
    Upsert every CH4 source inside a covered county on `source_name`, delete
    the rest, stamp SourceImport(SOURCE) with the licence, and bump the
    methane and dairies cache generations (the dairy table's methane column
    is cached under the dairies one). `rows` is the whole bbox: a partial
    list would delete the rest.
    """
    from camp.apps.emissions import dairies, methane

    report = Report(fetched=len(rows))
    index = county_index()
    facilities = trusted_facilities()
    with transaction.atomic():
        existing = {source.source_name: source for source in MethaneSource.objects.all()}
        seen = set()
        for raw in rows:
            values = parse_row(raw)
            if values is None or values['source_name'] in seen:
                report.skipped += 1
                continue
            if values['gas'] != MethaneSource.Gas.CH4:
                report.co2 += 1
                continue
            county = county_for(values['point'], index)
            if county is None:
                report.outside += 1
                continue
            seen.add(values['source_name'])
            values['county'] = county
            dairy_pk, dairy_m = nearest(Dairy.objects.all(), values['point'])
            facility_pk, facility_m = nearest(facilities, values['point'])
            values['dairy_id'] = dairy_pk
            values['facility_id'] = facility_pk
            distances = [m for m in (dairy_m, facility_m) if m is not None]
            values['distance_m'] = min(distances) if distances else None
            report.dairy_matches += dairy_pk is not None
            report.facility_matches += facility_pk is not None
            source = existing.get(values['source_name'])
            if source is None:
                MethaneSource.objects.create(**values)
                report.created += 1
            else:
                for field, value in values.items():
                    setattr(source, field, value)
                source.save()
                report.updated += 1
        report.deleted, _ = MethaneSource.objects.exclude(source_name__in=seen).delete()
        SourceImport.objects.create(
            source=SOURCE, data_through=date.today(),
            notes={
                'license': MethaneSource.LICENSE, 'license_url': MethaneSource.LICENSE_URL,
                'attribution': MethaneSource.ATTRIBUTION, 'sources': len(seen),
                'created': report.created, 'updated': report.updated, 'deleted': report.deleted,
                'dairy_matches': report.dairy_matches, 'facility_matches': report.facility_matches,
            },
        )
    methane.clear_caches()
    dairies.clear_caches()
    return report
```

Notes for the implementer: `Distance('point', point)` on a geodetic `PointField` returns metres on PostGIS (`ST_DistanceSphere`), and `distance_lte` with `D(m=…)` uses the same; `dwithin` in degrees is only the index prefilter (as `areas._within` does with a bbox). `setattr(source, 'dairy_id', …)` and `'facility_id'` work because the dict uses the `_id` names; `MethaneSource.objects.create(**values)` accepts them too. The duplicate test expects the *first* row of a duplicated name to win: the `seen` check is before the upsert, so the second is `skipped`.

- [ ] **Step 4: The command and the task**

`camp/apps/emissions/management/commands/import_carbon_mapper.py`:

```python
from pathlib import Path

import requests
from django.core.management.base import BaseCommand, CommandError

from camp.apps.emissions import carbonmapper


class Command(BaseCommand):
    help = (
        "Import Carbon Mapper's methane point sources for the Valley bbox (about 730; under a minute). Keeps CH4 sources inside "
        'the covered counties, links each to the nearest dairy and trusted-point facility within 1 km, removes sources no longer '
        'in the catalog. Idempotent. Data under Carbon Mapper\'s non-commercial terms (https://carbonmapper.org/terms). '
        '--path reads a saved sources CSV instead of the API.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--path', help='A saved sources CSV to import instead of fetching')

    def handle(self, *args, **options):
        try:
            text = Path(options['path']).read_text() if options['path'] else carbonmapper.fetch_csv()
            rows = carbonmapper.read_rows(text)
        except (carbonmapper.CarbonMapperError, OSError, requests.RequestException) as exc:
            raise CommandError(f'Carbon Mapper: {exc}')
        if not rows:
            raise CommandError('Carbon Mapper returned no sources; nothing changed.')
        report = carbonmapper.apply(rows)
        for line in report.lines():
            self.stdout.write(line)
```

Append to `camp/apps/emissions/tasks.py` (the imports exist from Phase 4):

```python
# Carbon Mapper publishes new plumes continuously; monthly keeps the layer
# current without leaning on their API. The 4th at 11:00 UTC.
@db_periodic_task(crontab(day='4', hour='11', minute='0'), priority=20)
def import_carbon_mapper():
    with get_queue('primary').lock_task('import-carbon-mapper'):
        call_command('import_carbon_mapper')
```

- [ ] **Step 5: Run, load the dev server, commit**

`$TEST camp/apps/emissions/tests/test_carbonmapper.py camp/apps/emissions/tests/test_tasks.py camp/apps/emissions/tests/test_models.py` — all pass. If `test_nearest_within_a_kilometre` fails on the boundary rows, print `distance_m` for both: the metres must be ~945 and ~1,056; if `Distance` came back in degrees (a value under 1), the field isn't geodetic in your migration — check `PointField` has no `geography=True` and no odd SRID, and that `.m` was read.

Then `docker exec $(docker ps --filter publish=8003 --format '{{.Names}}') python manage.py import_carbon_mapper` (expect roughly 700 sources, ~270 dairy links, ~140 facility links; fewer facility links if `import_carb_locations` hasn't run on the dev DB since Phase 2 — say the counts in the commit message).

```bash
git -C <worktree> add camp/apps/emissions/carbonmapper.py camp/apps/emissions/management/commands/import_carbon_mapper.py camp/apps/emissions/tests/data/carbon-mapper-sources.csv camp/apps/emissions/tests/test_carbonmapper.py
git -C <worktree> commit -m "feat(emissions): import Carbon Mapper's methane sources monthly, linked to dairies and facilities" -- camp/apps/emissions/carbonmapper.py camp/apps/emissions/management/commands/import_carbon_mapper.py camp/apps/emissions/tasks.py camp/apps/emissions/tests/data/carbon-mapper-sources.csv camp/apps/emissions/tests/test_carbonmapper.py camp/apps/emissions/tests/test_tasks.py
```

---

### Task 3: The read side and the same-origin GeoJSON view

**Files:**
- Modify: `camp/apps/emissions/methane.py` (append)
- Create: `camp/apps/emissions/methane_views.py`
- Modify: `camp/apps/emissions/urls.py`
- Create: `camp/apps/emissions/tests/test_methane.py`

**Interfaces:**
- `methane.sources() -> QuerySet` (CH4 rows, `select_related('county', 'dairy', 'facility')`).
- `methane.feature(source) -> dict`: `id` = sqid, Point rounded to 5 places, `properties` = `{id, name, group, sector, rate, unc, rate_text, persistence, obs, det, county, dairy: {id, name} | None, facility: {id, name, url} | None, viewer_url}`.
- `methane.collection() -> dict`: FeatureCollection, `properties` = `{sources, imported (ISO date | None), attribution, license, license_url, home_url}`; cached under `key('geojson')`.
- `methane.near_facility(facility) -> list[MethaneSource]`: the facility's linked CH4 sources by distance; `[]` when `facility.sector == Facility.Sector.OIL_GAS` (a permit grouping's point is an address). Cached under `key('facility', pk)`.
- `methane.for_dairy(dairy) -> list[MethaneSource]` (linked rows, by `-emission_kg_h`; not cached: one popup at a time).
- `methane.oil_gas_sources() -> list[dict]`: every `Group.OIL_GAS` source as `{source, county, facility}` ordered by county name then rate desc; cached under `key('oil-gas')`.
- `methane.attribution() -> dict` = `{'text': ATTRIBUTION, 'url': HOME_URL, 'license': LICENSE, 'license_url': LICENSE_URL}` (templates read it).
- `GET /tools/emissions/methane/geojson/` → `emissions:methane-geojson` (`methane_views.MethaneGeoJSON`), JSON of `collection()`, headers `Cache-Control: private, max-age=3600`, `X-Robots-Tag: noindex`; 404 before any import.

- [ ] **Step 1: Write the failing tests**

Create `camp/apps/emissions/tests/test_methane.py`:

```python
from django.core.cache import cache
from django.test import TestCase
from django.urls import NoReverseMatch, reverse

from camp.apps.emissions import carbonmapper, methane
from camp.apps.emissions.models import Facility, MethaneSource
from camp.apps.emissions.tests.test_carbonmapper import AT_GAS_STATION, JUST_OUTSIDE, NEAR_BOTH, row
from camp.apps.emissions.tests.test_dairies import make_dairies


class MethaneTestCase(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.big, self.small, self.closed = make_dairies()
        self.plant = Facility.objects.get(name='TEST PLANT')
        Facility.objects.filter(pk=self.plant.pk).update(point_source=Facility.PointSource.CENSUS)
        Facility.objects.filter(name='TEST GAS STATION').update(point_source=Facility.PointSource.CARB, sector=Facility.Sector.OIL_GAS)
        carbonmapper.apply([
            row(name='near', lnglat=NEAR_BOTH),
            row(name='lone', lnglat=JUST_OUTSIDE, sector='6A', rate='30', unc='9'),
            row(name='og', lnglat=AT_GAS_STATION, sector='1B2', rate='500', unc='150'),
        ])
        self.near = MethaneSource.objects.get(source_name='near')


class CollectionTests(MethaneTestCase):
    def test_collection_carries_the_licence(self):
        body = methane.collection()
        assert body['type'] == 'FeatureCollection' and body['properties']['sources'] == 3
        assert body['properties']['attribution'] == 'Data by Carbon Mapper®'
        assert body['properties']['license'] == 'Carbon Mapper non-commercial terms, https://carbonmapper.org/terms'
        assert body['properties']['license_url'] == 'https://carbonmapper.org/terms'
        assert body['properties']['imported'] is not None

    def test_features(self):
        by_name = {f['properties']['name']: f for f in methane.collection()['features']}
        near = by_name['near']
        assert near['id'] == self.near.sqid and near['geometry'] == {'type': 'Point', 'coordinates': [-119.786, 36.736]}
        p = near['properties']
        assert (p['group'], p['sector'], p['rate'], p['unc'], p['obs'], p['det']) == ('livestock', 'Livestock', 120.5, 40.2, 12, 5)
        assert p['rate_text'] == '120 ± 40 kg/h' and p['county'] == 'Fresno County'
        assert p['dairy'] == {'id': self.big.sqid, 'name': 'BIG DAIRY'}
        assert p['facility'] == {'id': self.plant.sqid, 'name': 'TEST PLANT', 'url': self.plant.get_absolute_url()}
        assert p['viewer_url'] == 'https://data.carbonmapper.org/#36.73600,-119.78600'
        lone = by_name['lone']['properties']
        assert lone['group'] == 'waste' and lone['dairy'] is None and lone['facility'] is None

    def test_collection_is_cached_under_the_generation(self):
        assert methane.collection()['properties']['sources'] == 3
        MethaneSource.objects.filter(source_name='lone').delete()
        assert methane.collection()['properties']['sources'] == 3
        methane.clear_caches()
        assert methane.collection()['properties']['sources'] == 2


class FacilityAndSectorTests(MethaneTestCase):
    def test_near_facility_and_the_oil_gas_suppression(self):
        assert [s.source_name for s in methane.near_facility(self.plant)] == ['near']
        station = Facility.objects.get(name='TEST GAS STATION')
        assert MethaneSource.objects.get(source_name='og').facility == station
        assert methane.near_facility(station) == []
        assert methane.near_facility(Facility.objects.get(name='TEST CEMENT')) == []

    def test_for_dairy_and_oil_gas_list(self):
        assert [s.source_name for s in methane.for_dairy(self.big)] == ['near']
        assert methane.for_dairy(self.closed) == []
        rows = methane.oil_gas_sources()
        assert [(r['source'].source_name, r['county'].slug, r['facility'].name) for r in rows] == [('og', 'kern', 'TEST GAS STATION')]


class ViewTests(MethaneTestCase):
    def test_the_view_is_same_origin_only(self):
        response = self.client.get(reverse('emissions:methane-geojson'))
        assert response.status_code == 200
        assert response['Cache-Control'] == 'private, max-age=3600' and response['X-Robots-Tag'] == 'noindex'
        body = response.json()
        assert body['properties']['license'].startswith('Carbon Mapper non-commercial') and len(body['features']) == 3

    def test_no_api_route(self):
        with self.assertRaises(NoReverseMatch):  # noqa: the one assertX allowed: pytest.raises works too
            reverse('api:v2:emissions:methane-geojson')
        assert self.client.get('/api/2.0/emissions/methane/geojson/').status_code == 404

    def test_404_before_any_import(self):
        MethaneSource.objects.all().delete()
        from camp.apps.emissions.models import SourceImport
        SourceImport.objects.filter(source='carbon-mapper').delete()
        methane.clear_caches()
        assert self.client.get(reverse('emissions:methane-geojson')).status_code == 404
```

(Write `test_no_api_route` with `pytest.raises(NoReverseMatch)` — the comment above is a reminder, not a licence to use `assertRaises`.) The `/api/2.0/emissions/methane/geojson/` GET hits the `<str:facility_id>/` catch-all, which 404s for an unknown id — that is the assertion.

- [ ] **Step 2: Run to verify failure**

`$TEST camp/apps/emissions/tests/test_methane.py` — `AttributeError: module … has no attribute 'collection'`.

- [ ] **Step 3: `methane.py`, the read side**

Append to `methane.py` (add `from camp.apps.emissions.models import Facility` to the imports):

```python
def attribution():
    """What every template and popup shows beside the data."""
    return {'text': MethaneSource.ATTRIBUTION, 'url': MethaneSource.HOME_URL,
            'license': MethaneSource.LICENSE, 'license_url': MethaneSource.LICENSE_URL}


def sources():
    return MethaneSource.objects.filter(gas=MethaneSource.Gas.CH4).select_related('county', 'dairy', 'facility')


def feature(source):
    return {
        'type': 'Feature',
        'id': source.sqid,
        'geometry': {'type': 'Point', 'coordinates': [round(source.point.x, 5), round(source.point.y, 5)]},
        'properties': {
            'id': source.sqid, 'name': source.source_name, 'group': source.group, 'sector': source.sector_label,
            'rate': source.emission_kg_h, 'unc': source.uncertainty_kg_h, 'rate_text': source.rate_text,
            'persistence': source.persistence, 'obs': source.observations, 'det': source.detections,
            'county': source.county.name,
            'dairy': {'id': source.dairy.sqid, 'name': source.dairy.name} if source.dairy else None,
            'facility': {'id': source.facility.sqid, 'name': source.facility.name, 'url': source.facility.get_absolute_url()} if source.facility else None,
            'viewer_url': source.viewer_url,
        },
    }


def collection():
    """The overlay's GeoJSON: every CH4 source, with the licence and attribution on the collection. Cached a day; an import invalidates it."""
    def compute():
        features = [feature(source) for source in sources().order_by('pk')]
        imported = stamp()
        return {
            'type': 'FeatureCollection',
            'properties': {
                'sources': len(features),
                'imported': imported.imported_at.date().isoformat() if imported else None,
                **attribution(), 'home_url': MethaneSource.HOME_URL,
            },
            'features': features,
        }
    return cache.get_or_set(key('geojson'), compute, CACHE_TIMEOUT)


def near_facility(facility):
    """
    The sources the import linked to this facility (their nearest trusted
    point within 1 km), nearest first. Empty for oil & gas permit groupings:
    their point is an office address, not the wells, so a plume "near" it
    says nothing (the sector page lists the Valley's oil & gas sources).
    """
    if facility.sector == Facility.Sector.OIL_GAS:
        return []
    return cache.get_or_set(
        key('facility', facility.pk),
        lambda: list(sources().filter(facility=facility).order_by('distance_m', 'pk')),
        CACHE_TIMEOUT,
    )


def for_dairy(dairy):
    return list(sources().filter(dairy=dairy))


def oil_gas_sources():
    """Every oil & gas source, by county then rate, with its facility where the import matched one."""
    def compute():
        codes = [code for code, (group, label) in MethaneSource.SECTORS.items() if group == MethaneSource.Group.OIL_GAS]
        rows = []
        for source in sources():
            if any(source.ipcc_sector.startswith(code) for code in codes):
                rows.append({'source': source, 'county': source.county, 'facility': source.facility})
        rows.sort(key=lambda r: (r['county'].name, -(r['source'].emission_kg_h or 0), r['source'].source_name))
        return rows
    return cache.get_or_set(key('oil-gas'), compute, CACHE_TIMEOUT)
```

(`attribution()` in the collection's properties is spread with `**`, and `home_url` is added beside it because the JS builds the attribution link from it.) Note that `feature()`'s `'rate_text'` uses the model property, so the popup and the facility card word a rate identically.

- [ ] **Step 4: The view and URL**

Create `camp/apps/emissions/methane_views.py`:

```python
"""
The methane layer for our own maps. Deliberately not under /api/2.0/ and not
in the API docs: Carbon Mapper's terms are non-commercial with share-alike
redistribution, and until Carbon Mapper confirms a public endpoint in writing
the data is served only to this site's pages (spec, open question 1). The
body still carries the licence and attribution, as the terms require.
"""
from django.http import Http404, JsonResponse
import vanilla

from camp.apps.emissions import methane


class MethaneGeoJSON(vanilla.View):
    def get(self, request):
        if not methane.enabled():
            raise Http404('No methane sources imported.')
        response = JsonResponse(methane.collection())
        response['Cache-Control'] = 'private, max-age=3600'
        response['X-Robots-Tag'] = 'noindex'
        return response
```

`camp/apps/emissions/urls.py`: import `methane_views` beside `dairy_views, views` and add, after the `about/` line:

```python
    # Our maps' methane overlay (Carbon Mapper, non-commercial terms): not a public API. See methane_views.
    path('methane/geojson/', methane_views.MethaneGeoJSON.as_view(), name='methane-geojson'),
```

- [ ] **Step 5: Run and commit**

`$TEST camp/apps/emissions/tests/test_methane.py camp/apps/emissions/tests/test_views.py` — all pass. On the dev server: `curl -s -D - -o /dev/null http://localhost:8003/tools/emissions/methane/geojson/ | grep -i 'x-robots\|cache-control'` shows both headers, and `curl -s http://localhost:8003/tools/emissions/methane/geojson/ | wc -c` is well under 300 KB.

```bash
git -C <worktree> add camp/apps/emissions/methane_views.py camp/apps/emissions/tests/test_methane.py
git -C <worktree> commit -m "feat(emissions): methane read side and a same-origin GeoJSON view with the licence in its body" -- camp/apps/emissions/methane.py camp/apps/emissions/methane_views.py camp/apps/emissions/urls.py camp/apps/emissions/tests/test_methane.py
```

---

### Task 4: Dairies: table column, `?methane=1` filter, headline tile, popup block

**Files:**
- Modify: `camp/apps/emissions/dairies.py` (`TABLE_SORTS`, new `METHANE_FILTERS`, `_methane()`, `table()`, `summary()`, `_where()`)
- Modify: `camp/apps/emissions/dairy_views.py` (`search_filters`, `DairyScopeMixin.get_context_data`, `DairyAreaPage` / `DairyList` summary calls)
- Modify: `camp/templates/emissions/includes/dairy-table.html`, `dairy-stats.html`, `dairy-list.html`, `dairy-area.html`
- Modify: `camp/api/v2/emissions/dairies.py` (`DairyDetail`), `assets/js/emissions/dairy-map.js` (`popupHtml`)
- Test: `camp/apps/emissions/tests/test_dairies.py`, `test_dairies_pages.py`, `test_dairy_area_pages.py`, `camp/api/v2/emissions/tests.py`

**Interfaces:**
- `dairies.METHANE_FILTERS = ('1',)`; `dairies.TABLE_SORTS` gains `'methane_kg_h', '-methane_kg_h'`.
- `dairies.table(year, *, county=None, area=None, q=None, sort=DEFAULT_SORT, enforcement=None, methane=None)`: rows annotated `methane` (bool), `methane_kg_h` (max rate, null), `methane_detections` (sum); `methane == '1'` keeps rows with `methane=True`.
- `dairies.summary(year, *, county=None, area=None, enforcement=None, methane=None)` gains `'methane': n` (dairies with a source) and honours the filter; `_where(county, area, enforcement, methane)`.
- `dairy_views.search_filters(get)` → adds `'methane': '1' | None`; context `methane_stamp = methane.stamp()` and `methane_attribution = methane.attribution()` on every dairy page.
- `DairyDetail` JSON gains `'methane': {'sources': [{name, sector, rate_text, rate, unc, persistence, obs, det, viewer_url}], 'attribution': {...}}` (`sources` empty when none).

- [ ] **Step 1: Write the failing tests**

Append to `test_dairies.py` (the module's `make_dairies` and `row` helpers are the ones Task 2's tests use; import `row`, `NEAR_BOTH` from `test_carbonmapper` and `carbonmapper`):

```python
class MethaneTableTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.big, self.small, self.closed = make_dairies()
        carbonmapper.apply([row(name='a', lnglat=NEAR_BOTH, rate='120', unc='40'), row(name='b', lnglat=NEAR_BOTH, rate='80', unc='10', detection_date_count='3')])

    def test_annotation_filter_and_sort(self):
        rows = {herd.dairy.name: herd for herd in dairies.table(2023)}
        assert rows['BIG DAIRY'].methane is True and rows['BIG DAIRY'].methane_kg_h == 120 and rows['BIG DAIRY'].methane_detections == 8
        assert rows['SMALL DAIRY'].methane is False and rows['SMALL DAIRY'].methane_kg_h is None
        assert [h.dairy.name for h in dairies.table(2023, methane='1')] == ['BIG DAIRY']
        assert [h.dairy.name for h in dairies.table(2023, sort='methane_kg_h')][-1] == 'BIG DAIRY'

    def test_summary_key_and_filter(self):
        assert dairies.summary(2023)['methane'] == 1
        assert dairies.summary(2023, methane='1')['dairies'] == 1
        assert dairies.summary(2023, county=self.small.county)['methane'] == 0
```

Update `test_dairies.py::test_summary`'s expected dicts to include `'methane': 0`.

Append to `test_dairies_pages.py`:

```python
class MethaneTests(DairyPageTestCase):
    def setUp(self):
        super().setUp()
        from camp.apps.emissions import carbonmapper
        from camp.apps.emissions.tests.test_carbonmapper import NEAR_BOTH, row
        carbonmapper.apply([row(name='a', lnglat=NEAR_BOTH, rate='120', unc='40')])

    def test_column_filter_and_tile(self):
        content = self.get({'year': '2023'}).content.decode()
        assert '>Methane observed</a>' in content and 'Carbon Mapper estimate' in content
        big_row = content[content.index('BIG DAIRY</a>'):]
        assert '120 kg/h' in big_row[:big_row.index('</tr>')]
        assert '<p class="heading">With observed methane plumes</p><p class="title">1</p>' in content
        assert 'name="methane" value="1"' in content and 'With an observed methane source' in content
        assert 'Data by Carbon Mapper' in content
        content = self.get({'year': '2023', 'methane': '1'}).content.decode()
        assert 'BIG DAIRY' in content and 'SMALL DAIRY' not in content and 'checked' in content

    def test_no_import_shows_nothing(self):
        from camp.apps.emissions import dairies, methane
        from camp.apps.emissions.models import MethaneSource, SourceImport
        MethaneSource.objects.all().delete()
        SourceImport.objects.filter(source='carbon-mapper').delete()
        dairies.clear_caches(); methane.clear_caches()
        content = self.get({'year': '2023'}).content.decode()
        assert 'Methane observed' not in content and 'name="methane"' not in content and 'With observed methane plumes' not in content
```

Append to `test_dairy_area_pages.py` (`ContentTests`):

```python
    def test_methane_tile_and_filter_on_an_area_page(self):
        from camp.apps.emissions import carbonmapper
        from camp.apps.emissions.tests.test_carbonmapper import NEAR_BOTH, row
        carbonmapper.apply([row(name='a', lnglat=NEAR_BOTH)])
        content = self.get(self.fresno, {'year': '2023'}).content.decode()
        assert '<p class="heading">With observed methane plumes</p><p class="title">1</p>' in content
        assert self.get(self.fresno, {'year': '2023', 'methane': '1'}).context['summary']['dairies'] == 1
```

Append to `camp/api/v2/emissions/tests.py` `DairyEndpointTests`:

```python
    def test_detail_carries_the_methane_block(self):
        from camp.apps.emissions import carbonmapper
        from camp.apps.emissions.tests.test_carbonmapper import NEAR_BOTH, row
        carbonmapper.apply([row(name='a', lnglat=NEAR_BOTH, rate='120', unc='40')])
        block = self.get('dairy-detail', sqid=self.big.sqid).json()['methane']
        assert [s['rate_text'] for s in block['sources']] == ['120 ± 40 kg/h']
        assert block['sources'][0]['viewer_url'].startswith('https://data.carbonmapper.org/#')
        assert block['attribution']['text'] == 'Data by Carbon Mapper®'
        assert self.get('dairy-detail', sqid=self.small.sqid).json()['methane']['sources'] == []
```

- [ ] **Step 2: Run to verify failure**

`$TEST camp/apps/emissions/tests/test_dairies.py::MethaneTableTests camp/apps/emissions/tests/test_dairies_pages.py::MethaneTests camp/api/v2/emissions/tests.py::DairyEndpointTests` — FAIL.

- [ ] **Step 3: `dairies.py`**

Beside Phase 6's `_recent_actions()`:

```python
METHANE_FILTERS = ('1',)


def _methane():
    """The outer herd's dairy's linked Carbon Mapper CH4 sources (import_carbon_mapper resolves the link)."""
    from camp.apps.emissions.models import MethaneSource
    return MethaneSource.objects.filter(dairy=OuterRef('dairy'), gas=MethaneSource.Gas.CH4)
```

- `TABLE_SORTS += ('methane_kg_h', '-methane_kg_h')`.
- `table(...)` gains `methane=None`; the annotate call adds `methane=Exists(_methane())`, `methane_kg_h=Subquery(_methane().order_by().values('dairy').annotate(m=Max('emission_kg_h')).values('m')[:1])`, `methane_detections=Coalesce(Subquery(_methane().order_by().values('dairy').annotate(n=Sum('detections')).values('n')[:1]), Value(0))`; after the enforcement filter `if methane == '1': queryset = queryset.filter(methane=True)`; the sort `expression` dict gains `'methane_kg_h': F('methane_kg_h')` (a `-methane_kg_h` sort puts nulls last: use `F('methane_kg_h').desc(nulls_last=True)` for the desc branch of that key). Imports: `Max`, `Sum` from `django.db.models` if not already there.
- `summary(...)` gains `methane=None`: inside `compute()`, `if methane == '1': queryset = queryset.filter(Exists(_methane()))` before the aggregate, and the dict gains `'methane': queryset.filter(Exists(_methane())).count() if year is not None else 0`. `_where(county, area, enforcement=None, methane=None)` appends `f':{enforcement or "all"}:{methane or "all"}'` (adjust Phase 6's signature rather than adding a second helper); every `_where` call site passes the new kwargs through.

- [ ] **Step 4: `dairy_views.py`**

`search_filters` gains `'methane': get.get('methane') if get.get('methane') in dairies.METHANE_FILTERS else None`. `DairyScopeMixin.get_context_data` adds `methane_stamp=methane.stamp()` and `methane_attribution=methane.attribution()` (import `methane`). `DairyAreaPage.get_context_data` and `DairyList.get_context_data` pass `methane=filters['methane']` to `dairies.summary(...)` beside `enforcement=`.

- [ ] **Step 5: Templates**

`dairy-table.html`, after Phase 6's Water Board column (`{% if not compact %}` both cells), only when `methane_stamp`:

```django
            {% if not compact and methane_stamp %}<th>{% if sortable %}{% sort_link '-methane_kg_h' 'Methane observed' %}{% else %}Methane observed{% endif %}
                <span class="icon is-small has-text-grey has-tooltip-multiline has-tooltip-bottom has-tooltip-arrow" data-tooltip="Plumes Carbon Mapper has observed within 1 km, from aircraft and satellite passes since 2016: the largest source's rate (a Carbon Mapper estimate, an instantaneous snapshot with wide uncertainty, not an annual total) and its detection count. No plume doesn't mean no emissions. Data by Carbon Mapper®, non-commercial use."><span class="fa-regular fa-circle-info" aria-hidden="true"></span></span></th>{% endif %}
```

```django
            {% if not compact and methane_stamp %}<td>{% if herd.methane %}{{ herd.methane_kg_h|whole }} kg/h{% if herd.methane_detections %}, {{ herd.methane_detections }} detection{{ herd.methane_detections|pluralize }}{% endif %}{% else %}—{% endif %}</td>{% endif %}
```

The empty-row `colspan` becomes `{% if methane_stamp %}9{% else %}8{% endif %}` (Phase 6 left it at 8). The comment block gains a line on the column and its licence.

`dairy-stats.html`, after Phase 6's Water Board tile:

```django
    {% if methane_stamp %}
    <div class="level-item has-text-centered"><div>
        <p class="heading">With observed methane plumes</p><p class="title">{{ summary.methane|intcomma }}</p>
        <p class="is-size-7 has-text-grey"><a href="{{ methane_attribution.url }}">{{ methane_attribution.text }}</a>, snapshots</p>
    </div></div>
    {% endif %}
```

`dairy-list.html` and `dairy-area.html`, in the filter form after Phase 6's checkbox:

```django
            {% if methane_stamp %}
            <div class="field">
                <label class="checkbox"><input type="checkbox" name="methane" value="1"{% if filters.methane %} checked{% endif %}> With an observed methane source</label>
                <p class="help">Carbon Mapper plumes within 1 km. <a href="{% url 'emissions:about' %}#methane">What this is</a>.</p>
            </div>
            {% endif %}
```

- [ ] **Step 6: The popup endpoint and JS**

`camp/api/v2/emissions/dairies.py`, `DairyDetail.get` (import `methane`): add to the returned dict

```python
            'methane': {
                'sources': [{
                    'name': s.source_name, 'sector': s.sector_label, 'rate_text': s.rate_text,
                    'rate': s.emission_kg_h, 'unc': s.uncertainty_kg_h, 'persistence': s.persistence,
                    'obs': s.observations, 'det': s.detections, 'viewer_url': s.viewer_url,
                } for s in methane.for_dairy(dairy)],
                'attribution': methane.attribution(),
            },
```

`dairy-map.js` `popupHtml`, after Phase 6's Water Board block and before `Counted in`:

```js
    var me = data.methane;
    if (me && me.sources && me.sources.length) {
      var lines = me.sources.map(function (s) {
        return '<strong>Methane observed</strong>: ' + escapeHtml(s.rate_text) + ' (Carbon Mapper estimate)' +
          (s.det ? ', ' + s.det + ' detection' + (s.det === 1 ? '' : 's') + ' of ' + s.obs + ' pass' + (s.obs === 1 ? '' : 'es') : '') +
          ' · <a href="' + escapeHtml(s.viewer_url) + '">View at Carbon Mapper →</a>';
      });
      lines.push('<span class="has-text-grey"><a href="' + escapeHtml(me.attribution.url) + '">' + escapeHtml(me.attribution.text) + '</a>, non-commercial use</span>');
      parts.push('<div class="dairy-popup-methane is-size-7"><p>' + lines.join('<br>') + '</p></div>');
    }
```

Update the `popupHtml` comment. `node --check assets/js/emissions/dairy-map.js`, then the asset rebuild.

- [ ] **Step 7: Run, check the browser, commit**

`$TEST camp/apps/emissions/tests/test_dairies.py camp/apps/emissions/tests/test_dairies_pages.py camp/apps/emissions/tests/test_dairy_area_pages.py camp/api/v2/emissions/tests.py` — all pass. On :8003 open `/tools/emissions/dairies/?county=tulare&methane=1`: the column, the checked box, the tile; click a dairy: the popup's Methane line with the attribution.

```bash
git -C <worktree> commit -m "feat(dairies): observed methane sources in the dairy table, filter, headline and popup" -- camp/apps/emissions/dairies.py camp/apps/emissions/dairy_views.py camp/templates/emissions/includes/dairy-table.html camp/templates/emissions/includes/dairy-stats.html camp/templates/emissions/dairy-list.html camp/templates/emissions/dairy-area.html camp/api/v2/emissions/dairies.py assets/js/emissions/dairy-map.js camp/apps/emissions/tests/test_dairies.py camp/apps/emissions/tests/test_dairies_pages.py camp/apps/emissions/tests/test_dairy_area_pages.py camp/api/v2/emissions/tests.py
```

---

### Task 5: The facility card, its oil-gas suppression, and the oil-gas sector page list

**Files:**
- Modify: `camp/apps/emissions/views.py` (`FacilityDetail.get_context_data`, `SectorDetail.get_context_data`)
- Create: `camp/templates/emissions/includes/methane-card.html`, `camp/templates/emissions/includes/methane-oil-gas.html`
- Modify: `camp/templates/emissions/facility-detail.html`, `camp/templates/emissions/sector-detail.html`
- Test: `camp/apps/emissions/tests/test_facility_page.py`, `camp/apps/emissions/tests/test_sectors.py`

**Interfaces:**
- `FacilityDetail` context: `methane_sources = methane.near_facility(facility)`, `methane_stamp`, `methane_attribution`.
- `SectorDetail` context: `methane_oil_gas = methane.oil_gas_sources() if self.sector == Facility.Sector.OIL_GAS and methane.enabled() else None`, `methane_stamp`, `methane_attribution`, `METHANE_LIST_ROWS = 25`.
- Card title `Methane plumes observed nearby`; list title `Methane sources observed at oil & gas sites`.

- [ ] **Step 1: Look at the real names**

`head -n 4 <worktree>/camp/apps/emissions/tests/data/carbon-mapper-sources.csv`. If `source_name` reads like an id (`CH4_1B2_…`, a hash), the list shows the nearest facility or the coordinates and this step is done. If it carries a site or field name, the list's first column is that name and `methane-oil-gas.html` below gets a `Field` column before `Nearest facility` — say which in the commit message.

- [ ] **Step 2: Write the failing tests**

Append to `test_facility_page.py`:

```python
class MethaneCardTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        from camp.apps.emissions import carbonmapper
        from camp.apps.emissions.tests.test_carbonmapper import AT_GAS_STATION, NEAR_BOTH, row
        from camp.apps.emissions.tests.test_dairies import make_dairies
        cache.clear()
        make_dairies()
        Facility.objects.filter(name='TEST PLANT').update(point_source=Facility.PointSource.CENSUS)
        Facility.objects.filter(name='TEST GAS STATION').update(point_source=Facility.PointSource.CARB, sector=Facility.Sector.OIL_GAS)
        carbonmapper.apply([row(name='near', lnglat=NEAR_BOTH, rate='120', unc='40'), row(name='og', lnglat=AT_GAS_STATION, sector='1B2')])

    def detail(self, name):
        return self.client.get(Facility.objects.get(name=name).get_absolute_url()).content.decode()

    def test_card_rows_and_attribution(self):
        content = self.detail('TEST PLANT')
        assert 'card-header-title">Methane plumes observed nearby' in content
        assert '120 ± 40 kg/h' in content and 'Carbon Mapper estimate' in content
        assert '5 detections of 12 passes' in content and 'View at Carbon Mapper →' in content
        assert 'href="https://carbonmapper.org"' in content and 'Data by Carbon Mapper®' in content
        assert 'BIG DAIRY' in content  # the nearest dairy is named
        assert 'not an annual total' in content

    def test_card_is_hidden_for_oil_gas_groupings(self):
        from camp.apps.emissions.models import MethaneSource
        assert MethaneSource.objects.get(source_name='og').facility.name == 'TEST GAS STATION'
        assert 'Methane plumes observed nearby' not in self.detail('TEST GAS STATION')

    def test_no_card_without_a_source(self):
        assert 'Methane plumes observed nearby' not in self.detail('TEST CEMENT')
```

Append to `test_sectors.py` (use its existing test-case base and the same `setUp` data as above; import what it needs):

```python
class OilGasMethaneListTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        from camp.apps.emissions import carbonmapper
        from camp.apps.emissions.tests.test_carbonmapper import AT_GAS_STATION, row
        from camp.apps.emissions.tests.test_dairies import make_dairies
        cache.clear()
        make_dairies()
        Facility.objects.filter(name='TEST GAS STATION').update(point_source=Facility.PointSource.CARB, sector=Facility.Sector.OIL_GAS)
        carbonmapper.apply([row(name='og', lnglat=AT_GAS_STATION, sector='1B2', rate='500', unc='150')])

    def test_the_oil_gas_page_lists_sources(self):
        content = self.client.get(reverse('emissions:sector-detail', args=['oil-gas'])).content.decode()
        assert 'Methane sources observed at oil &amp; gas sites' in content
        assert '500 ± 150 kg/h' in content and 'Kern' in content and 'TEST GAS STATION' in content
        assert 'Data by Carbon Mapper®' in content
        assert 'Methane sources observed' not in self.client.get(reverse('emissions:sector-detail', args=['glass'])).content.decode()
```

- [ ] **Step 3: Run to verify failure**

`$TEST camp/apps/emissions/tests/test_facility_page.py::MethaneCardTests camp/apps/emissions/tests/test_sectors.py::OilGasMethaneListTests` — FAIL.

- [ ] **Step 4: Views**

`views.py`: import `methane` beside `areas, dairies, stats, wells`. `FacilityDetail.get_context_data` adds `methane_sources=methane.near_facility(facility) if methane.enabled() else []`, `methane_stamp=methane.stamp()`, `methane_attribution=methane.attribution()`. `SectorDetail.get_context_data` adds `methane_oil_gas=methane.oil_gas_sources() if self.sector == Facility.Sector.OIL_GAS and methane.enabled() else None`, `methane_list_rows=METHANE_LIST_ROWS` (module constant `METHANE_LIST_ROWS = 25` beside `SECTOR_PAGE_ROWS`), `methane_stamp`, `methane_attribution`.

- [ ] **Step 5: Templates**

Create `camp/templates/emissions/includes/methane-card.html`:

```django
{% load humanize emissions_explorer %}
{% comment %}
Carbon Mapper methane sources the import linked to this facility (their nearest
trusted-point facility within 1 km; methane.near_facility). Never rendered for
oil & gas permit groupings. Every rate is Carbon Mapper's estimate; the
attribution and the non-commercial terms are part of the card (the licence
requires both wherever the data shows).
{% endcomment %}
{% if methane_sources %}
<div class="card mt-5" id="methane">
    <header class="card-header"><p class="card-header-title">Methane plumes observed nearby</p></header>
    <div class="card-content content">
        <table class="table is-fullwidth is-narrow">
            <thead><tr><th>Source</th><th>Rate</th><th>Seen</th><th>Nearest dairy</th><th></th></tr></thead>
            <tbody>
            {% for source in methane_sources %}
            <tr>
                <td>{{ source.sector_label }} <span class="has-text-grey is-size-7">{{ source.distance_m|floatformat:0 }} m away</span></td>
                <td>{{ source.rate_text }} <span class="has-text-grey is-size-7">Carbon Mapper estimate</span></td>
                <td>{{ source.detections }} detection{{ source.detections|pluralize }} of {{ source.observations }} pass{{ source.observations|pluralize:"es" }}{% if source.persistence is not None %} <span class="has-text-grey is-size-7">(persistence {{ source.persistence|floatformat:2 }})</span>{% endif %}</td>
                <td>{% if source.dairy %}{{ source.dairy.name }}{% else %}—{% endif %}</td>
                <td><a href="{{ source.viewer_url }}">View at Carbon Mapper →</a></td>
            </tr>
            {% endfor %}
            </tbody>
        </table>
        <p class="is-size-7 has-text-grey">Plumes are snapshots from aircraft and satellite passes. Each rate is an instantaneous estimate with wide uncertainty, not an annual total. A site with no plume hasn't been shown to be clean. <a href="{% url 'emissions:about' %}#methane">More</a>. <a href="{{ methane_attribution.url }}">{{ methane_attribution.text }}</a>, for <a href="{{ methane_attribution.license_url }}">non-commercial use</a>.{% if methane_stamp %} Catalog as of {{ methane_stamp.imported_at|date:"N j, Y" }}.{% endif %}</p>
    </div>
</div>
{% endif %}
```

`facility-detail.html`: `{% include 'emissions/includes/methane-card.html' %}` immediately after the `{% endif %}` that closes the `{% if toxics_rows %}` block (before anything Phase 1 or Phase 4 added below it: the include is harmless where the list is empty).

Create `camp/templates/emissions/includes/methane-oil-gas.html`:

```django
{% load humanize %}
{% comment %}
The oil-gas sector page's list of Carbon Mapper's oil & gas methane sources
(methane.oil_gas_sources): CEIDARS' oil & gas rows are permit groupings whose
point is an office, so the plumes are listed here instead of on facility pages.
{% endcomment %}
{% if methane_oil_gas is not None %}
<h3 class="title is-4 mt-5" id="methane">Methane sources observed at oil &amp; gas sites</h3>
{% if methane_oil_gas %}
<div class="table-container">
<table class="table is-fullwidth is-narrow">
    <thead><tr><th>County</th><th>Rate</th><th>Seen</th><th>Nearest facility</th><th></th></tr></thead>
    <tbody>
    {% for item in methane_oil_gas|slice:methane_list_rows %}
    <tr>
        <td>{{ item.county.short_name }}</td>
        <td>{{ item.source.rate_text }} <span class="has-text-grey is-size-7">Carbon Mapper estimate</span></td>
        <td>{{ item.source.detections }} of {{ item.source.observations }} passes</td>
        <td>{% if item.facility %}<a href="{{ item.facility.get_absolute_url }}">{{ item.facility.name }}</a>{% else %}<span class="has-text-grey">{{ item.source.point.y|floatformat:4 }}, {{ item.source.point.x|floatformat:4 }}</span>{% endif %}</td>
        <td><a href="{{ item.source.viewer_url }}">View at Carbon Mapper →</a></td>
    </tr>
    {% endfor %}
    </tbody>
</table>
</div>
{% if methane_oil_gas|length > methane_list_rows %}<p class="is-size-7 has-text-grey">The {{ methane_list_rows }} largest of {{ methane_oil_gas|length|intcomma }}; turn on the map's <em>Methane sources (Carbon Mapper)</em> overlay for all of them.</p>{% endif %}
{% else %}
<p class="has-text-grey">No oil &amp; gas methane sources in Carbon Mapper's catalog for the covered counties.</p>
{% endif %}
<p class="is-size-7 has-text-grey">Snapshots from aircraft and satellite passes, not annual totals; a field with no plume hasn't been shown to be clean. <a href="{{ methane_attribution.url }}">{{ methane_attribution.text }}</a>, for <a href="{{ methane_attribution.license_url }}">non-commercial use</a>.</p>
{% endif %}
```

`sector-detail.html`: include it after the facilities table's "All N facilities" paragraph. (`slice:methane_list_rows` with an int variable works in Django templates; the top-25 order is county then rate, so on a long list say "largest per county" if reviewers prefer; the test doesn't pin the wording.)

- [ ] **Step 6: Run and commit**

`$TEST camp/apps/emissions/tests/test_facility_page.py camp/apps/emissions/tests/test_sectors.py camp/apps/emissions/tests/test_views.py` — all pass. On :8003 open a dairy-adjacent facility page (one the import linked; `MethaneSource.objects.exclude(facility=None).first().facility.get_absolute_url()` in `$MANAGE shell`) and `/tools/emissions/sectors/oil-gas/`.

```bash
git -C <worktree> add camp/templates/emissions/includes/methane-card.html camp/templates/emissions/includes/methane-oil-gas.html
git -C <worktree> commit -m "feat(emissions): methane plumes card on facility pages and the oil & gas source list" -- camp/apps/emissions/views.py camp/templates/emissions/includes/methane-card.html camp/templates/emissions/includes/methane-oil-gas.html camp/templates/emissions/facility-detail.html camp/templates/emissions/sector-detail.html camp/apps/emissions/tests/test_facility_page.py camp/apps/emissions/tests/test_sectors.py
```

---

### Task 6: The map overlay (shared module, both maps), About, integrations, smoke, PR notes

**Files:**
- Create: `assets/js/emissions/methane-overlay.js`
- Modify: `assets/js/emissions/facility-map.js`, `assets/js/emissions/dairy-map.js`, `camp/templates/emissions/base.html` (script tag), `assets/sass/sjvair/pages/emissions.sass`
- Modify: `camp/apps/emissions/views.py` (`methane_overlay`, `facility_map_config(methane=…)`, `MapPage`, `RegionPage`, `NearMe`, `SectorDetail`, `FacilityDetail`, `About`), `camp/apps/emissions/dairy_views.py` (`dairy_map_config(methane=…)`, the three dairy pages)
- Modify: `camp/templates/emissions/about.html`, `datafiles/data-integrations.yaml`, `scripts/emissions_map_smoke.py`
- Test: `camp/apps/emissions/tests/test_methane.py` (append), `test_views.py` (append)

**Interfaces:**
- `views.methane_overlay(get, *, default=False) -> {'on': bool, 'default': bool} | None`: `None` when `not methane.enabled()` (nothing offered); otherwise the wells pattern with `?methane=1|0`.
- `facility_map_config(..., methane=None)` and `dairy_map_config(..., methane=None)` put on the container: `data-methane-url` (`reverse('emissions:methane-geojson')` or `''`), `data-methane` (`'1'`/`''`), `data-methane-default`, `data-methane-attribution` (the HTML-safe text), `data-methane-home` (the URL).
- `window.EmissionsMethaneOverlay(host, opts)`: `host` is a `FacilityMap` or `DairyMap` (has `shell`, `map`, `el`, `data`, `syncUrl()`); `opts.before` is the layer id the methane layer is inserted **under** (`'facilities'` / `'dairies'`, so the host's points stay clickable on top). Methods: `read()`, `addLayers()`, `apply()`, `load()`, `set(on)`, `legendHtml()`, `writeState(params)`, `bind(legendBody)`, `onAdopt()`, `destroy()`; fields `enabled`, `on`, `default`, `data`.

- [ ] **Step 1: Write the failing tests**

Append to `test_methane.py` (class `OverlayConfigTests(MethaneTestCase)`), and to `test_views.py` a `MapDataTests`-style helper if one exists (Phase 7's `map_data(content, name)` reads a `data-*` attribute off the container; reuse it or copy it):

```python
class OverlayConfigTests(MethaneTestCase):
    def test_methane_overlay_helper(self):
        from camp.apps.emissions import views
        assert views.methane_overlay({}) == {'on': False, 'default': False}
        assert views.methane_overlay({'methane': '1'}) == {'on': True, 'default': False}
        assert views.methane_overlay({'methane': '0'}, default=True) == {'on': False, 'default': True}
        assert views.methane_overlay({'methane': 'x'}) == {'on': False, 'default': False}
        MethaneSource.objects.all().delete()
        from camp.apps.emissions.models import SourceImport
        SourceImport.objects.filter(source='carbon-mapper').delete()
        assert views.methane_overlay({'methane': '1'}) is None

    def test_every_map_offers_the_overlay_off_by_default(self):
        from camp.apps.emissions.tests.test_views import map_data
        region = self.plant.county
        urls = [
            reverse('emissions:map'), reverse('emissions:facility-list'),
            region.get_emissions_url(), region.get_emissions_dairies_url(), reverse('emissions:dairy-list'),
            reverse('emissions:sector-detail', args=['oil-gas']), self.plant.get_absolute_url(),
        ]
        for url in urls:
            content = self.client.get(url, {'year': 2023}).content.decode()
            assert map_data(content, 'methane-url') == reverse('emissions:methane-geojson'), url
            assert map_data(content, 'methane') == '', url
            assert 'Carbon Mapper' in map_data(content, 'methane-attribution'), url
        content = self.client.get(reverse('emissions:map'), {'methane': '1'}).content.decode()
        assert map_data(content, 'methane') == '1'

    def test_nothing_offered_before_an_import(self):
        from camp.apps.emissions.models import SourceImport
        from camp.apps.emissions.tests.test_views import map_data
        MethaneSource.objects.all().delete()
        SourceImport.objects.filter(source='carbon-mapper').delete()
        methane.clear_caches()
        content = self.client.get(reverse('emissions:map'), {'methane': '1'}).content.decode()
        assert map_data(content, 'methane-url') == ''

    def test_about_has_the_methane_section(self):
        content = self.client.get(reverse('emissions:about')).content.decode()
        assert '<h2 id="methane">Methane</h2>' in content
        assert 'Data by Carbon Mapper®' in content and 'https://carbonmapper.org/terms' in content
        assert 'not an annual total' in content and 'Methane is a climate pollutant, not a direct local toxic' in content
```

(`emissions:facility-list` has no map; drop it from `urls` if the page has no `.facility-map` container — check the template.)

- [ ] **Step 2: Run to verify failure**

`$TEST camp/apps/emissions/tests/test_methane.py::OverlayConfigTests` — `AttributeError: … 'methane_overlay'`.

- [ ] **Step 3: Views**

`views.py`, above `facility_map_config`, beside `wells_overlay`:

```python
def methane_overlay(get, *, default=False):
    """
    The maps' Methane sources (Carbon Mapper) overlay: nothing (None) until
    an import exists; else off unless the page says otherwise, with
    ?methane=1|0 overriding either way so the state can be shared.
    """
    if not methane.enabled():
        return None
    raw = get.get('methane')
    on = raw == '1' if raw in ('0', '1') else default
    return {'on': on, 'default': default}


def methane_map_data(overlay):
    """The data-* values both map configs carry for the overlay; empty strings when it isn't offered."""
    if not overlay:
        return {'methane_url': '', 'methane': '', 'methane_default': '', 'methane_attribution': '', 'methane_home': ''}
    return {
        'methane_url': reverse('emissions:methane-geojson'),
        'methane': '1' if overlay['on'] else '',
        'methane_default': '1' if overlay['default'] else '',
        'methane_attribution': MethaneSource.ATTRIBUTION,
        'methane_home': MethaneSource.HOME_URL,
    }
```

`facility_map_config(..., methane=None)`: `config.update(methane_map_data(methane))` after the wells keys; docstring mentions it. Pass `methane=methane_overlay(self.request.GET)` from `MapPage`, `RegionPage.get_map_config`, `NearMe.get_map_config`, `SectorDetail` and `FacilityDetail` (the facility's own map offers it: decision 4). `dairy_views.dairy_map_config(..., methane=None)`: the same `config.update(views.methane_map_data(methane))` before `template_only` is computed; `DairyList`, `RegionDairies` and `NearMeDairies` pass `methane=views.methane_overlay(self.request.GET)`.

- [ ] **Step 4: `methane-overlay.js`**

Create `assets/js/emissions/methane-overlay.js`:

```js
/*
 * The "Methane sources (Carbon Mapper)" overlay, shared by facility-map.js
 * and dairy-map.js: one circle per Carbon Mapper CH4 source from
 * data-methane-url (/tools/emissions/methane/geojson/, our pages only),
 * sized by the square root of its rate and coloured by sector group; a
 * legend checkbox row toggles it and ?methane= carries it. The source
 * carries a MapLibre attribution, so the map's attribution control shows
 * "Data by Carbon Mapper®" whenever the layer is on; the popup repeats it
 * with the non-commercial terms. Nothing here is ours: every rate is
 * labelled a Carbon Mapper estimate.
 */
(function () {
  'use strict';

  var M = window.SJVAirMaps;
  if (!M) return;

  var COLORS = { livestock: '#7c3aed', 'oil-gas': '#0f766e', waste: '#b45309', other: '#6b7280' };
  var GROUPS = [['livestock', 'Livestock'], ['oil-gas', 'Oil & gas'], ['waste', 'Waste & wastewater'], ['other', 'Other']];
  var TERMS_URL = 'https://carbonmapper.org/terms';

  function escapeHtml(text) { return M.escapeHtml ? M.escapeHtml(text) : String(text).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }

  function Overlay(host, opts) {
    this.host = host;
    this.before = (opts || {}).before || null;
    this.collection = null;
    this.request = 0;
    this.read();
    var self = this;
    host.map.on('click', 'methane', function (evt) { self.openPopup(evt.features[0], evt.lngLat); });
    host.map.on('mouseenter', 'methane', function () { host.map.getCanvas().style.cursor = 'pointer'; });
    host.map.on('mouseleave', 'methane', function () { host.map.getCanvas().style.cursor = ''; });
  }

  Overlay.prototype.read = function () {
    var d = this.host.data;
    this.enabled = !!d.methaneUrl;
    this.default = d.methaneDefault === '1';
    this.on = this.enabled && d.methane === '1';
  };

  // Under the host's own points (`before`), so a dairy or facility circle on
  // top of a plume stays clickable. The attribution is the licence's.
  Overlay.prototype.addLayers = function () {
    var d = this.host.data;
    this.host.shell.ensureSource('methane', {
      attribution: '<a href="' + escapeHtml(d.methaneHome || 'https://carbonmapper.org') + '">' + escapeHtml(d.methaneAttribution || 'Data by Carbon Mapper®') + '</a>',
    });
    if (!this.host.map.getLayer('methane')) {
      this.host.map.addLayer({
        id: 'methane', type: 'circle', source: 'methane',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['sqrt', ['coalesce', ['get', 'rate'], 0]], 0, 4, 5, 6, 15, 10, 30, 16, 60, 22],
          'circle-color': ['match', ['get', 'group'], 'livestock', COLORS.livestock, 'oil-gas', COLORS['oil-gas'], 'waste', COLORS.waste, COLORS.other],
          'circle-opacity': 0.55,
          'circle-stroke-color': '#ffffff', 'circle-stroke-width': 1,
        },
      }, this.before && this.host.map.getLayer(this.before) ? this.before : undefined);
    }
    this.apply();
  };

  Overlay.prototype.apply = function () {
    var map = this.host.map;
    if (map && map.getLayer('methane')) map.setLayoutProperty('methane', 'visibility', this.enabled && this.on ? 'visible' : 'none');
  };

  // Fetched once per page (the whole Valley, cached an hour server-side), only when on.
  Overlay.prototype.load = function () {
    var self = this;
    if (!this.enabled || !this.on) return;
    if (this.collection) { this.host.shell.setSourceData('methane', this.collection); this.host.el.dataset.methaneLoaded = '1'; return; }
    var request = ++this.request;
    this.host.el.dataset.methaneLoaded = '';
    M.getJson(this.host.data.methaneUrl)
      .then(function (collection) {
        if (request !== self.request || !self.host.map) return;
        self.collection = collection;
        self.host.shell.setSourceData('methane', collection);
        self.host.shell.updateLegend();
        self.host.el.dataset.methaneLoaded = '1';
      })
      .catch(function (err) { if (request === self.request && self.host.map && M.logError) M.logError('failed to load the methane sources', err); });
  };

  Overlay.prototype.set = function (on) {
    if (!this.enabled) return;
    this.on = !!on;
    this.apply();
    this.host.syncUrl();
    this.host.shell.updateLegend();
    this.load();
  };

  Overlay.prototype.legendHtml = function () {
    if (!this.enabled) return '';
    var html = '<div class="legend-overlay"><label class="legend-toggle"><input type="checkbox" data-methane' + (this.on ? ' checked' : '') + '> Methane sources (Carbon Mapper)</label>';
    if (this.on) {
      html += '<p class="legend-wells">' + GROUPS.map(function (g) {
        return '<span class="legend-well"><span class="legend-swatch is-well is-methane" style="background: ' + COLORS[g[0]] + '"></span>' + g[1] + '</span>';
      }).join('') + '</p><p class="legend-note">Circle area by Carbon Mapper\'s estimated rate (kg/h). Snapshots from overflights, not annual totals. <a href="' + escapeHtml(this.host.data.methaneHome || 'https://carbonmapper.org') + '">' + escapeHtml(this.host.data.methaneAttribution || 'Data by Carbon Mapper®') + '</a>, non-commercial use.</p>';
    }
    return html + '</div>';
  };

  Overlay.prototype.openPopup = function (feature, lngLat) {
    var p = feature.properties;
    var link = p.facility ? JSON.parse(p.facility) : null;  // nested objects arrive as JSON strings in MapLibre feature properties
    var dairy = p.dairy ? JSON.parse(p.dairy) : null;
    var html = '<div class="facility-popup methane-popup">' +
      '<p class="facility-popup-name">' + escapeHtml(p.sector) + ' methane source</p>' +
      '<p>' + escapeHtml(p.rate_text) + ' <span class="has-text-grey">(Carbon Mapper estimate)</span></p>' +
      '<p>' + p.det + ' detection' + (p.det === 1 ? '' : 's') + ' of ' + p.obs + ' pass' + (p.obs === 1 ? '' : 'es') + (p.persistence !== null && p.persistence !== undefined ? ' · persistence ' + Number(p.persistence).toFixed(2) : '') + '</p>' +
      (dairy ? '<p>Nearest dairy: ' + escapeHtml(dairy.name) + '</p>' : '') +
      (link ? '<p>Nearest facility: <a href="' + escapeHtml(link.url) + '">' + escapeHtml(link.name) + '</a></p>' : '') +
      '<p><a href="' + escapeHtml(p.viewer_url) + '">View at Carbon Mapper →</a></p>' +
      '<p class="is-size-7 has-text-grey"><a href="' + escapeHtml(this.host.data.methaneHome || 'https://carbonmapper.org') + '">' + escapeHtml(this.host.data.methaneAttribution || 'Data by Carbon Mapper®') + '</a>, for <a href="' + TERMS_URL + '">non-commercial use</a>.</p></div>';
    this.host.shell.placePopup(html, lngLat);
  };

  Overlay.prototype.writeState = function (params) {
    if (this.enabled && this.on !== this.default) params.set('methane', this.on ? '1' : '0'); else params.delete('methane');
  };

  // The legend re-renders with the map, so the checkbox handler is delegated to the legend body, bound once.
  Overlay.prototype.bind = function (legendBody) {
    var self = this;
    if (!legendBody || legendBody.getAttribute('data-methane-bound')) return;
    legendBody.setAttribute('data-methane-bound', '1');
    legendBody.addEventListener('change', function (event) {
      if (event.target && event.target.hasAttribute('data-methane')) self.set(event.target.checked);
    });
  };

  Overlay.prototype.onAdopt = function () { this.read(); this.apply(); this.load(); };
  Overlay.prototype.destroy = function () { this.collection = null; };

  window.EmissionsMethaneOverlay = Overlay;
})();
```

Check `assets/js/maps/core.js` for the real names of the shared helpers (`M.getJson`, `M.escapeHtml`, `M.logError` — facility-map.js has local `getJson`/`escapeHtml`/`logError` that wrap or duplicate them; use whatever `core.js` exports and fall back as above). Nested `dairy`/`facility` properties come out of `queryRenderedFeatures` as JSON strings — hence the `JSON.parse`.

- [ ] **Step 5: Wire both maps**

`camp/templates/emissions/base.html`: add `<script src="{% static 'js/emissions/methane-overlay.js' %}"></script>` **before** the `dairy-map.js` line. (`invoke bundle` copies `assets/js/` into static; confirm by grepping `tasks.py` for `assets/js` if the file doesn't appear.)

`facility-map.js`: in the constructor after the wells listeners, `this.methane = window.EmissionsMethaneOverlay ? new window.EmissionsMethaneOverlay(this, { before: 'facilities' }) : null;`. Then, guarding each with `if (this.methane)`: at the end of `addLayers` → `this.methane.addLayers()`; in `load()` after `loadWells` → `this.methane.load()`; every `legend.innerHTML = …` assignment that appends `this.wellsLegendHtml()` also appends `+ (this.methane ? this.methane.legendHtml() : '')` (in `legend()` and `areaLegend()`); in `onChrome` after the wells binding → `this.methane.bind(legendBody)`; in `writeState` after the wells line → `this.methane.writeState(params)`; in `onAdopt` after the wells calls → `this.methane.onAdopt()`; in `destroy` → `this.methane.destroy()`. The cursor loop gains nothing (the overlay binds its own). Header comment: add "Overlays: … Methane sources (Carbon Mapper), from data-methane-url, shared with the dairy map (methane-overlay.js)."

`dairy-map.js`: the same seven hooks with `before: 'dairies'`: constructor; end of `addLayers` (after `applyFilters()`); `load()` (after the dairies promise is set up, not inside it: `if (this.methane) this.methane.load();` right after `this.shell.setStatus('Loading dairies…')`); `legend()` → `legend.innerHTML = (… ? this.countyLegend() : this.dairyLegend()) + (this.methane ? this.methane.legendHtml() : '')`; `onChrome` → `if (this.methane) this.methane.bind(this.shell.legendBodyEl)` (the property name `updateLegend` reads); `writeState` → `if (this.methane) this.methane.writeState(params)`; `onAdopt` → after `this.readState()` add `if (this.methane) this.methane.onAdopt()`; `destroy` → `if (this.methane) this.methane.destroy()`. Note the dairy legend's `if (this.view === 'counties' ? !this.counties : !this.dairies) return;` early exit: the overlay row still needs to render on an empty area page, so move the overlay append into the same assignment and only keep the early return when the legend has neither data nor an enabled overlay.

`assets/sass/sjvair/pages/emissions.sass`, beside Phase 7's `.legend-swatch.is-well`: `.legend-swatch.is-methane` → `border-radius: 50%; opacity: 0.7` and `.methane-popup .facility-popup-name` → `text-transform: none` (only if the facility popup name is uppercased there; check). `node --check` both map files and the new one; run the asset rebuild.

- [ ] **Step 6: About and integrations**

`about.html`, after the Dairies section and before `<h2 id="sources">`:

```django
<h2 id="methane">Methane</h2>
<p>The maps' <em>Methane sources (Carbon Mapper)</em> overlay, the dairy tables' <em>Methane observed</em> column and the facility pages' <em>Methane plumes observed nearby</em> card show the methane point sources in <a href="https://carbonmapper.org">Carbon Mapper</a>'s public catalog: plumes seen from aircraft and satellite passes since 2016, clustered into the sites they come from, each with Carbon Mapper's estimate of its emission rate and how often it was seen. Each source is linked to the nearest CADD dairy and the nearest permitted facility with a trustworthy map point within 1 km.</p>
<div class="notification is-light">
    <p>Plumes are snapshots from aircraft and satellite passes. Each rate is an instantaneous estimate with wide uncertainty, not an annual total. A site with no plume hasn't been shown to be clean: it may not have been overflown, or the plume was below detection. Methane is a climate pollutant, not a direct local toxic. Data by Carbon Mapper®, for non-commercial use.</p>
</div>
<p class="is-size-7 has-text-grey"><a href="https://carbonmapper.org">Data by Carbon Mapper®</a>, under Carbon Mapper's <a href="https://carbonmapper.org/terms">non-commercial terms</a>: SJVAir, a non-profit public service, shows the data on its own pages with attribution and doesn't sell, license or offer it for download. Every rate shown is a Carbon Mapper estimate, not SJVAir's.</p>
```

Sources list: `<li><a href="https://carbonmapper.org/data">Carbon Mapper methane point sources</a> (Data by Carbon Mapper®, non-commercial terms)</li>`. `datafiles/data-integrations.yaml`, under Emissions Data after the CARB Pollution Mapping Tool entry:

```yaml
    - name: Carbon Mapper
      logo: img/logo/carbon-mapper.svg
      url: https://carbonmapper.org
      description: Carbon Mapper is a non-profit that finds methane and CO2 super-emitters from aircraft and satellites and publishes each source's location, estimated emission rate and how often it was seen. SJVAir shows the Valley's methane sources as a map overlay and links each to the nearest dairy or permitted facility. Data by Carbon Mapper®, for non-commercial use.
```

No Carbon Mapper logo is in `assets/img/logo/` (the memory rule: reuse the repo first, SVG preferred). Check `https://carbonmapper.org` for a press-kit or brand page and, **only if its use is permitted there**, save the wordmark as `assets/img/logo/carbon-mapper.svg`; otherwise leave `logo:` out and confirm the integrations template renders an entry without one (grep the template that reads `data-integrations.yaml`) — say which in the commit and in the PR notes so Derek can decide.

- [ ] **Step 7: Smoke**

Append to `scripts/emissions_map_smoke.py`, after the dairies tab's size/digester checks (the block ending "reloaded map only draws medium/large digester dairies"), a methane block:

```python
        # Phase 9: the methane overlay on the dairy map. Ticking the legend's
        # checkbox loads the layer, writes ?methane=1, and a plume's popup
        # carries the attribution.
        driver.get(args.base + '/tools/emissions/dairies/')
        wait_dairies(driver)
        has_toggle = driver.execute_script("return !!document.querySelector('.dairy-map-legend [data-methane]');")
        check(results, 'dairies tab offers the methane overlay (needs import_carbon_mapper on this DB)', has_toggle)
        if has_toggle:
            driver.execute_script("document.querySelector('.dairy-map-legend [data-methane]').click()")
            loaded = wait_for(driver, "var el = document.querySelector('.dairy-map'); return !!el && el.dataset.methaneLoaded === '1';")
            count = driver.execute_script("var m = window.EmissionsDairyMap.instances()[0]; return m.map.querySourceFeatures('methane').length;")
            check(results, 'the methane layer loads and ?methane=1 lands in the URL', loaded and count > 0 and 'methane=1' in driver.current_url, f'{count} sources; {driver.current_url}')
            legend = driver.execute_script("return document.querySelector('.dairy-map-legend').textContent;")
            check(results, 'the methane legend carries the attribution', 'Data by Carbon Mapper' in legend and 'Livestock' in legend)
            attribution = driver.execute_script("var el = document.querySelector('.maplibregl-ctrl-attrib-inner, .maptiler-ctrl-attrib-inner'); return el ? el.textContent : '';")
            check(results, "the map's attribution control names Carbon Mapper", 'Carbon Mapper' in attribution, attribution[:120])
            opened = driver.execute_script(
                "var m = window.EmissionsDairyMap.instances()[0]; var f = m.map.querySourceFeatures('methane')[0]; if (!f) return false;"
                "m.methane.openPopup(f, {lng: f.geometry.coordinates[0], lat: f.geometry.coordinates[1]}); return true;")
            popup = driver.execute_script("var p = document.querySelector('.methane-popup'); return p ? p.textContent : '';") if opened else ''
            check(results, 'a methane popup says Carbon Mapper estimate and carries the attribution', 'Carbon Mapper estimate' in popup and 'Data by Carbon Mapper' in popup, popup[:160])
```

If the script has no `wait_for(driver, script)` helper, add one beside `wait_dairies` (poll `execute_script` until truthy, `MAP_TIMEOUT`). Run the smoke; every line should be PASS (the dev DB has the import from Task 2).

- [ ] **Step 8: Run everything, commit, draft the PR notes**

`$TEST camp/apps/emissions camp/api/v2/emissions` — all pass; `node --check` on the three JS files.

```bash
git -C <worktree> add assets/js/emissions/methane-overlay.js
git -C <worktree> commit -m "feat(emissions): Methane sources (Carbon Mapper) overlay on the facility and dairy maps, About section" -- assets/js/emissions/methane-overlay.js assets/js/emissions/facility-map.js assets/js/emissions/dairy-map.js assets/sass/sjvair/pages/emissions.sass camp/templates/emissions/base.html camp/apps/emissions/views.py camp/apps/emissions/dairy_views.py camp/templates/emissions/about.html datafiles/data-integrations.yaml scripts/emissions_map_smoke.py camp/apps/emissions/tests/test_methane.py camp/apps/emissions/tests/test_views.py
```

(add `assets/img/logo/carbon-mapper.svg` to both commands if Step 6 saved one.) Then write the PR notes into `<worktree>/.superpowers/pr-notes-phase-9.md` (untracked; the controller pastes them):

```
**Licence: Derek must confirm before deploy.** Carbon Mapper's terms (https://carbonmapper.org/terms) are non-commercial with attribution and share-alike. This PR serves the data only to our own pages (a same-origin view under /tools/emissions/, not /api/2.0/; no CSV; not in the API docs), records the terms on the model and in every SourceImport, and shows "Data by Carbon Mapper®" wherever the data is drawn or listed. Keep the PR a draft until the licence is confirmed; if Carbon Mapper confirms a public endpoint in writing, moving the view under /api/2.0/ is one URL line.

Deploy: `migrate`; one-off `heroku run -a <app> -- python manage.py import_carbon_mapper` (network, under a minute; ~730 sources); the monthly task (the 4th, 11:00 UTC) registers on restart. Nothing shows until the import has run (no overlay, column, tile or card). Logo: <saved from the press kit | omitted; needs one>.
```

---

### Task 7: Optional: `DigesterGrant`, `ddrdp.py`, `import_ddrdp`, popup line and county totals

**Ship criterion (decide by the end of Step 3, one afternoon at most):** the parse yields at least 135 of the PDF's 142 projects with a dairy name, county and grant amount, and name+city matching plus a crosswalk of at most ~25 hand entries links at least 80% of them to a `Dairy`. Otherwise `git -C <worktree> reset --hard HEAD~1` (nothing from this task has been committed before Step 6), leave the checked-in sample file out, and add one line to the PR notes: "DDRDP digester grants deferred to a follow-up PR: <what broke>". Everything before this task ships either way.

**Files:**
- Modify: `camp/apps/emissions/models.py` (append), `admin.py`
- Create: `camp/apps/emissions/migrations/0017_digestergrant.py` (generated), `camp/apps/emissions/ddrdp.py`, `camp/apps/emissions/ddrdp_crosswalk.py`, `camp/apps/emissions/management/commands/import_ddrdp.py`
- Create: `camp/apps/emissions/tests/data/ddrdp-page.pdf`, `camp/apps/emissions/tests/test_ddrdp.py`
- Modify: `camp/api/v2/emissions/dairies.py` (`DairyDetail`), `assets/js/emissions/dairy-map.js` (`popupHtml`), `camp/apps/emissions/dairy_views.py` (`DairyAreaPage`), `camp/templates/emissions/includes/dairy-stats.html`, `about.html`, `datafiles/data-integrations.yaml`

**Interfaces:**
- `DigesterGrant(sqid, dairy FK null SET_NULL related_name='grants', project_name, dairy_name, city, county (char 32), developer, grant_amount Decimal(12,2) null, end_use (char 64), est_reduction_tco2e float null, awarded date null, operational date null, match_method ('manual' | 'auto' | ''))`; `Meta.ordering = ['-awarded', 'dairy_name']`.
- `ddrdp.URL = 'https://www.cdfa.ca.gov/oefi/DDRDP/docs/DDRDP_Project_Level_Data.pdf'`, `ddrdp.SOURCE = 'ddrdp'`, `ddrdp.DDRDPFormatError`.
- `ddrdp.parse(path) -> (rows: list[dict], version: str)` (pdfplumber; `version` is the "updated" date printed on the PDF, ISO, or `''`), `ddrdp.normalise_name(name) -> str`, `ddrdp.match(rows) -> rows with 'dairy' and 'match_method' filled`, `ddrdp.apply(rows, version) -> Report(parsed, matched_auto, matched_manual, unmatched)`, `ddrdp.county_totals(county) -> {'grants', 'amount', 'reduction'} | None` (cached under `dairies.key('ddrdp', county.pk)`), `ddrdp.stamp()`.
- `ddrdp_crosswalk.CROSSWALK = {normalised project or dairy name: cadd_id}` (hand-kept, with a comment per entry saying why).
- Command `import_ddrdp --path FILE | --url [URL]`; manual (CDFA updates the PDF a few times a year), no task.
- `DairyDetail` JSON gains `'grants': [{project_name, amount, awarded_year, end_use, reduction}]`; county dairy pages get a tile `DDRDP digester grants` (`$X · N t CO2e/yr claimed`).

- [ ] **Step 1: Look at the PDF first**

```bash
curl -sSL -o /home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer/.superpowers/ddrdp.pdf https://www.cdfa.ca.gov/oefi/DDRDP/docs/DDRDP_Project_Level_Data.pdf
$MANAGE shell -c "import pdfplumber; pdf = pdfplumber.open('/app/.superpowers/ddrdp.pdf'); print(len(pdf.pages)); p = pdf.pages[1]; t = p.extract_table(); print(len(t) if t else None); print(t[:3] if t else p.extract_text()[:800])"
```

Read the header row and two data rows: which columns exist (dairy/project name, city, county, developer, grant amount, end use, estimated MTCO2e/yr, award and operational dates), whether a project spans two lines, and whether `extract_table()` finds the table or needs `extract_text()` with a regex. Write `parse()` for the real layout; the test in Step 2 asserts against what you saw.

- [ ] **Step 2: The one-page sample and the failing tests**

One data page, so the parser is tested against CDFA's real layout (`qpdf` if installed, else `pypdf` in the smoke venv: `/home/derek/.claude/jobs/d44a9b36/tmp/venv/bin/pip install pypdf`):

```bash
/home/derek/.claude/jobs/d44a9b36/tmp/venv/bin/python -c "
from pypdf import PdfReader, PdfWriter
r = PdfReader('/home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer/.superpowers/ddrdp.pdf'); w = PdfWriter(); w.add_page(r.pages[1])
w.write('/home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer/camp/apps/emissions/tests/data/ddrdp-page.pdf')"
```

Create `camp/apps/emissions/tests/test_ddrdp.py`:

```python
"""data/ddrdp-page.pdf is page 2 of CDFA's DDRDP project list (updated 2026-06-27), extracted with pypdf (Task 7 Step 2)."""
from decimal import Decimal
from pathlib import Path

from django.core.cache import cache
from django.test import TestCase

from camp.apps.emissions import ddrdp
from camp.apps.emissions.models import DigesterGrant, SourceImport
from camp.apps.emissions.tests.test_dairies import make_dairies

SAMPLE = Path(__file__).parent / 'data' / 'ddrdp-page.pdf'


class ParseTests(TestCase):
    def test_the_real_page(self):
        rows, version = ddrdp.parse(SAMPLE)
        assert len(rows) >= 20  # a full data page; adjust to the count you saw, minus none
        first = rows[0]
        assert set(first) >= {'project_name', 'dairy_name', 'city', 'county', 'developer', 'grant_amount', 'end_use', 'est_reduction_tco2e', 'awarded', 'operational'}
        assert all(r['dairy_name'] and r['county'] for r in rows)
        assert all(r['grant_amount'] is None or isinstance(r['grant_amount'], Decimal) for r in rows)
        assert sum(1 for r in rows if r['grant_amount']) >= len(rows) - 2

    def test_normalise_name(self):
        assert ddrdp.normalise_name('Lakeside Dairy, LLC') == 'lakeside'
        assert ddrdp.normalise_name('J & D Farms Inc.') == 'j d farms'
        assert ddrdp.normalise_name('Big Dairy #2') == 'big 2'


class MatchAndApplyTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.big, self.small, self.closed = make_dairies()

    def row(self, **overrides):
        values = dict(project_name='Big Dairy Digester', dairy_name='Big Dairy', city='Riverdale', county='Fresno', developer='Dev Co',
                      grant_amount=Decimal('1500000'), end_use='Pipeline injection', est_reduction_tco2e=12000.0, awarded=None, operational=None)
        values.update(overrides)
        return values

    def test_two_match_paths_and_unmatched(self):
        from camp.apps.emissions import ddrdp_crosswalk
        ddrdp_crosswalk.CROSSWALK['mystery digester'] = self.small.cadd_id
        try:
            rows = ddrdp.match([self.row(), self.row(project_name='Mystery Digester', dairy_name='Mystery', city='Nowhere'), self.row(project_name='Lost', dairy_name='Lost Dairy', city='Nowhere')])
        finally:
            del ddrdp_crosswalk.CROSSWALK['mystery digester']
        assert [(r['dairy'], r['match_method']) for r in rows] == [(self.big, 'auto'), (self.small, 'manual'), (None, '')]

    def test_apply_replaces_and_stamps(self):
        ddrdp.apply(ddrdp.match([self.row()]), '2026-06-27')
        ddrdp.apply(ddrdp.match([self.row(), self.row(project_name='Second', dairy_name='Small Dairy', city='Bakersfield', county='Kern', grant_amount=Decimal('900000'), est_reduction_tco2e=5000.0)]), '2026-06-27')
        assert DigesterGrant.objects.count() == 2 and SourceImport.latest('ddrdp').version == '2026-06-27'
        totals = ddrdp.county_totals(self.big.county)
        assert totals == {'grants': 1, 'amount': Decimal('1500000'), 'reduction': 12000.0}
        assert ddrdp.county_totals(self.closed.county) == totals  # same county
```

Append to `camp/api/v2/emissions/tests.py` `DairyEndpointTests`: `test_detail_carries_grants` — after `ddrdp.apply(...)` of one matched row, `self.get('dairy-detail', sqid=self.big.sqid).json()['grants'] == [{'project_name': 'Big Dairy Digester', 'amount': 1500000.0, 'awarded_year': None, 'end_use': 'Pipeline injection', 'reduction': 12000.0}]`, and `[]` for `self.small`. Append to `test_dairy_area_pages.py` `ContentTests`: `test_ddrdp_tile_on_a_county_page` — the Fresno page contains `<p class="heading">DDRDP digester grants</p>` and `$1,500,000`; a city page (`self.get(<a city region>)`) doesn't.

- [ ] **Step 3: Model, migration, module, crosswalk, command**

Append to `models.py`:

```python
class DigesterGrant(models.Model):
    """
    A CDFA Dairy Digester Research and Development Program (DDRDP) grant,
    from CDFA's project-level PDF: the dairy, the developer, the award, the
    biogas end use and CDFA's estimate of the annual reduction. Matched to a
    Dairy by normalised name and city, then by ddrdp_crosswalk; unmatched
    rows are kept (their county still counts them). The reduction is CDFA's
    claim, shown as such.
    """

    class Match(models.TextChoices):
        AUTO = 'auto', _('Name and city')
        MANUAL = 'manual', _('Crosswalk')

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.DigesterGrant'))
    dairy = models.ForeignKey(Dairy, verbose_name=_('Dairy'), null=True, blank=True, on_delete=models.SET_NULL, related_name='grants')
    project_name = models.CharField(_('Project'), max_length=128)
    dairy_name = models.CharField(_('Dairy name'), max_length=128)
    city = models.CharField(_('City'), max_length=64, blank=True)
    county = models.CharField(_('County'), max_length=32, blank=True)
    developer = models.CharField(_('Developer'), max_length=128, blank=True)
    grant_amount = models.DecimalField(_('Grant amount'), max_digits=12, decimal_places=2, null=True, blank=True)
    end_use = models.CharField(_('Biogas end use'), max_length=64, blank=True)
    est_reduction_tco2e = models.FloatField(_('Estimated reduction (t CO2e/yr)'), null=True, blank=True)
    awarded = models.DateField(_('Awarded'), null=True, blank=True)
    operational = models.DateField(_('Operational'), null=True, blank=True)
    match_method = models.CharField(_('Match method'), max_length=8, choices=Match.choices, blank=True)

    class Meta:
        ordering = ['-awarded', 'dairy_name']

    def __str__(self):
        return f'{self.project_name} ({self.dairy_name})'
```

`$MANAGE makemigrations emissions -n digestergrant`. Admin: `DigesterGrantAdmin(ReadOnlyAdminMixin, base_admin.ModelAdmin)` with `list_display = ['project_name', 'dairy_name', 'city', 'county', 'dairy', 'match_method', 'grant_amount', 'est_reduction_tco2e', 'awarded']`, `list_filter = ['match_method', 'county']`, `search_fields = ['project_name', 'dairy_name', 'dairy__name']`, `raw_id_fields = ['dairy']`.

`ddrdp.py` (shape; fill `parse()` from what Step 1 showed):

```python
STOP_WORDS = {'dairy', 'dairies', 'farm', 'farms', 'llc', 'inc', 'lp', 'ranch', 'digester', 'and', 'the', 'of'}

def normalise_name(name):
    words = re.sub(r'[^a-z0-9 ]', ' ', (name or '').lower().replace('&', ' ')).split()
    return ' '.join(w for w in words if w not in STOP_WORDS) or ' '.join(words)
```

(`test_normalise_name` expects `'j d farms'`: `farms` is kept there because dropping every stop word would leave `'j d'` — implement as "drop stop words unless fewer than two words remain, then drop only the corporate suffixes `llc`, `inc`, `lp`". Adjust the test to whatever rule you settle on; the point is that `Lakeside Dairy, LLC` and `LAKESIDE DAIRY` meet.) `match(rows)`: build `{(normalise_name(d.name), cities.lookup_key(d.address.get('city'))): d}` and `{normalise_name(d.name): [d, …]}` over `Dairy.objects.all()`; a row matches `auto` on name+city, or on a name that is unique Valley-wide; else `manual` via `CROSSWALK.get(normalise_name(project_name)) or CROSSWALK.get(normalise_name(dairy_name))` → `Dairy.objects.filter(cadd_id=…)`; else unmatched. `apply(rows, version)`: one transaction, `DigesterGrant.objects.all().delete()` then `bulk_create`, `SourceImport(source='ddrdp', version=version, data_through=<version as date if parseable>)`, `dairies.clear_caches()`. `county_totals(county)`: sum over `DigesterGrant.objects.filter(county__iexact=county.short_name)`, `None` when no rows; cached under `dairies.key('ddrdp', county.pk)`. `parse(path)`: pdfplumber over every page, `extract_table()` per page (or text + regex), money → `Decimal` (strip `$` and commas), dates → `date` (formats seen in Step 1), `version` from a line matching `updated .*?(\d{1,2}/\d{1,2}/\d{4})` on page 1 → ISO.

`import_ddrdp`: `--path FILE` or `--url [URL]` (default `ddrdp.URL`; download to a temp file with `requests`, 120 s timeout); `rows, version = ddrdp.parse(path)`; `CommandError` on `DDRDPFormatError` or fewer than 100 rows; `report = ddrdp.apply(ddrdp.match(rows), version)`; print `report.lines()` **and the unmatched rows grouped by county** (name, city) so the crosswalk can be extended. Fill `ddrdp_crosswalk.py` from that list until the ship criterion holds; each entry gets a comment (`# CADD: "LAKESIDE DAIRY #2", Hanford; PDF: "Lakeside Digester", Lemoore`).

Run `$TEST camp/apps/emissions/tests/test_ddrdp.py` and `$MANAGE import_ddrdp --path /app/.superpowers/ddrdp.pdf` against the dev DB; **apply the ship criterion here.**

- [ ] **Step 4: Popup, tile, About**

`DairyDetail.get`: `'grants': [{'project_name': g.project_name, 'amount': float(g.grant_amount) if g.grant_amount is not None else None, 'awarded_year': g.awarded.year if g.awarded else None, 'end_use': g.end_use, 'reduction': g.est_reduction_tco2e} for g in dairy.grants.all()]`. `dairy-map.js` `popupHtml`, right after the Digester line:

```js
    if (data.grants && data.grants.length) {
      parts.push('<p class="is-size-7">' + data.grants.map(function (g) {
        return 'CDFA DDRDP grant' + (g.amount !== null ? ', $' + whole(g.amount) : '') + (g.awarded_year ? ' (' + g.awarded_year + ')' : '') +
          (g.reduction !== null ? ', estimated ' + whole(g.reduction) + ' t CO2e/yr reduction' : '') + ' <span class="has-text-grey">(CDFA\'s estimate)</span>';
      }).join('<br>') + '</p>');
    }
```

`DairyAreaPage.get_context_data`: `ddrdp_totals=ddrdp.county_totals(county) if county is not None else None`. `dairy-stats.html`, after the methane tile:

```django
    {% if ddrdp_totals %}
    <div class="level-item has-text-centered"><div>
        <p class="heading">DDRDP digester grants</p><p class="title">${{ ddrdp_totals.amount|floatformat:0|intcomma }}</p>
        <p class="is-size-7 has-text-grey">{{ ddrdp_totals.grants }} grant{{ ddrdp_totals.grants|pluralize }} · {{ ddrdp_totals.reduction|whole }} t CO2e/yr claimed</p>
    </div></div>
    {% endif %}
```

About, in the Dairies list after the Digesters bullet: `<li><strong>Digester grants.</strong> CDFA's Dairy Digester Research and Development Program lists each grant it has made, the developer, the biogas end use and CDFA's estimate of the annual reduction in tonnes of CO2-equivalent. Dairy popups show a dairy's grants; county dairy pages total them. The reductions are CDFA's estimates, not measurements.</li>` and a Sources item linking `ddrdp.URL`. Integrations, under Emissions Data: `CDFA DDRDP` with `url: https://www.cdfa.ca.gov/oefi/ddrdp/` and a two-sentence description; logo: check `assets/img/logo/` for a CDFA mark first; if none, save the seal from cdfa.ca.gov as `assets/img/logo/cdfa.svg` (a public agency mark) or omit as in Task 6.

- [ ] **Step 5: Run and commit**

`$TEST camp/apps/emissions/tests/test_ddrdp.py camp/apps/emissions/tests/test_dairy_area_pages.py camp/api/v2/emissions/tests.py camp/apps/emissions/tests/test_views.py` — all pass; `node --check assets/js/emissions/dairy-map.js`; asset rebuild; `$MANAGE makemigrations --check --dry-run` → no changes.

```bash
git -C <worktree> add camp/apps/emissions/migrations/0017_digestergrant.py camp/apps/emissions/ddrdp.py camp/apps/emissions/ddrdp_crosswalk.py camp/apps/emissions/management/commands/import_ddrdp.py camp/apps/emissions/tests/data/ddrdp-page.pdf camp/apps/emissions/tests/test_ddrdp.py
git -C <worktree> commit -m "feat(dairies): CDFA DDRDP digester grants in dairy popups and county totals" -- camp/apps/emissions/models.py camp/apps/emissions/migrations/0017_digestergrant.py camp/apps/emissions/admin.py camp/apps/emissions/ddrdp.py camp/apps/emissions/ddrdp_crosswalk.py camp/apps/emissions/management/commands/import_ddrdp.py camp/apps/emissions/tests/data/ddrdp-page.pdf camp/apps/emissions/tests/test_ddrdp.py camp/api/v2/emissions/dairies.py camp/api/v2/emissions/tests.py assets/js/emissions/dairy-map.js camp/apps/emissions/dairy_views.py camp/templates/emissions/includes/dairy-stats.html camp/templates/emissions/about.html datafiles/data-integrations.yaml camp/apps/emissions/tests/test_dairy_area_pages.py
```

- [ ] **Step 6: PR notes**

Append to `.superpowers/pr-notes-phase-9.md`: "Deploy (DDRDP): one-off `import_ddrdp --url` (or `--path` with the PDF copied in); manual, re-run when CDFA updates the list (the version line prints the PDF's date). Matched N of 142 (M by crosswalk); the K unmatched are listed by `import_ddrdp`'s output."

---

## Self-review

- Every rendering of Carbon Mapper data in this plan carries the attribution and the terms: GeoJSON body (Task 3), map source attribution + legend + popup (Task 6), facility card and oil-gas list (Task 5), dairy table tooltip, tile and popup (Task 4), About (Task 6), `SourceImport.notes` (Task 2). No `/api/2.0/` route, no CSV, no API docs line (`test_no_api_route`).
- The spec's Phase 9 items are all placed: maps overlay (Task 6), facility card with the oil-gas suppression and the sector list (Task 5), dairy popup/table/filter/headline (Task 4), digester grants (Task 7, optional), About and integrations (Tasks 6–7), tests as the spec lists them (county clip, upsert and removal, 1-km boundary case, trusted-point rule, licence in the GeoJSON, dairy filter and headline, facility card and its suppression, DDRDP parse and two match paths, smoke on the dairy map with an attributed popup).
- Interfaces named in later tasks exist in earlier ones: `MethaneSource.sector_for/rate_text/viewer_url` (1) ← 2, 3, 4, 5; `carbonmapper.apply/row helpers` (2) ← 3, 4, 5, 6 tests; `methane.stamp/enabled/attribution/near_facility/oil_gas_sources/collection` (3) ← 4, 5, 6; `views.methane_map_data` (6) ← `dairy_views.dairy_map_config` (6).
