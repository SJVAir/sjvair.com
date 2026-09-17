# Pesticides Plain-Language Health Notes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** No badge anywhere in the explorer without an explanation a resident can read in one breath, with all of the copy in one datafile.

**Architecture:** A YAML datafile (`datafiles/pesticide-health-notes.yaml`) loaded through the existing `datafile()` helper and cached in-process; a tiny `notes.py` module that maps a chemical/product/notice to the note keys it carries; a template tag that exposes a note by key; the badges include gains `title` tooltips from the notes; a `what-this-means.html` include renders the notes for the badges present on entity, notice, and place pages; the landing explainer and the "How to read this page" panel render the same notes.

**Tech Stack:** Django templates, YAML via `camp.utils.datafiles.datafile`, `functools.lru_cache`.

**Spec:** `docs/superpowers/specs/2026-09-16-pesticides-explorer-v2-design.md`, section "5. Plain-language layer".

## Global Constraints

- Commands from the worktree root inside Docker: `docker compose run --rm test pytest <path> -q`; `docker compose run --rm web invoke styles` after sass edits (`dist/css/style.css` is git-ignored; do not try to commit it).
- Tests: `django.test.TestCase`, fixtures (`pesticides-explorer`), plain `assert`. Fixture chemical 1 GLYPHOSATE (categories `[carcinogen]`, IARC 2A → Prop 65 + IARC badges), 2 CHLORPYRIFOS (`[toxic_air_contaminant, cholinesterase_inhibitor]` → CARB TAC badge + cholinesterase tag), 3 SULFUR (none). Product 2 LORSBAN 4E is `fumigant` + `california_restricted`.
- Copy rules: every `summary` is one or two sentences, plain words, no jargon without a gloss; never claims a specific exposure is harmful; every entry has a `source_url` on an official site (OEHHA, IARC, CARB, DPR, SprayDays).
- Explorer pages never link to raw API endpoints. Never `git add -A`; commit trailer exactly `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; no other AI attribution.
- Shared db; a dev server for this worktree runs on port 8002 (do not start/stop servers).

---

## File map

| File | Responsibility |
|---|---|
| `datafiles/pesticide-health-notes.yaml` | the copy: one entry per key |
| `camp/apps/pesticides/notes.py` | `all_notes()`, `note(key)`, `keys_for_chemical()`, `keys_for_product()`, `keys_for_notice()`, `notes_for(keys)` |
| `camp/apps/pesticides/templatetags/pesticides_explorer.py` | + `health_note` simple tag, `note_summary` filter |
| `camp/templates/pesticides/includes/classification-badges.html`, `product-detail.html`, `product-list.html`, `chemical-detail.html`, `chemical-list.html` | badge `title` from notes |
| `camp/templates/pesticides/includes/what-this-means.html` | expandable notes for the badges present |
| `chemical-detail.html`, `product-detail.html`, `notice-detail.html`, `place.html`, `section-detail.html` | include `what-this-means.html` |
| `home.html`, `includes/how-to-read.html` | explainer + panel render notes |
| `camp/apps/pesticides/tests/test_notes.py` | tests |

---

### Task 1: The datafile, the notes module, tooltips, and the "What this means" block

**Files:** Create `datafiles/pesticide-health-notes.yaml`, `camp/apps/pesticides/notes.py`, `camp/templates/pesticides/includes/what-this-means.html`, `camp/apps/pesticides/tests/test_notes.py`. Modify `templatetags/pesticides_explorer.py`, `includes/classification-badges.html`, `chemical-detail.html`, `chemical-list.html`, `product-detail.html`, `product-list.html`, `notice-detail.html`, `place.html`, `section-detail.html`, `home.html`, `includes/how-to-read.html`, `pesticides.sass`, and the corresponding views to add `note_keys` to the context.

**Interfaces:**

```python
# camp/apps/pesticides/notes.py
NOTES_FILE = 'pesticide-health-notes.yaml'
REQUIRED_KEYS = (
    'prop65', 'iarc_1', 'iarc_2a', 'iarc_2b', 'iarc_3', 'carb_tac',
    'fumigant', 'cholinesterase_inhibitor', 'groundwater_contaminant', 'biopesticide', 'oil',
    'restricted_material', 'noi_meaning', 'pur_lag', 'shades', 'badges',
)

