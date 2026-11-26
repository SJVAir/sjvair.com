# Monitor groups and pollutant help text Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `GET /api/2.0/monitors/meta/` sends `monitor_groups`, a `group` per monitor type (derived from `GRADE`), and a `description` per entry type.

**Architecture:** A `Monitor.GradeGroup` choices class and a classmethod mapping `GRADE` to it live on the `Monitor` model; a `description` class attribute lives on entry models. `MonitorMetaEndpoint` serializes both. No migration, no new per-type attribute.

**Tech Stack:** Django, django-resticus, pytest.

**Spec:** `docs/superpowers/specs/2026-11-12-monitor-meta-groups-design.md`

## Global Constraints

- Additions only: no existing meta field changes; bam1022's label stays "BAM 1022".
- Group ids `reference` and `low-cost` are permanent. Labels: "Reference-grade", "Low-cost sensors". Orders 0 and 1.
- FEM and FRM map to `reference`, LCS to `low-cost`, `None` to `None`; a grade-less type stays in meta with `group: null`.
- All new labels and descriptions use `gettext_lazy`; the endpoint sends them as `str`.
- Descriptions are the spec's table verbatim; every other entry type sends `description: null` (key present).
- No v1 API change. No production commands. Don't touch other repos.

## Test command

All test runs use the test image with a per-session DB. From the worktree, build the URL without printing it:

```bash
DBURL=$(grep '^DATABASE_URL=' ../../.env.test | cut -d= -f2- | sed 's#/[^/?]*\([?].*\)\?$#/test_meta_groups\1#')
podman run --rm --network sjvaircom_sjvair-net --env-file ../../.env.test -e DATABASE_URL="$DBURL" \
  -e BAM_MIRROR_ENABLED=0 -e TWILIO_AUTH_TOKEN=test-token -v "$PWD":/app:z -w /app \
  sjvair-com-test:latest pytest <target> -v
```

Referred to below as `RUN <target>`. "fatal: not a git repository" inside the container is harmless.

## Review Focus

1. Lazy strings leaking: a `__proxy__` in the payload would fail JSON or render oddly. Tests assert `type(...) is str`.
2. A missing key instead of `null`: clients distinguish "no help text" from an old server. Tests assert `'description' in entry` for every entry type.
3. A newly enabled type with a grade that maps to no group would silently lose its heading; the every-graded-type test catches it. A type with no grade (CIMIS when `MONITOR_ENABLED_TYPES` is empty) stays in meta with `group: null`, not dropped or erroring.
4. Heading order coming from dict order: `order` must be explicit integers 0, 1 matching declaration order.
5. A `monitors.Group` model name clash: the choices class is `GradeGroup`, never `Group`.

---

### Task 1: Monitor groups in the meta

**Files:**
- Modify: `camp/apps/monitors/models.py` (inside `class Monitor`, next to `class Grade` / `GRADE = None`, ~line 122-127)
- Modify: `camp/api/v2/monitors/endpoints.py` (`MonitorMetaEndpoint.get_monitors`, `get`)
- Test: `camp/api/v2/monitors/tests/test_meta_labels.py` (new class `MonitorMetaGroupTests`)

**Interfaces:**
- Produces: `Monitor.GradeGroup(models.TextChoices)` with `REFERENCE = 'reference', _('Reference-grade')` and `LOW_COST = 'low-cost', _('Low-cost sensors')`, declared in that order.
- Produces: `Monitor.get_grade_group() -> Monitor.GradeGroup | None`, a classmethod: FEM/FRM give `REFERENCE`, LCS gives `LOW_COST`, anything else `None`.
- Produces: `MonitorMetaEndpoint.get_monitor_groups() -> dict` keyed by group value, each `{'key', 'label', 'order'}`.

- [ ] **Step 1: Write the failing tests** in `MonitorMetaGroupTests(TestCase)` (fixtures `['default-calibrations.yaml']`, same `_fetch` as the existing classes):

