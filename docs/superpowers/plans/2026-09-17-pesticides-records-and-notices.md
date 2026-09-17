# Pesticides Records Browser, Section Pages, and Notices Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The researcher tier: a filterable, paginated browser of individual PUR application records with the section map above it; a page per MTRS section; a notices section (active list, monthly archive, notice detail) that sends residents to SprayDays for alerts; and entity pages that link into all of it.

**Architecture:** Three new `vanilla` views over existing models plus the `section-map.html` include from sub-project 2 and the rollup/stats helpers from sub-project 1. Records are read from `PesticideUse` with `select_related`; filters map to the same lookups the v2 API uses (county FK, region → MTRS spatial join, section FK, entity FKs, method, date range, radius). Notices read `PesticideNotice` with `stats._upcoming` for the active window. No new models.

**Tech Stack:** Django 5.2, PostGIS, `django-vanilla-views`, Bulma 0.9, the Leaflet section map from sub-project 2.

**Spec:** `docs/superpowers/specs/2026-09-16-pesticides-explorer-v2-design.md`, section "3. Records browser and NOI section" and "NOI timing".

## Global Constraints

- Commands from the worktree root inside Docker: `docker compose run --rm test pytest <path> -q`; `invoke styles` for CSS.
- Tests: `django.test.TestCase`, fixtures, plain `assert`; aggregate-reading classes use `RollupTestMixin`. The fixture has counties 9001 (Fresno) / 9002 (Kern), sections 9101 (Fresno square lon -119.80..-119.78, lat 36.70..36.72) / 9102 (Kern square lon -119.05..-119.03, lat 35.35..35.37), 9 use rows (see the rollup plan's table), notices 1 (past, Fresno), 2 (2099, Fresno, chlorpyrifos/lorsban), 3 (2099, Kern, gly+chl / roundup+lorsban). Fixture notices have no `point`; tests that need one set it with `update(point=Point(...))`.
- `SqidsField` is not a DB column: resolve sqids only via `Model.objects.filter(sqid=...)`.
- Notices: "active" = `scheduled_application >= now - 4 days` (`stats._upcoming`, `stats.NOTICE_GRACE_DAYS`). Never a "next N days" window. Every notice page carries a "Sign up with SprayDays" link (`https://spraydays.cdpr.ca.gov/`). No alert features of our own.
- Explorer pages never link to raw API endpoints (docs links only).
- URLs are the only state; `qs_replace` preserves params in sort/pagination links; the year picker applies to year-binned data only.
- Never `git add -A`; commit trailer exactly `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; no other AI attribution.
- Shared db; port 8001 belongs to another worktree; use 8002 for this worktree if a server is needed.

---

## File map

| File | Responsibility |
|---|---|
| `camp/apps/pesticides/forms.py` | + `RecordsFilterForm`, `NoticeFilterForm` |
| `camp/apps/pesticides/views.py` | + `RecordsBrowser`, `SectionDetail`, `NoticeList`, `NoticeDetail`; `area_filter()` helper; entity pages link changes |
| `camp/apps/pesticides/urls.py` | + `records/`, `sections/<sqid>/`, `notices/`, `notices/<sqid>/` |
| `camp/templates/pesticides/records.html`, `section-detail.html`, `notice-list.html`, `notice-detail.html` | pages |
| `camp/templates/pesticides/includes/month-bars.html` | 12-bar CSS chart from `by_month` rows |
| `camp/templates/pesticides/includes/records-table.html` | shared records table (records page + section page) |
| `camp/templates/pesticides/includes/notice-rows.html` | shared notice table rows |
| `camp/templates/pesticides/base.html` | sub-nav: Map · Chemicals · Products · Commodities · Records · Notices |
| `camp/templates/pesticides/detail-base.html` | recent records → 5 rows + "Browse all records"; planned → link to notices list |
| `assets/sass/sjvair/pages/pesticides.sass` | month bars, records filters |
| `camp/apps/pesticides/tests/test_records.py`, `test_notices.py`, `test_sections.py` | tests |

---

### Task 1: Records browser

**Files:** `forms.py`, `views.py`, `urls.py`, `records.html`, `includes/records-table.html`, `base.html` (sub-nav), `pesticides.sass`, `tests/test_records.py`

**Interfaces:**
- `views.area_filter(queryset, *, county=None, region=None, section=None, point=None, radius=None, field_prefix='')` → queryset restricted to an area, usable for both `PesticideUse` (`mtrs`/`county` fields) and `PesticideNotice` (same field names). Semantics: `county` (Region) → `county=`; `section` (Region MTRS) → `mtrs=`; `region` (Region other) → `mtrs__boundary__geometry__intersects=region.boundary.geometry` (none() if no boundary); `point`+`radius` → `mtrs__boundary__geometry__distance_lte=(point, D(mi=radius))` with the same degree-bbox prefilter used by the sections API (import `radius_bbox` from `camp.api.v2.pesticides.sections`). Only one of region/section/point applies; county may combine with any.
- `RecordsFilterForm` (GET): `start`, `end` (DateField, optional), `county` (ChoiceField of county slugs, optional), `method` (ChoiceField from `PesticideUse.AerialGround.choices`, optional), plus hidden `region`, `section`, `chemical`, `product`, `commodity` (sqid CharFields), `lat`, `lng` (FloatField), `radius` (ChoiceField 1/3/5). All optional.
- `RecordsBrowser(ExplorerListMixin-like but its own class, vanilla.ListView)`: model `PesticideUse`, `paginate_by = 50`, template `pesticides/records.html`, URL `pesticides:records` at `records/`. Query: resolve `year` via `stats.resolve_year`; default `start`/`end` to Jan 1 / Dec 31 of that year when neither is given (so the page never lists all years by accident); filters by date range, area (`area_filter`), entities (resolved sqids; unknown → `none()`), method. `select_related('county', 'mtrs', 'chemical', 'product', 'commodity')`. Sort allowlist `date` (default `-date` → `application_date` nulls last, then `-pk`), `lbs` (`lbs_chemical`), `acres` (`acres_treated`).
- Totals above the table: `totals = queryset.aggregate(applications=Count('id'), lbs=Sum('lbs_chemical'), acres=Sum('acres_treated'))`, cached 10 minutes under `pesticides:records-totals:<sha1 of sorted filter params>` (the records only change at import). Summary sentence: "2,314 applications, 41,200 lbs, 3,100 acres treated — 2023, Fresno County, Sulfur".
- Context: `form`, `object_list`, `page_obj`, `is_paginated`, `totals`, `summary_sentence`, `sort`, `active_filters` (list of `{label, clear_url}` for entities/area), `map_config` (from `section_map_config`: year, entity identifiers, county slug; center/zoom from the area: section → its centroid at zoom 13; region → boundary centroid at zoom 10; point → lat/lng at zoom 12 with `radius`; county → county centroid zoom 9; else SJV default), `county_map` for the no-JS fallback (county totals for the year), `year_context`.
- Page layout: filter form in a left column (dates, county, method, Apply/Clear; hidden fields carried), map + summary + table on the right. Table columns: date, county, section (link to `pesticides:section-detail`), commodity, product, chemical (with badges), lbs, acres, method. Sortable headers via `sort_link`. Pagination include.

- [ ] **Step 1: Tests (RED)** — `tests/test_records.py`:

```python
from datetime import date
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.pesticides.models import Chemical, Commodity, PesticideUse, Product
from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin
from camp.apps.regions.models import Region


class RecordsBrowserTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.url = reverse('pesticides:records')

    def pks(self, response):
        return [u.pk for u in response.context['object_list']]

    def test_defaults_to_latest_year_newest_first(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        self.assertTemplateUsed(response, 'pesticides/records.html')
        assert self.pks(response) == [6, 5, 4, 3, 2, 1]
        assert response.context['totals'] == {'applications': 6, 'lbs': 740.0, 'acres': 74.0}
        assert response.context['form']['start'].value() == date(2023, 1, 1)

    def test_year_param_sets_range(self):
        response = self.client.get(self.url, {'year': 2022})
        assert self.pks(response) == [9, 8, 7]

    def test_explicit_dates_win(self):
        response = self.client.get(self.url, {'start': '2023-05-01', 'end': '2023-07-31'})
        assert self.pks(response) == [5, 3]

    def test_county_and_method(self):
        assert self.pks(self.client.get(self.url, {'county': 'kern'})) == [5, 3]
        assert self.pks(self.client.get(self.url, {'method': 'A'})) == [5, 3]
        assert self.pks(self.client.get(self.url, {'county': 'fresno', 'method': 'A'})) == []

    def test_entity_filters(self):
        chem = Chemical.objects.get(pk=1)
        assert self.pks(self.client.get(self.url, {'chemical': chem.sqid})) == [3, 2, 1]
        assert self.pks(self.client.get(self.url, {'product': Product.objects.get(pk=2).sqid})) == [5, 4]
        assert self.pks(self.client.get(self.url, {'commodity': Commodity.objects.get(pk=2).sqid})) == [6, 2]
        assert self.pks(self.client.get(self.url, {'chemical': 'nope'})) == []
        assert [f['label'] for f in self.client.get(self.url, {'chemical': chem.sqid}).context['active_filters']] == ['GLYPHOSATE']

    def test_section_filter_centers_map(self):
        section = Region.objects.get(pk=9102)
        response = self.client.get(self.url, {'section': section.sqid})
        assert self.pks(response) == [5, 3]
        cfg = response.context['map_config']
        assert cfg['zoom'] == 13 and cfg['center'].startswith('35.36,-119.04')

    def test_region_filter_uses_spatial_join(self):
        city = Region.objects.create(name='Fresno', slug='fresno-city', type='city', external_id='c1', boundary=None)
        from camp.apps.regions.models import Boundary
        b = Boundary.objects.create(region=city, version='t', geometry='SRID=4326;MULTIPOLYGON (((-119.85 36.65, -119.75 36.65, -119.75 36.75, -119.85 36.75, -119.85 36.65)))')
        city.boundary = b
        city.save()
        response = self.client.get(self.url, {'region': city.sqid})
        assert self.pks(response) == [6, 4, 2, 1]

    def test_radius_filter(self):
        response = self.client.get(self.url, {'lat': 35.36, 'lng': -119.04, 'radius': 1})
        assert self.pks(response) == [5, 3]
        assert response.context['map_config']['radius'] == 1

    def test_sort_and_pagination_keep_filters(self):
        response = self.client.get(self.url, {'sort': '-lbs', 'county': 'fresno'})
        assert self.pks(response) == [6, 1, 2, 4]
        html = response.content.decode()
        assert 'county=fresno' in html

    def test_totals_cached(self):
        self.client.get(self.url)
        PesticideUse.objects.filter(pk=6).delete()
        assert self.client.get(self.url).context['totals']['applications'] == 6

    def test_rows_link_to_section_and_entities(self):
        html = self.client.get(self.url).content.decode()
        assert reverse('pesticides:section-detail', kwargs={'sqid': Region.objects.get(pk=9101).sqid}) in html
        assert Chemical.objects.get(pk=3).get_absolute_url() in html

    def test_nav_has_records(self):
        html = self.client.get(reverse('pesticides:chemical-list')).content.decode()
        assert reverse('pesticides:records') in html
```

`test_rows_link_to_section_and_entities` needs the `section-detail` URL name to exist; Task 1 registers a placeholder `SectionDetail` (Task 2 fills it) so the reverse works.

- [ ] **Step 2: Implement** the form, `area_filter`, `RecordsBrowser`, templates, sub-nav, sass (`.records-filters` compact form; `.records-table td` nowrap for date/lbs), URL entries (`records/`, `sections/<str:sqid>/` → placeholder `SectionDetail(vanilla.TemplateView)`). For the county centroid use `Region.objects.filter(type=COUNTY, slug=...).select_related('boundary')` and `boundary.geometry.centroid` (y = lat, x = lng); format center as `f'{lat:.4f},{lng:.4f}'`. For the radius filter parse floats and validate ranges like the API does.
- [ ] **Step 3: GREEN** on `tests/test_records.py` and the pesticides package; `invoke styles`.
- [ ] **Step 4: Commit** — `feat(pesticides): add the PUR records browser` + trailer.

---

### Task 2: Section pages and the month bars

**Files:** `views.py` (replace the placeholder `SectionDetail`), `section-detail.html`, `includes/month-bars.html`, `pesticides.sass`, `tests/test_sections.py`

**Interfaces:**
- `SectionDetail(vanilla.DetailView)` on `Region` filtered to `type=MTRS`, lookup `sqid`, template `pesticides/section-detail.html`, URL `pesticides:section-detail`. Context: `object`, `year_context`, `rows = PesticideUseRollup.objects.filter(mtrs=object)`, `county_name` (from rollup rows, ordered), `totals = stats.year_totals(rows, year)`, `by_year = stats.by_year(rows)`, `by_month = stats.by_month(rows, year)`, `peak_month` (name of the max month or None), `top_chemicals/top_products/top_commodities` (`stats.top_related`, limit 10; products by `lbs_product`), `upcoming` (active notices with `mtrs=object`), `recent_uses` (5, `PesticideUse.objects.filter(mtrs=object, year=year)`), `records_url` (`records/?section=<sqid>&year=`), `map_config` centered on the section centroid at zoom 13.
- `includes/month-bars.html` expects `by_month` (12 dicts with `month`, `lbs`, `applications`) and `year`; renders a `<div class="month-bars">` with 12 `<div class="bar">` whose inner `<span class="fill" style="height: NN%">` is scaled to the max month, month abbreviations underneath, and a `title` with the pounds. Zero-height bars still render a baseline. Pure CSS.
- Page: header "Section MDM-T14S-R20E-01" + county; stat row (lbs, applications, chemicals used); map; by-month bars with a sentence "Spraying here peaks in March" when data exists; three top lists (reuse `related-card.html`, `show_lbs=True`, `complete=False` with `show_all_url` into the records browser filtered by section + entity? No: keep `show_all_url` = records browser filtered by section); by-year table; active notices in this section (reuse `upcoming-notices.html`); "Browse all records in this section" link; sources footer.

- [ ] **Step 1: Tests (RED)** — `tests/test_sections.py`:

```python
class SectionDetailTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.section = Region.objects.get(pk=9101)
        self.url = reverse('pesticides:section-detail', kwargs={'sqid': self.section.sqid})

    def test_renders(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        ctx = response.context
        assert ctx['county_name'] == 'Fresno County'
        assert ctx['totals'] == {'lbs': 670.0, 'applications': 4, 'counties': 1}
        assert [r.obj.name for r in ctx['top_chemicals']] == ['SULFUR', 'GLYPHOSATE', 'CHLORPYRIFOS']
        assert len(ctx['by_month']) == 12 and ctx['peak_month'] == 'August'
        assert [u.pk for u in ctx['recent_uses']] == [6, 4, 2, 1]
        assert ctx['map_config']['zoom'] == 13 and ctx['map_config']['center'] == '36.7100,-119.7900'
        html = response.content.decode()
        assert 'month-bars' in html and 'Spraying here peaks in August' in html
        assert reverse('pesticides:records') + f'?section={self.section.sqid}' in html

    def test_year_param(self):
        ctx = self.client.get(self.url, {'year': 2022}).context
        assert ctx['totals']['lbs'] == 480.0 and ctx['peak_month'] == 'August'

    def test_notices_in_section(self):
        from camp.apps.pesticides.models import PesticideNotice
        PesticideNotice.objects.filter(pk=2).update(mtrs=self.section)
        ctx = self.client.get(self.url).context
        assert [n.pk for n in ctx['upcoming']] == [2]

    def test_404_for_non_section(self):
        county = Region.objects.get(pk=9001)
        assert self.client.get(reverse('pesticides:section-detail', kwargs={'sqid': county.sqid})).status_code == 404
```

- [ ] **Step 2: Implement**; month names via `calendar.month_name`. Sass: `.month-bars { display:flex; align-items:flex-end; gap:4px; height:120px }`, `.bar { flex:1; display:flex; flex-direction:column; justify-content:flex-end; align-items:center }`, `.fill { width:100%; background:$primary; min-height:2px; border-radius:2px 2px 0 0 }`, `.label { font-size: $size-7; color: $grey }`.
- [ ] **Step 3: GREEN**; `invoke styles`.
- [ ] **Step 4: Commit** — `feat(pesticides): add section pages with monthly bars` + trailer.

---

### Task 3: Notices list, notice detail, and entity-page links

**Files:** `forms.py` (`NoticeFilterForm`), `views.py` (`NoticeList`, `NoticeDetail`; detail-base changes), `urls.py`, `notice-list.html`, `notice-detail.html`, `includes/notice-rows.html`, `detail-base.html`, `tests/test_notices.py`, `tests/test_views.py` (adjust "recent records" expectations)

**Interfaces:**
- `NoticeFilterForm` (GET): `county` (choices), `method` (CharField), hidden `chemical`, `product`, `region`, `section`, `lat`, `lng`, `radius`; `past` (BooleanField; when true show the archive), `month` (1–12), `year` (int) for the archive.
- `NoticeList(vanilla.ListView)`: model `PesticideNotice`, `paginate_by = 50`, template `pesticides/notice-list.html`, URL `pesticides:notice-list` at `notices/`. Default (active): `stats._upcoming(...)` ordered by `scheduled_application`. Archive (`past=1`): `scheduled_application < now - 4 days`, ordered newest first, optionally restricted to `year`/`month` (of `scheduled_application`, in `America/Los_Angeles`). Filters via `area_filter` and entity sqids. `select_related('county', 'mtrs').prefetch_related('chemicals', 'products')`. Context: `form`, `mode` (`active`|`past`), `object_list`, `count`, `map_config` (year = latest, so the map shades current use; notices come from the active endpoint automatically), `active_filters`, `archive_months` (list of `{year, month, label, count}` for the last 24 months with any notice, for the archive sidebar).
- `NoticeDetail(vanilla.DetailView)`: lookup `sqid`, template `pesticides/notice-detail.html`, URL `pesticides:notice-detail` at `notices/<sqid>/`. Context: `object`, `is_active`, `window_end` (scheduled + 4 days), `map_config` centered on `point` (or the section centroid) at zoom 13, `related_notices` (other active notices in the same section, up to 5), `records_url` (records browser filtered by section). Page: heading "Notice of intent · <date>", tag "Active" or "Past", one plain sentence: "Scheduled for <date time>; the grower may begin any time through <window_end date>. A notice is an intention, not a confirmation that spraying happened." Products and chemicals with badges (chemicals link to chemical pages, products to product pages), treated amount + units, method, county, section link, the map, then a prominent box: "Want to be told about notices near you? SprayDays sends texts or emails for the square mile around an address." with the sign-up link.
- Entity pages (`detail-base.html`): "Most recent records" shows 5 rows and a "Browse all N records" link to `records/?<chemical|product|commodity>=<sqid>&year=`; the "Planned applications" section links "See all notices for <name>" to `notices/?<chemical|product>=<sqid>`. Update the existing view tests that asserted 10 recent rows to 5.
- Sub-nav gains "Notices" (Task 1 added "Records"); the landing callout's count links to the notices list.

- [ ] **Step 1: Tests (RED)** — `tests/test_notices.py`:

```python
class NoticeListTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.url = reverse('pesticides:notice-list')

    def test_active_default(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert [n.pk for n in response.context['object_list']] == [2, 3]
        assert response.context['mode'] == 'active'

    def test_filters(self):
        assert [n.pk for n in self.client.get(self.url, {'county': 'kern'}).context['object_list']] == [3]
        chem = Chemical.objects.get(pk=1)
        assert [n.pk for n in self.client.get(self.url, {'chemical': chem.sqid}).context['object_list']] == [3]

    def test_archive(self):
        response = self.client.get(self.url, {'past': 1})
        assert response.context['mode'] == 'past'
        assert [n.pk for n in response.context['object_list']] == [1]
        assert response.context['archive_months'][0]['year'] == 2020
        assert [n.pk for n in self.client.get(self.url, {'past': 1, 'year': 2020, 'month': 1}).context['object_list']] == [1]
        assert self.client.get(self.url, {'past': 1, 'year': 2020, 'month': 2}).context['object_list'] == []

    def test_spraydays_link_present(self):
        assert 'spraydays.cdpr.ca.gov' in self.client.get(self.url).content.decode()


class NoticeDetailTests(TestCase):
    fixtures = ['pesticides-explorer']

    def test_renders_active(self):
        from django.contrib.gis.geos import Point
        PesticideNotice.objects.filter(pk=2).update(point=Point(-119.79, 36.71, srid=4326), mtrs_id=9101)
        notice = PesticideNotice.objects.get(pk=2)
        response = self.client.get(reverse('pesticides:notice-detail', kwargs={'sqid': notice.sqid}))
        assert response.status_code == 200
        ctx = response.context
        assert ctx['is_active'] is True
        assert (ctx['window_end'] - notice.scheduled_application).days == 4
        assert ctx['map_config']['center'] == '36.7100,-119.7900' and ctx['map_config']['zoom'] == 13
        html = response.content.decode()
        assert 'may begin any time through' in html and 'spraydays.cdpr.ca.gov' in html
        assert Chemical.objects.get(pk=2).get_absolute_url() in html
        assert reverse('pesticides:section-detail', kwargs={'sqid': Region.objects.get(pk=9101).sqid}) in html

    def test_past_notice(self):
        notice = PesticideNotice.objects.get(pk=1)
        ctx = self.client.get(reverse('pesticides:notice-detail', kwargs={'sqid': notice.sqid})).context
        assert ctx['is_active'] is False

    def test_404(self):
        assert self.client.get(reverse('pesticides:notice-detail', kwargs={'sqid': 'nope'})).status_code == 404


class EntityPageLinksTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def test_recent_records_are_five_with_browse_link(self):
        chem = Chemical.objects.get(pk=1)
        response = self.client.get(chem.get_absolute_url())
        assert len(response.context['recent_uses']) <= 5
        html = response.content.decode()
        assert reverse('pesticides:records') + f'?chemical={chem.sqid}' in html
        assert reverse('pesticides:notice-list') + f'?chemical={chem.sqid}' in html
```

- [ ] **Step 2: Implement**; archive month labels via `calendar.month_name[m] + ' ' + str(y)`; `archive_months` from `PesticideNotice.objects.annotate(month=TruncMonth('scheduled_application', tzinfo=ZoneInfo('America/Los_Angeles')))...values('month').annotate(count=Count('id')).order_by('-month')[:24]`.
- [ ] **Step 3: GREEN** on the whole `camp/apps/pesticides/tests/`; `invoke styles`.
- [ ] **Step 4: Commit** — `feat(pesticides): add notice pages and link entity pages into the records browser` + trailer.

---

### Task 4: Browser check and wrap-up (controller)

Chrome against port 8002: records page with a county + chemical filter (map recenters, rows link), a section page (bars, lists, notices), notices list (active) and archive, a notice detail, an entity page's new links. One fix dispatch + scoped re-review for anything found. Full suite. Ledger. No push.