@lru_cache(maxsize=1)
def all_notes() -> dict[str, dict]      # key → {'key', 'title', 'summary', 'detail' (str|None), 'source_url'}; validates REQUIRED_KEYS present, raises ImproperlyConfigured listing missing keys
def note(key) -> dict | None
def keys_for_chemical(chemical) -> list[str]   # 'prop65' if is_prop65; 'carb_tac' if is_tac; f'iarc_{group.lower()}' if iarc_group; then each of other_categories that has a note (fumigant, cholinesterase_inhibitor, groundwater_contaminant, biopesticide, oil); ordered as listed, no duplicates
def keys_for_product(product) -> list[str]     # 'fumigant' if product.fumigant; 'restricted_material' if product.california_restricted
def keys_for_notice(notice) -> list[str]       # 'noi_meaning', 'restricted_material', then the union of keys_for_chemical over notice.chemicals.all() (prefetched) and keys_for_product over notice.products.all(), ordered, unique
def notes_for(keys) -> list[dict]              # notes in the given order, skipping unknown keys
```

Template side:
- `{% health_note 'prop65' as n %}` simple tag → `note(key)`; `{{ 'prop65'|note_summary }}` filter → summary or `''`.
- `classification-badges.html`: each badge's `title` becomes the note summary (`{% health_note 'prop65' as prop65_note %}` … `title="{{ prop65_note.summary }}"`); IARC picks `iarc_<group lower>`; CARB TAC → `carb_tac`. Product badges in `product-detail.html` / `product-list.html` get `fumigant` / `restricted_material` summaries; DPR category tags in `chemical-detail.html` / `chemical-list.html` get the category's summary when a note exists.
- `includes/what-this-means.html` expects `notes` (list of note dicts); renders nothing when empty, else:

```html
{% if notes %}
<details class="what-this-means">
    <summary>What this means</summary>
    <dl>
    {% for note in notes %}
        <dt>{{ note.title }}</dt>
        <dd>{{ note.summary }} <a href="{{ note.source_url }}" target="_blank" rel="noopener" class="is-size-7">Source</a></dd>
    {% endfor %}
    </dl>