```python
def test_monitor_groups(self):
    assert self._fetch()['monitor_groups'] == {
        'reference': {'key': 'reference', 'label': 'Reference-grade', 'order': 0},
        'low-cost': {'key': 'low-cost', 'label': 'Low-cost sensors', 'order': 1},
    }

def test_group_labels_are_plain_strings(self):
    for group in self._fetch()['monitor_groups'].values():
        assert type(group['label']) is str

def test_every_graded_type_has_a_group(self):
    data = self._fetch()
    for monitor_model in Monitor.get_enabled_subclasses():
        if monitor_model.GRADE is not None:
            assert data['monitors'][monitor_model.monitor_type]['group'] in data['monitor_groups']

def test_gradeless_type_listed_with_null_group(self):
    # Empty MONITOR_ENABLED_TYPES enables every type, CIMIS (GRADE None) included.
    with self.settings(MONITOR_ENABLED_TYPES=[]):
        monitors = self._fetch()['monitors']
    assert 'cimis' in monitors
    assert monitors['cimis']['group'] is None

def test_current_type_groups(self):
    monitors = self._fetch()['monitors']
    expected = {
        'airnow': 'reference', 'aqlite': 'reference', 'aqview': 'reference', 'bam1022': 'reference',
        'airgradient': 'low-cost', 'purpleair': 'low-cost', 'vozbox': 'low-cost',
    }
    for monitor_type, group in expected.items():
        if monitor_type in monitors:
            assert monitors[monitor_type]['group'] == group

def test_bam1022_label_unchanged(self):
    monitors = self._fetch()['monitors']
    if 'bam1022' in monitors:
        assert monitors['bam1022']['label'] == 'BAM 1022'
```

Plus a model-level test of the mapping (same file, class `GradeGroupMappingTests(TestCase)`), using throwaway subclasses or `unittest.mock.patch.object(Monitor, 'GRADE', ...)`:

```python
def test_grade_mapping(self):
    cases = {
        Monitor.Grade.FEM: Monitor.GradeGroup.REFERENCE,
        Monitor.Grade.FRM: Monitor.GradeGroup.REFERENCE,
        Monitor.Grade.LCS: Monitor.GradeGroup.LOW_COST,
        None: None,
    }
    for grade, group in cases.items():
        with patch.object(Monitor, 'GRADE', grade):
            assert Monitor.get_grade_group() == group
```

- [ ] **Step 2: Run to verify they fail**

Run: `RUN camp/api/v2/monitors/tests/test_meta_labels.py`
Expected: the new tests FAIL (`KeyError: 'monitor_groups'`, `AttributeError: GradeGroup`); existing tests pass.

- [ ] **Step 3: Implement** `Monitor.GradeGroup` and `Monitor.get_grade_group()` in `models.py`; in the endpoint add `'group'` to each monitor type (value `getattr(monitor_model.get_grade_group(), 'value', None)`), add `get_monitor_groups()` (`order` = index in `list(Monitor.GradeGroup)`, `label` = `str(...)`), and add `'monitor_groups': self.get_monitor_groups()` to `get()`'s data.

- [ ] **Step 4: Run to verify they pass**

Run: `RUN camp/api/v2/monitors/tests/test_meta_labels.py`
Expected: all PASS.

- [ ] **Step 5: Confirm no migration is generated**

Run: `RUN` with `python manage.py makemigrations --check --dry-run monitors` in place of `pytest <target> -v`
Expected: `No changes detected`.

- [ ] **Step 6: Commit**

```bash
git add camp/apps/monitors/models.py camp/api/v2/monitors/endpoints.py camp/api/v2/monitors/tests/test_meta_labels.py
git commit -m "Monitor meta: monitor_groups and each type's group, from GRADE"
```

### Task 2: Pollutant help text in the meta