</details>
{% endif %}
```

- Views add `notes`: `ChemicalDetail` → `notes_for(keys_for_chemical(object))`; `ProductDetail` → `notes_for(keys_for_product(object))`; `NoticeDetail` → `notes_for(keys_for_notice(object))`; place pages (`place_context`) and `SectionDetail` → `notes_for(ordered union of keys_for_chemical over the top_chemicals' objs)`. Rendered under the header (after the badges/identifiers) on those pages.
- `home.html` explainer: the Prop 65, IARC, CARB TAC, and DPR-categories paragraphs are replaced by the notes' `summary` + `detail` (via `{% health_note %}`), so copy lives in one place; the section anchors (`#prop65`, `#iarc`, `#tac`, `#categories`) stay.
- `includes/how-to-read.html` (from the near-me plan) renders `pur_lag`, `noi_meaning`, `shades`, `badges` summaries instead of inline copy.
- Sass: `.what-this-means { margin: .5rem 0 1rem } .what-this-means summary { cursor: pointer; font-weight: 600; color: $primary } .what-this-means dl { margin: .5rem 0 0 } .what-this-means dt { font-weight: 600; margin-top: .5rem } .what-this-means dd { margin-left: 0; @extend .has-text-grey-dark }`.

The datafile (write exactly this, then adjust wording only if a test or reviewer finds an error of fact):

```yaml
# Plain-language notes for the pesticides explorer. One entry per key.
# title: short label. summary: one or two sentences a resident can read in one breath.
# detail: optional paragraph. source_url: an official source.
prop65:
  title: Proposition 65
  summary: California lists this chemical as known to cause cancer, birth defects, or other reproductive harm. Being on the list means the state has evidence of a hazard, not that any particular exposure will hurt you.
  detail: Proposition 65 (the Safe Drinking Water and Toxic Enforcement Act of 1986) requires the state to keep a public list of chemicals with evidence of causing cancer or reproductive harm. Here the badge appears when the Department of Pesticide Regulation tags the chemical as a carcinogen, reproductive toxin, or developmental toxin.
  source_url: https://oehha.ca.gov/proposition-65/proposition-65-list
iarc_1:
  title: IARC Group 1
  summary: The World Health Organization's cancer agency has found that this chemical causes cancer in people. The rating describes the strength of the evidence, not how risky a given amount is.
  source_url: https://monographs.iarc.who.int/agents-classified-by-the-iarc/
iarc_2a:
  title: IARC Group 2A
  summary: The World Health Organization's cancer agency rates this chemical as probably causing cancer in people. The rating describes the strength of the evidence, not how risky a given amount is.
  source_url: https://monographs.iarc.who.int/agents-classified-by-the-iarc/
iarc_2b:
  title: IARC Group 2B
  summary: The World Health Organization's cancer agency rates this chemical as possibly causing cancer in people. The evidence is limited, and the rating says nothing about how risky a given amount is.
  source_url: https://monographs.iarc.who.int/agents-classified-by-the-iarc/
iarc_3:
  title: IARC Group 3
  summary: The World Health Organization's cancer agency looked at this chemical and could not classify it either way. That is not the same as being found safe.
  source_url: https://monographs.iarc.who.int/agents-classified-by-the-iarc/
carb_tac:
  title: Toxic Air Contaminant
  summary: The California Air Resources Board lists this chemical as an air pollutant that may cause serious illness. Pesticides on the list get extra monitoring and rules when they are sprayed.
  source_url: https://ww2.arb.ca.gov/resources/documents/carb-identified-toxic-air-contaminants
fumigant:
  title: Fumigant
  summary: A fumigant is applied as a gas to soil or stored crops and can drift beyond the field. Fumigant applications need extra setbacks and buffer zones, and they are the notices SprayDays publishes 48 hours ahead.
  source_url: https://www.cdpr.ca.gov/docs/emon/fumigants/
cholinesterase_inhibitor:
  title: Cholinesterase inhibitor
  summary: This chemical works by blocking an enzyme the nervous system needs, in insects and in people. Farmworkers who handle it are required to have regular blood tests.
  source_url: https://www.cdpr.ca.gov/docs/whs/cholinesterase.htm
groundwater_contaminant:
  title: Groundwater contaminant
  summary: This chemical has been found in California groundwater or can reach it, so the state restricts where and how it is used to protect drinking-water wells.
  source_url: https://www.cdpr.ca.gov/docs/emon/grndwtr/
biopesticide:
  title: Biopesticide
  summary: A biopesticide comes from natural materials such as bacteria, minerals, or plant extracts. They are generally lower-toxicity to people than conventional pesticides, though not always harmless.
  source_url: https://www.epa.gov/ingredients-used-pesticide-products/what-are-biopesticides
oil:
  title: Oil
  summary: Petroleum or plant oils used to smother insects and mites. They are low in toxicity to people, but they are counted by weight, so they often top the pounds-applied lists.
  source_url: https://www.cdpr.ca.gov/docs/pur/purmain.htm
restricted_material:
  title: California restricted material
  summary: This product can only be used with a permit from the county agricultural commissioner, and a notice of intent must be filed before each application. That is why it shows up in SprayDays.
  source_url: https://www.cdpr.ca.gov/docs/enforce/permitting.htm
noi_meaning:
  title: Notice of intent
  summary: A notice of intent is a grower telling the county they plan to apply a restricted pesticide. It is a plan, not proof that spraying happened, and the grower may begin any time up to four days after the scheduled date.
  detail: SprayDays publishes notices 48 hours ahead for fumigants and 24 hours ahead for other restricted materials. Notices list the product and chemical but not the crop. To be told about notices near an address, sign up with SprayDays.
  source_url: https://spraydays.cdpr.ca.gov/Home/About
pur_lag:
  title: Why the latest year is last year
  summary: Growers report applications to the county, which sends them to the state, which checks and publishes them about a year later. The most recent full year here is the newest the state has released.
  source_url: https://www.cdpr.ca.gov/docs/pur/purmain.htm
shades:
  title: What the shades mean
  summary: Darker squares and counties had more pounds applied that year. Shades rank the areas shown against each other, so the same color can mean different amounts on different maps; read the legend for the actual range.
  source_url: https://www.cdpr.ca.gov/docs/pur/purmain.htm
badges:
  title: What the badges mean
  summary: Badges mark chemicals that an official list flags for cancer, reproductive harm, or air toxicity. A badge says the chemical is on a list, not how much of it reached anyone.
  source_url: https://oehha.ca.gov/proposition-65
```

- [ ] **Step 1: Tests (RED)** — `tests/test_notes.py`:

```python
from django.test import TestCase
from django.urls import reverse

from camp.apps.pesticides import notes
from camp.apps.pesticides.models import Chemical, PesticideNotice, Product
from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin


class NotesModuleTests(TestCase):
    fixtures = ['pesticides-explorer']

    def test_datafile_is_complete(self):
        data = notes.all_notes()
        for key in notes.REQUIRED_KEYS:
            entry = data[key]
            assert entry['title'] and entry['summary'] and entry['source_url'].startswith('https://'), key
            assert entry['summary'].count('. ') <= 2, key

    def test_keys_for_chemical(self):
        assert notes.keys_for_chemical(Chemical.objects.get(pk=1)) == ['prop65', 'iarc_2a']
        assert notes.keys_for_chemical(Chemical.objects.get(pk=2)) == ['carb_tac', 'cholinesterase_inhibitor']
        assert notes.keys_for_chemical(Chemical.objects.get(pk=3)) == []

    def test_keys_for_product_and_notice(self):
        assert notes.keys_for_product(Product.objects.get(pk=2)) == ['fumigant', 'restricted_material']
        assert notes.keys_for_product(Product.objects.get(pk=1)) == []
        notice = PesticideNotice.objects.prefetch_related('chemicals', 'products').get(pk=3)
        assert notes.keys_for_notice(notice) == ['noi_meaning', 'restricted_material', 'prop65', 'iarc_2a', 'carb_tac', 'cholinesterase_inhibitor', 'fumigant']

    def test_notes_for_skips_unknown(self):
        assert [n['key'] for n in notes.notes_for(['prop65', 'nope', 'prop65'])] == ['prop65']


class NotesRenderingTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def test_badge_tooltips_and_block_on_chemical_page(self):
        html = self.client.get(Chemical.objects.get(pk=1).get_absolute_url()).content.decode()
        prop65 = notes.note('prop65')['summary']
        assert f'title="{prop65}"' in html
        assert 'What this means' in html and notes.note('iarc_2a')['title'] in html

    def test_no_block_without_badges(self):
        html = self.client.get(Chemical.objects.get(pk=3).get_absolute_url()).content.decode()
        assert 'What this means' not in html

    def test_product_page(self):
        html = self.client.get(Product.objects.get(pk=2).get_absolute_url()).content.decode()
        assert notes.note('restricted_material')['summary'] in html

    def test_notice_page(self):
        notice = PesticideNotice.objects.get(pk=3)
        html = self.client.get(reverse('pesticides:notice-detail', kwargs={'sqid': notice.sqid})).content.decode()
        assert notes.note('noi_meaning')['summary'] in html and notes.note('fumigant')['title'] in html

    def test_landing_and_how_to_read_use_notes(self):
        html = self.client.get(reverse('pesticides:home')).content.decode()
        assert notes.note('prop65')['summary'] in html
        assert notes.note('pur_lag')['summary'] in html and notes.note('shades')['summary'] in html

    def test_list_pages_have_tooltips(self):
        html = self.client.get(reverse('pesticides:product-list')).content.decode()
        assert f'title="{notes.note("fumigant")["summary"]}"' in html
```

- [ ] **Step 2: Run** → fails (no module).
- [ ] **Step 3: Implement** the datafile, module, tag/filter, includes, view context, template edits, sass. Keep `all_notes()` an `lru_cache` (copy changes ship with a deploy, like the rest of `datafiles/`).
- [ ] **Step 4: GREEN** on `camp/apps/pesticides`; `invoke styles`.
- [ ] **Step 5: Commit** — `feat(pesticides): add plain-language health notes from a datafile` + trailer.

---

### Task 2: Browser check and wrap-up (controller)

Chrome against port 8002: chemical page (hover a badge for the tooltip; expand "What this means"), product page, a notice page, a place page, the landing explainer and the how-to-read panel. One fix dispatch + scoped re-review for anything found. Ledger. No push.