**Files:**
- Modify: `camp/apps/entries/models/base.py` (`BaseEntry`: `description = None` next to `units = None`)
- Modify: `camp/apps/entries/models/particulates.py` (`PM25`, `PM10`, `PM100`), `camp/apps/entries/models/gases.py` (`CO`, `CO2`, `NO2`, `O3`, `SO2`): `description = _('...')` right after `label`
- Modify: `camp/api/v2/monitors/endpoints.py` (`get_entries`)
- Test: `camp/api/v2/monitors/tests/test_meta_labels.py` (new class `MonitorMetaDescriptionTests`)

**Interfaces:**
- Produces: `BaseEntry.description: str | lazy str | None`.

- [ ] **Step 1: Write the failing tests**

```python
DESCRIPTIONS = {
    'pm25': 'Fine particles from smoke, dust, and vehicle exhaust.',
    'o3': 'Ground-level gas that forms in sunlight on hot days.',
    'pm10': 'The smallest particles, mostly from smoke and vehicle exhaust.',
    'pm100': 'Coarser particles from dust, farming, and road traffic.',
    'no2': 'Gas from vehicle and engine exhaust, highest near busy roads.',
    'so2': 'Gas from burning fuels that contain sulfur, mostly from industry.',
    'co': 'Colorless, odorless gas from vehicle exhaust and burning fuel.',
    'co2': 'Gas from breathing and burning fuel; high levels indoors mean a room needs fresh air.',
}

def test_pollutant_descriptions(self):
    entries = self._fetch()['entries']
    for entry_type, text in DESCRIPTIONS.items():
        assert entries[entry_type]['description'] == text
        assert type(entries[entry_type]['description']) is str

def test_other_entry_types_null(self):
    entries = self._fetch()['entries']
    for entry_type, entry in entries.items():
        assert 'description' in entry
        if entry_type not in DESCRIPTIONS:
            assert entry['description'] is None
    assert entries['particulates']['description'] is None
    assert entries['temperature']['description'] is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `RUN camp/api/v2/monitors/tests/test_meta_labels.py::MonitorMetaDescriptionTests`
Expected: FAIL with `KeyError: 'description'`.

- [ ] **Step 3: Implement** the attributes with the table's text, and add `'description': str(entry_model.description) if entry_model.description is not None else None` to `get_entries`.

- [ ] **Step 4: Run to verify they pass**

Run: `RUN camp/api/v2/monitors/tests/test_meta_labels.py`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add camp/apps/entries/models/ camp/api/v2/monitors/endpoints.py camp/api/v2/monitors/tests/test_meta_labels.py
git commit -m "Monitor meta: help text for each air-quality pollutant"
```

### Task 3: Docs and full suite

**Files:**
- Modify: `CLAUDE.md` (Metadata Endpoints, the `monitors/meta/` sentence in "Domain meta endpoints")

- [ ] **Step 1: Document** after "…`stages` and `processors` labels.": "`monitor_groups` (`reference`, `low-cost`; `{key, label, order}`, ids permanent) and each monitor type's `group`, derived from `GRADE` (`Monitor.get_grade_group()`: FEM/FRM reference, LCS low-cost). Each entry type has `description`: plain help text for the air-quality pollutants, `null` otherwise."

- [ ] **Step 2: Run the full suite**

Run: `RUN` with `pytest -n 4 --dist loadscope` in place of `pytest <target> -v`
Expected: all pass (same skips as develop).

- [ ] **Step 3: Check the live endpoint on the local stack** (read-only; retry once if the first request fails after a reload). Only after the branch is served there; otherwise skip and say so.

Run: `curl -s http://localhost:8000/api/2.0/monitors/meta/ | python3 -c "import json,sys; d=json.load(sys.stdin)['data']; print(d['monitor_groups']); print({k:v['group'] for k,v in d['monitors'].items()}); print(d['entries']['pm25']['description'])"`
Expected: both groups, the 7 types grouped as in Task 1, and the PM2.5 line.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "CLAUDE.md: monitor meta groups and descriptions"
```
