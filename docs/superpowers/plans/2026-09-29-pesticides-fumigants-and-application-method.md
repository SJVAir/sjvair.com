# Fumigants and application method Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Fumigants scope counts re-registered products CDPR doesn't flag, the explorer can narrow to "Applied by air", and every page with use shows how it was applied.

**Architecture:** A stored, data-derived `Product.is_fumigant` (CDPR flag OR contains a fumigant ingredient, classified over all loaded years) replaces `product.fumigant` everywhere the explorer means "is a fumigant". The rollup gains CDPR's per-record `method` in its grain (+0.7% rows); the new `aerial` narrowing reads only the rollup. First, the narrowing plumbing is fixed so every narrowing value (not just "flagged") reaches maps, forms, caches and aggregates.

**Tech Stack:** Django 5 / PostGIS, Postgres raw SQL rollup (`camp/apps/pesticides/rollup.py`), django templates, ES5 map module `assets/js/pesticides/section-map.js`.

**Spec:** `docs/superpowers/specs/2026-09-29-pesticides-fumigants-and-application-method-design.md`

## Global Constraints

- Worktree `/home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+pesticides-explorer`, branch `feature/pesticides-explorer`. All edits there, never in the main checkout.
- **Do not commit, stage, stash or push.** Derek commits. (Every "Commit" step in the standard template is "leave uncommitted".)
- Scope changes only through the scope bar. No new controls that change a page's scope.
- Fumigant ingredient thresholds, verbatim: `FUMIGANT_MIN_LBS = 100`, `FUMIGANT_MIN_SHARE = 0.9`; classified over **all loaded years**, never per year; no exclusions.
- `Product.fumigant` stays CDPR's raw flag (verbose name "CDPR fumigant flag"). The explorer reads `Product.is_fumigant`.
- Method codes verbatim from CDPR: `A`, `G`, `F`, `O`, `''`. Labels: `G` Ground, `A` Air, `F` Field fumigation, `O` Other, `''` Not reported. Display order: Ground, Air, Field fumigation, Other, Not reported. SprayDays `Ground`/`Aircraft`/`Fumigation` map to Ground/Air/Field fumigation.
- New narrowing: value `aerial`, label "Applied by air", after Fumigants in `NARROW_CHOICES`.
- Not-reported note copy, verbatim: "Not reported is mostly structural, landscape and right-of-way use, which is reported in monthly summaries without a method."
- Unflagged-fumigant badge tooltip, verbatim: "Not flagged as a fumigant by CDPR; its active ingredient is almost always applied as a fumigant."
- No aerial map metric. No ground narrowing. No per-year classification.
- Products before chemicals wherever both appear.
- Tests: Django `TestCase`, plain `assert`; prefer building test data inside the test over editing `fixtures/pesticides-explorer.yaml` (its row counts are asserted in `test_fixture.py` and many totals tests). No AI attribution anywhere. Don't align `=`.
- Test harness (`HARNESS <paths>` below):
  ```
  docker compose -f /home/derek/dev/ccac/sjvair.com/docker-compose.yml --project-directory /home/derek/dev/ccac/sjvair.com run --rm -T -e DATABASE_URL=postgis://sjvair:changeme@db:5432/sjvair_fumigants -v /home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+pesticides-explorer:/app test pytest <paths> -q -p no:cacheprovider --create-db
  ```
  Add `-n 4 --dist loadscope` for package/full runs. Full suite before handing back: `HARNESS camp -n 4 --dist loadscope`.
- Migrations: `makemigrations pesticides` proposes an unrelated `commodities` AlterField drift that exists on main — never include it.

## Review Focus

1. **A narrowing value other than "flagged" survives every round trip** — map grid requests, filter-form submits, entity pickers, links built server-side — and never silently becomes `concern=1`. Pinned by Task 1's round-trip tests.
2. **Totals-table readers under a rollup-only narrowing** (fumigant, aerial) never return unnarrowed or empty numbers — landing by-year trend, `county_totals`, `_place_stats` with `?year=all` on a county page. Pinned in Tasks 1 and 4.
3. **Classification is stable and idempotent** — re-running doesn't change results; an ingredient that stops qualifying loses the category; CDPR-flagged products stay fumigant. Pinned in Task 2.
4. **A narrowing that excludes the page's subject** (e.g. `narrow=aerial` on a product never applied by air) renders the normal empty states, not an error or the unscoped page. Pinned in Task 4.
5. **The method breakdown's shares add to 100% and "Not reported" is labelled, not dropped**, including pages where every record is blank. Pinned in Task 5.

---

## File Structure

- `camp/apps/pesticides/stats.py` — narrowing (`NARROW_AERIAL`, `narrow_needs_rollup`, `narrow_rows`, `narrow_notices`), `METHOD_LABELS`, `by_method`, landing fixes.
- `camp/apps/pesticides/fumigants.py` (new) — `classify_fumigants()`.
- `camp/apps/pesticides/models.py` — `Product.is_fumigant`, `PesticideUseRollup.method` + constraint.
- `camp/apps/pesticides/rollup.py` — method in `REBUILD_SQL`; classification after rebuilds.
- `camp/apps/pesticides/management/commands/rebuild_pesticide_rollup.py`, `import_pur.py` — hooks, `--fumigants-only`.
- `camp/apps/pesticides/views.py`, `places.py`, `spraydays.py`, `notes.py`, `forms.py`, `admin.py`.
- `camp/api/v2/pesticides/sections.py`, `endpoints.py`, `serializers.py`, `filters.py`.
- `camp/templates/pesticides/…` — scope-hidden, base banners, home, lists, place, detail-base, section-summary, product badges/detail/list, about, new `includes/method-breakdown.html`.
- `assets/js/pesticides/section-map.js`, `entity-picker.js`.
- Tests under `camp/apps/pesticides/tests/` and `camp/api/v2/pesticides/tests.py`.

---

### Task 1: Every narrowing value flows through (fix the concern-only plumbing)

Pre-existing bugs, found by inventory, that make the Restricted and Fumigants narrowings partly behave as "Flagged chemicals", and that would drop `aerial` entirely. Fix them generically (any narrowing value), not per value.

**Files:**
- Modify: `camp/apps/pesticides/stats.py` (~l.213-255 narrowing helpers; `county_totals` ~931-953; `_build_landing_stats` ~1100-1180)
- Modify: `camp/apps/pesticides/views.py` (`section_map_config` ~1159; `cached_stat` ~815-832; `ChemicalList.apply_filters` ~469; `ProductList.get_queryset` ~646 / `apply_filters` ~657; `ExplorerListMixin.get_summary_sentence` ~402; `CommodityList.lbs_applied` ~734; `ChemicalDetail.concern_applies` ~985; `ProductDetail.concern_applies` ~1022; `ExplorerDetailMixin` `notices_url` ~930; `SectionDetail` records_url ~1761; `RecordsBrowser.get_summary_sentence` ~1569)
- Modify: `camp/apps/pesticides/places.py` (`_place_stats` ~510-512)
- Modify: `camp/api/v2/pesticides/endpoints.py` (`EntitySearch` ~280-313)
- Modify: templates `includes/scope-hidden.html:8`, `base.html:92-101`, `home.html:102`, `commodity-list.html:24`, `product-list.html:35`, `place.html:171`
- Modify: `assets/js/pesticides/section-map.js` (`DATA_KEYS` ~1283, `commonParams` ~1606), `assets/js/pesticides/entity-picker.js` (~258-268)
- Test: `camp/apps/pesticides/tests/test_stats.py`, `test_views.py`, `test_places.py`, `camp/api/v2/pesticides/tests.py`

**Interfaces:**
- Produces: `stats.narrow_needs_rollup(narrow) -> bool` (replaces `narrow_needs_product`; True for `NARROW_FUMIGANT` now; Task 4 adds `NARROW_AERIAL`). Map container attribute `data-narrow` (the narrow value) replacing `data-concern`; the grid endpoints receive `narrow=<value>` (they already read it via `stats.resolve_narrow`). Hidden scope field `narrow`.

- [ ] **Step 1: Write failing tests.** One test per defect, each asserting behaviour under `narrow=restricted` or `narrow=fumigant` (the fixture has a fumigant product: LORSBAN 4E pk 2; a restricted chemical: CHLORPYRIFOS pk 2):
  ```python
  class NarrowPlumbingTests(RollupTestMixin, TestCase):
      fixtures = ['pesticides-explorer']

      def setUp(self):
          cache.clear()

      def test_map_config_carries_the_narrow_value(self):
          cfg = views.section_map_config(2023, concern='fumigant')
          assert cfg['map']['data']['narrow'] == 'fumigant'
          assert 'concern' not in cfg['map']['data']

      def test_hidden_scope_field_keeps_the_narrowing(self):
          html = self.client.get(reverse('pesticides:records'), {'narrow': 'restricted'}).content.decode()
          assert '<input type="hidden" name="narrow" value="restricted">' in html
          assert 'name="concern"' not in html

      def test_landing_trend_is_not_empty_under_fumigant(self):
          data = stats.landing_stats(2023, narrow='fumigant')  # use the real signature; see stats.landing_stats
          assert data['by_year'] and sum(r['lbs'] for r in data['by_year']) > 0

      def test_county_totals_under_fumigant_counts_only_fumigant_products(self):
          rows = stats.county_totals(2023, False, 'fumigant')
          expected = PesticideUseRollup.objects.filter(year=2023, product__fumigant=True).aggregate(s=Sum('lbs_chemical'))['s']
          assert sum(r['lbs'] for r in rows) == expected

      def test_detail_all_years_cache_is_per_narrowing(self):
          chem = Chemical.objects.get(pk=2)
          a = self.client.get(chem.get_absolute_url(), {'year': 'all', 'narrow': 'restricted'}).context['totals']
          b = self.client.get(chem.get_absolute_url(), {'year': 'all', 'narrow': 'fumigant'}).context['totals']
          # restricted keeps every CHLORPYRIFOS row; fumigant keeps only LORSBAN rows -- same here, so compare keys instead:
          keys = [k for k in cache._cache.keys() if 'detail' in str(k)] if hasattr(cache, '_cache') else []
          assert any('restricted' in str(k) for k in keys) and any('fumigant' in str(k) for k in keys)

      def test_commodity_list_pounds_follow_the_narrowing_not_flagged(self):
          ctx = self.client.get(reverse('pesticides:commodity-list'), {'narrow': 'fumigant'}).context
          lbs = {c.name: c.lbs_applied for c in ctx['object_list']}
          expected = dict(PesticideUseRollup.objects.filter(year=2023, product__fumigant=True)
              .values_list('commodity__name').annotate(s=Sum('lbs_chemical')))
          assert lbs == expected

      def test_banner_names_the_active_narrowing(self):
          html = self.client.get(reverse('pesticides:chemical-list'), {'narrow': 'restricted'}).content.decode()
          assert 'Restricted materials' in html
          assert 'flagged chemicals only' not in html

      def test_entity_search_honours_narrow(self):
          url = reverse('api:v2:pesticides:entity-search')
          data = self.client.get(url, {'q': 'a', 'narrow': 'fumigant'}).json()['data']
          names = {r['name'] for r in data if r.get('kind') == 'commodity'}
          assert names <= set(PesticideUseRollup.objects.filter(product__fumigant=True).values_list('commodity__name', flat=True))
  ```
  Adapt names to the real signatures (read `stats.landing_stats`, `stats.county_totals`, `EntitySearch` response shape first) but keep each assertion's intent. For the cache-key test, prefer asserting via `stats.all_years_key` construction if the cache backend in tests doesn't expose keys: test that `ExplorerDetailMixin.cached_stat` builds different keys for different narrowings (call it on a view instance with `concern_active` set to each value and capture the key via `mock.patch('camp.apps.pesticides.stats.cached')`).
  Also add to `camp/api/v2/pesticides/tests.py`: `SectionList` with `narrow=restricted` returns different `lbs` than `concern=1` for a section where they differ (build a PesticideUse with a restricted, non-flagged chemical if the fixture has none — check `Chemical.is_of_concern`).
- [ ] **Step 2: Run to verify they fail.** `HARNESS camp/apps/pesticides/tests/test_stats.py camp/apps/pesticides/tests/test_views.py camp/api/v2/pesticides/tests.py -k Narrow`
- [ ] **Step 3: Implement.**
  - `stats.py`: rename `narrow_needs_product` → `narrow_needs_rollup` (docstring: "the narrowing can only be answered from the rollup — the totals tables carry neither the product for chemical rows nor the application method"), returning `narrow in {NARROW_FUMIGANT}`; update callers (`county_totals`, `places._place_stats`). In `_build_landing_stats`, build `totals`/`by_year` from the rollup whenever `concern` is truthy (use `valley_by_year`'s rollup branch), from `PesticideUseTotal` only when unnarrowed.
  - `views.section_map_config`: replace `'concern': '1' if concern else ''` with `'narrow': concern or ''` (the param already carries the narrow value or ''). `section-map.js`: `DATA_KEYS` `'concern'` → `'narrow'`; `commonParams` sends `narrow: this.data.narrow`. `entity-picker.js`: read/send `narrow` (form field `narrow`, URL `narrow=`, `.section-map[data-narrow]`), still accepting a legacy `concern=1` in the URL as `narrow=concern`.
  - `scope-hidden.html`: `{% if concern %}<input type="hidden" name="narrow" value="{{ concern }}">{% endif %}` (check what `concern` holds in template context — `year_context` sets it from `scope_concern`, the narrow value).
  - `cached_stat`: `scope = f'{scope}:{self.concern_active}'` (the value, not `CONCERN_PARAM`).
  - Concern-only logic keyed on `== stats.NARROW_CONCERN`: `ChemicalList.apply_filters` (the `of_concern_chemicals()` filter), `ProductList` concern-ingredient prefetch/filter, `CommodityList.lbs_applied` (`commodity_concern_lbs` only for concern; other narrowings use `lbs_subquery(..., concern=self.concern)` which reads the rollup), `_build_landing_stats` flagged board (`if not concern` → shown unless narrowed to something other than concern), templates `home.html:102`, `commodity-list.html:24`, `product-list.html:35` (`{% if concern == 'concern' %}`).
  - `concern_applies`: `ChemicalDetail` returns `is_of_concern` for concern, `is_restricted` for restricted, `True` otherwise; `ProductDetail` likewise with its ingredients (concern ingredients / restricted ingredients), `True` for fumigant (and later aerial).
  - Summary sentences (`ExplorerListMixin.get_summary_sentence`, `RecordsBrowser.get_summary_sentence`) and `place.html:171`: use `stats.narrow_label(concern)` instead of "of concern"/"flagged chemicals only".
  - `base.html:92-101` banners: keep the per-value copy, with an explicit branch per value (no catch-all "flagged" else); Task 4 adds `aerial`.
  - Links: `notices_url` and `SectionDetail` records URL use `stats.scope_param(...)`/`narrow=` instead of `&concern=1`.
  - `EntitySearch`: `narrow = stats.resolve_narrow(params)`; when set, existence/pounds come from `stats.narrow_rows(PesticideUseRollup…, narrow)` instead of `concern_rows`.
- [ ] **Step 4: Run to verify they pass, then the pesticides + API packages.** `HARNESS camp/apps/pesticides/tests camp/api/v2/pesticides -n 4 --dist loadscope` — all green. Existing tests asserting `data-concern` / `name="concern"` are updated to the new names (not deleted).
- [ ] **Step 5: Leave uncommitted.**

---

### Task 2: Classify fumigants (`Product.is_fumigant`)

**Files:**
- Modify: `camp/apps/pesticides/models.py` (`Product` ~253)
- Create: `camp/apps/pesticides/migrations/00NN_product_is_fumigant.py` (via makemigrations, pesticides only)
- Create: `camp/apps/pesticides/fumigants.py`
- Modify: `camp/apps/pesticides/rollup.py` (`rebuild_all`), `management/commands/import_pur.py` (~105-108), `management/commands/rebuild_pesticide_rollup.py`
- Test: `camp/apps/pesticides/tests/test_fumigants.py` (new), `test_rollup.py`

**Interfaces:**
- Produces: `Product.is_fumigant` (BooleanField, default False, db_index=True); `fumigants.classify_fumigants() -> dict` with keys `chemicals` (int, ingredients now in the fumigant category), `products` (int, products now `is_fumigant`), `added` (int, `is_fumigant` but not CDPR-flagged); constants `FUMIGANT_MIN_LBS = 100`, `FUMIGANT_MIN_SHARE = 0.9`.

- [ ] **Step 1: Write the failing tests** (`test_fumigants.py`), building data in the test:
  ```python
  from django.test import TestCase
  from camp.apps.pesticides import fumigants
  from camp.apps.pesticides.models import Chemical, PesticideUse, Product, ProductChemical

  class ClassifyFumigantsTests(TestCase):
      fixtures = ['pesticides-explorer']

      def add_use(self, product, chemical, lbs, method, year=2023, n=1):
          for _ in range(n):
              PesticideUse.objects.create(
                  year=year, use_no=PesticideUse.objects.count() + 10_000,
                  product=product, chemical=chemical, lbs_chemical=lbs, aerial_ground=method,
              )  # fill required fields the model needs (read PesticideUse); copy from a fixture row

      def setUp(self):
          self.telone = Chemical.objects.create(chem_code=90001, name='1,3-DICHLOROPROPENE')
          self.flagged = Product.objects.create(prodno=90001, reg_number='62719-32-AA', name='TELONE OLD', fumigant=True)
          self.reregistered = Product.objects.create(prodno=90002, reg_number='95290-1-AA', name='TELONE II', fumigant=False)
          for p in (self.flagged, self.reregistered):
              ProductChemical.objects.create(product=p, chemical=self.telone, pct=97.5)  # match real field names
          self.add_use(self.reregistered, self.telone, 1000, 'F')
          self.add_use(self.flagged, self.telone, 50, 'G')

      def test_unflagged_product_with_a_fumigant_ingredient_becomes_fumigant(self):
          result = fumigants.classify_fumigants()
          self.telone.refresh_from_db(); self.reregistered.refresh_from_db()
          assert Chemical.Category.FUMIGANT in self.telone.categories
          assert self.reregistered.is_fumigant and not self.reregistered.fumigant
          assert result['added'] >= 1

      def test_cdpr_flagged_products_stay_fumigant(self):
          fumigants.classify_fumigants()
          assert Product.objects.get(pk=self.flagged.pk).is_fumigant
          assert Product.objects.get(pk=2).is_fumigant  # LORSBAN 4E, fumigant=True in the fixture

      def test_below_share_threshold_does_not_qualify(self):
          self.add_use(self.reregistered, self.telone, 200, 'G')  # 1050/1250 = 84% < 90%
          fumigants.classify_fumigants()
          self.telone.refresh_from_db()
          assert Chemical.Category.FUMIGANT not in (self.telone.categories or [])
          assert not Product.objects.get(pk=self.reregistered.pk).is_fumigant

      def test_below_pound_floor_does_not_qualify(self):
          PesticideUse.objects.filter(chemical=self.telone).update(lbs_chemical=40)  # 80 lbs < 100
          fumigants.classify_fumigants()
          self.telone.refresh_from_db()
          assert Chemical.Category.FUMIGANT not in (self.telone.categories or [])

      def test_idempotent_and_clears_stale_category(self):
          fumigants.classify_fumigants(); first = set(Product.objects.filter(is_fumigant=True).values_list('pk', flat=True))
          fumigants.classify_fumigants(); assert set(Product.objects.filter(is_fumigant=True).values_list('pk', flat=True)) == first
          self.add_use(self.reregistered, self.telone, 5000, 'G')
          fumigants.classify_fumigants(); self.telone.refresh_from_db()
          assert Chemical.Category.FUMIGANT not in (self.telone.categories or [])

      def test_other_categories_are_untouched(self):
          chlorpyrifos = Chemical.objects.get(pk=2)
          before = set(chlorpyrifos.categories)
          fumigants.classify_fumigants(); chlorpyrifos.refresh_from_db()
          assert set(chlorpyrifos.categories) - {Chemical.Category.FUMIGANT} == before - {Chemical.Category.FUMIGANT}
  ```
  Read `PesticideUse`, `Product`, `ProductChemical` field names first and adjust the constructors; keep the assertions. Add to `test_rollup.py`: `rollup.rebuild_all()` classifies (a product set up as above is `is_fumigant` afterwards), and `rebuild_pesticide_rollup --fumigants-only` runs only the classification (rollup row count unchanged, output mentions the counts).
- [ ] **Step 2: Run to verify they fail.** `HARNESS camp/apps/pesticides/tests/test_fumigants.py camp/apps/pesticides/tests/test_rollup.py`
- [ ] **Step 3: Implement.**
  - `Product`: `fumigant = models.BooleanField(_('CDPR fumigant flag'), default=False)` (verbose name only) and
    ```python
    # CDPR's flag, or a product containing an ingredient that is almost always
    # applied as a fumigant (fumigants.classify_fumigants). CDPR's flag misses
    # re-registrations -- the 2021 Telone products carry none.
    is_fumigant = models.BooleanField(_('Fumigant'), default=False, db_index=True)
    ```
    `docker compose ... run --rm web python manage.py makemigrations pesticides` (worktree-mounted as in the harness, using the `web` service), then delete any `commodities` operation it adds.
  - `fumigants.py`:
    ```python
    """
    Which products are fumigants. CDPR flags fumigants per product
    registration (PRODUCT.fumigant_sw) and misses re-registrations -- the 2021
    Telone products carry no flag. So an active ingredient counts as a fumigant
    when almost all of its reported pounds, across every loaded year, came from
    CDPR-flagged products or field fumigation (aer_gnd_ind 'F'); a product is a
    fumigant when CDPR flags it or it contains one. Across all years rather than
    per year, so no product flips between years as its use shifts.
    """
    from django.db import connection, transaction
    from django.db.models import Q, Sum

    from camp.apps.pesticides.models import Chemical, PesticideUse, Product

    FUMIGANT_MIN_LBS = 100
    FUMIGANT_MIN_SHARE = 0.9
    FUMIGANT = Chemical.Category.FUMIGANT


    def fumigant_chemical_ids():
        rows = (
            PesticideUse.objects.filter(chemical__isnull=False)
            .values('chemical')
            .annotate(
                total=Sum('lbs_chemical'),
                fumigant=Sum('lbs_chemical', filter=Q(product__fumigant=True) | Q(aerial_ground='F')),
            )
        )
        return {
            r['chemical'] for r in rows
            if (r['total'] or 0) >= FUMIGANT_MIN_LBS and (r['fumigant'] or 0) >= FUMIGANT_MIN_SHARE * r['total']
        }


    @transaction.atomic
    def classify_fumigants():
        ids = fumigant_chemical_ids()
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE pesticides_chemical SET categories = array_remove(categories, %s) "
                "WHERE %s = ANY(categories) AND NOT (id = ANY(%s))",
                [FUMIGANT, FUMIGANT, list(ids)],
            )
            cursor.execute(
                "UPDATE pesticides_chemical SET categories = array_append(COALESCE(categories, '{}'), %s) "
                "WHERE id = ANY(%s) AND NOT (%s = ANY(COALESCE(categories, '{}')))",
                [FUMIGANT, list(ids), FUMIGANT],
            )
        by_ingredient = Product.objects.filter(product_chemicals__chemical__in=ids).values('pk')
        Product.objects.update(is_fumigant=False)
        Product.objects.filter(Q(fumigant=True) | Q(pk__in=by_ingredient)).update(is_fumigant=True)
        return {
            'chemicals': len(ids),
            'products': Product.objects.filter(is_fumigant=True).count(),
            'added': Product.objects.filter(is_fumigant=True, fumigant=False).count(),
        }
    ```
    Check the real table/column names (`categories` is an ArrayField on `pesticides_chemical`; confirm `db_table`). If `Product.objects.update(is_fumigant=False)` over all products is slow on the real DB, restrict it to `is_fumigant=True` rows.
  - `rollup.rebuild_all()`: after rebuilding every year, `fumigants.classify_fumigants()`; return value unchanged (tests assert it). `import_pur`: after `rollup.rebuild_year(year)`, call `classify_fumigants()` and print its counts. `rebuild_pesticide_rollup`: `--fumigants-only` (runs only the classification and prints counts, then `refresh_landing_stats()`); `--all` prints the classification counts; `--totals-only` does not classify.
- [ ] **Step 4: Run to verify they pass.** Same command; then `HARNESS camp/apps/pesticides/tests -n 4 --dist loadscope`.
- [ ] **Step 5: Leave uncommitted.**

---

### Task 3: The explorer reads `is_fumigant`; SprayDays links Telone

**Files:**
- Modify: `stats.py:254` (`narrow_rows` fumigant), `:265` (`narrow_notices`), `:1160-1161` (`products_fumigant`), `LANDING_KEY` (`:27`, `v3` → `v4`, with a comment line like the existing ones)
- Modify: `views.py:662-664`, `:692-695` (`ProductList` filter + description), `forms.py:40` (label stays "Fumigant"; filters `is_fumigant`), `notes.py:71-72`, `admin.py:28,30,38,70` (display/filter `is_fumigant`; keep `fumigant` visible in the product admin as "CDPR fumigant flag")
- Modify: `camp/api/v2/pesticides/serializers.py:38` (`fumigant` reads `is_fumigant`; add `cdpr_fumigant` = raw flag), `filters.py:45` (the `fumigant` filter filters `is_fumigant`)
- Modify: templates `product-list.html:43`, `product-detail.html:15`, `includes/product-badges.html:6` (badge on `is_fumigant`; tooltip when `is_fumigant and not fumigant`, using the existing bulma-tooltip badge pattern in that include), `about.html` (`#methodology` — a paragraph on how fumigants are decided and that the earlier Fumigants figures for 2021 on were ~30–40% low)
- Modify: `camp/apps/pesticides/spraydays.py` (`_product_pks_from_raw` ~90, `product_map` ~144)
- Test: `test_views.py`, `test_stats.py`, `test_notes.py`, `camp/api/v2/pesticides/tests.py`, `test_spraydays.py`

**Interfaces:**
- Consumes: `Product.is_fumigant` (Task 2).
- Produces: API product field `cdpr_fumigant` (bool).

- [ ] **Step 1: Write failing tests.** Set `Product.objects.filter(pk=1).update(is_fumigant=True)` (ROUNDUP, `fumigant=False`) and `pk=2` (LORSBAN, `fumigant=True`) `is_fumigant=True`, then assert:
  - `narrow=fumigant` on the records browser / a commodity page / the sections API includes ROUNDUP's rows.
  - `narrow_notices(..., 'fumigant')` includes notice 3 (lists product 1).
  - Landing `products_fumigant` counts ROUNDUP.
  - Product page for ROUNDUP shows the "Fumigant" badge with the verbatim tooltip; LORSBAN shows the badge without it.
  - The fumigant health note appears for ROUNDUP (`notes.keys_for_product`).
  - API `/api/2.0/pesticides/products/<ROUNDUP sqid>/` → `fumigant: true, cdpr_fumigant: false`; `?fumigant=true` list includes it.
  - SprayDays: `_product_pks_from_raw([{'EPARegNo': '95290-1'}], product_map)` links a product whose `reg_number` is `'95290-1-AA'` (and `'95290-1-AA'` still links exactly).
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.** Every "is a fumigant" reader switches to `is_fumigant` (the inventory's list above). SprayDays: first inspect a real payload — run in the web container (`docker exec` into the 8002 container `sjvair-web-run-9fa08fbbbf15`, or `docker compose ... run --rm web python manage.py shell`) a call to the SprayDays client's `get_applications(comtrs)` for the COMTRS of notice application ids 2093917 or 2095139 (look up `PesticideNotice.objects.get(application_id=2093917).comtrs`), print the `Products` entries, and record the `EPARegNo` format in the report. Then normalise both sides to the company-product part: `re.match(r'^\s*(\d+)-(\d+)', value)` → `'95290-1'`; build `product_map` keyed on that (keep the first/lowest `prodno` on collisions, or prefer an exact full match when present). Don't change the data model.
- [ ] **Step 4: Run to verify they pass; then** `HARNESS camp/apps/pesticides/tests camp/api/v2/pesticides -n 4 --dist loadscope`.
- [ ] **Step 5: Leave uncommitted.**

---

### Task 4: Method in the rollup; the "Applied by air" narrowing

**Files:**
- Modify: `models.py` (`PesticideUseRollup` ~474-535: `method` field, constraint fields), new migration (pesticides only)
- Modify: `rollup.py` (`REBUILD_SQL`)
- Modify: `stats.py` (`NARROW_AERIAL`, `NARROW_CHOICES`, `narrow_needs_rollup`, `narrow_rows`, `narrow_notices`)
- Modify: `views.py` (`ChemicalDetail`/`ProductDetail.concern_applies` return True for aerial — already so after Task 1), `base.html` banner branch for `aerial`, `includes/scope-picker.html` tooltip text for the new option, `about.html` (a sentence under the Narrow-to description)
- Modify: `RecordsBrowser` — its narrowing runs on raw `PesticideUse`: `narrow_rows` on `PesticideUse` must use `aerial_ground='A'` (add a `field` choice: `narrow_rows(rows, narrow, method_field='method')`, the records browser passes `method_field='aerial_ground'`)
- Test: `test_rollup.py`, `test_stats.py`, `test_views.py`, `test_places.py`, `test_notices.py`, `test_records.py`, `camp/api/v2/pesticides/tests.py`

**Interfaces:**
- Consumes: `narrow_needs_rollup` (Task 1).
- Produces: `PesticideUseRollup.method` (`CharField(max_length=1, blank=True, default='')`); `stats.NARROW_AERIAL = 'aerial'`; `narrow_rows(rows, narrow, method_field='method')`.

- [ ] **Step 1: Write failing tests.** Fixture aerial rows: use pks 3, 5, 8 (`A`, all county 9002 / section 9102); ground: 1, 2, 4, 6, 7, 9.
  ```python
  class AerialNarrowingTests(RollupTestMixin, TestCase):
      fixtures = ['pesticides-explorer']

      def setUp(self):
          cache.clear()

      def test_rollup_carries_method(self):
          assert set(PesticideUseRollup.objects.filter(year=2023).values_list('method', flat=True)) == {'A', 'G'}
          assert PesticideUseRollup.objects.filter(year=2023, method='A').aggregate(s=Sum('lbs_chemical'))['s'] == 70.0  # uses 3 + 5

      def test_totals_still_sum_every_method(self):
          assert PesticideUseTotal.objects.filter(year=2023, chemical__isnull=False).aggregate(s=Sum('lbs_chemical'))['s'] == 740.0

      def test_two_records_differing_only_by_method_make_two_rows(self):
          use = PesticideUse.objects.get(pk=1)
          use.pk = None; use.use_no = 99999; use.aerial_ground = 'A'; use.save()
          rollup.rebuild_year(2023)
          assert PesticideUseRollup.objects.filter(year=2023, mtrs_id=9101, chemical_id=1, product_id=1, commodity_id=1, month=3).count() == 2

      def test_pages_narrow_to_air(self):
          chem = Chemical.objects.get(pk=1)
          assert self.client.get(chem.get_absolute_url(), {'narrow': 'aerial'}).context['totals']['lbs'] == 30.0
          place = Region.objects.get(pk=9001)  # Fresno: no aerial use in the fixture
          ctx = self.client.get(reverse('pesticides:region', kwargs={'sqid': place.sqid, 'slug': place.slug}), {'narrow': 'aerial'}).context
          assert not ctx['totals']['applications']  # renders, empty

      def test_county_totals_and_landing_under_aerial(self):
          assert {r['county'] for r in stats.county_totals(2023, False, 'aerial') if r['lbs']} == {'Kern'}  # adapt to the row shape
          landing = stats.landing_stats(2023, narrow='aerial')
          assert sum(r['lbs'] for r in landing['by_year'] if r['year'] == 2023) == 70.0

      def test_sections_api_narrows_to_air(self):
          data = self.client.get(reverse('api:v2:pesticides:section-list'), {'bbox': '-121,35,-118,38', 'narrow': 'aerial'}).json()
          lbs = {f['id']: f['properties']['lbs'] for f in data['features']}  # adapt to the response shape
          assert lbs.get(Region.objects.get(pk=9101).sqid, 0) == 0 and lbs[Region.objects.get(pk=9102).sqid] == 70.0

      def test_notices_narrow_to_aircraft(self):
          # fixture notice 3's application_method is "Aerial"; set it to SprayDays' real "Aircraft"
          PesticideNotice.objects.filter(pk=3).update(application_method='Aircraft')
          assert list(stats.narrow_notices(PesticideNotice.objects.all(), 'aerial').values_list('pk', flat=True)) == [3]

      def test_records_browser_narrows_raw_records(self):
          ctx = self.client.get(reverse('pesticides:records'), {'narrow': 'aerial', 'year': 2023}).context
          assert {u.pk for u in ctx['object_list']} == {3, 5}

      def test_county_page_all_years_under_aerial_reads_the_rollup(self):
          kern = Region.objects.get(pk=9002)
          ctx = self.client.get(reverse('pesticides:region', kwargs={'sqid': kern.sqid, 'slug': kern.slug}), {'year': 'all', 'narrow': 'aerial'}).context
          assert ctx['totals']['lbs'] == 130.0  # 30 + 40 + 60

      def test_scope_bar_offers_applied_by_air(self):
          html = self.client.get(reverse('pesticides:chemical-list')).content.decode()
          assert 'narrow=aerial' in html and 'Applied by air' in html
  ```
  Adapt `county_totals`/landing/section response shapes and region URL kwargs to the real code; keep each intent. Update `test_rollup.py`'s `rebuild_year(2023) == 6` / `rebuild_all()` expectations only if they change (they shouldn't: every fixture row already has a distinct key).
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.**
  - Model: `method = models.CharField(_('Application method'), max_length=1, blank=True, default='')` with a comment ("CDPR's aer_gnd_ind: A aerial, G ground, F field fumigation, O other, blank not reported"); add `'method'` to the `pesticides_rollup_key` fields. Migration: pesticides only. The migration only adds the column and swaps the constraint — existing rows get `''` and the deploy's full rebuild fills them.
  - `REBUILD_SQL`: add `method` to the INSERT column list, `COALESCE(aerial_ground, '') AS method` to the SELECT, and `method` to the GROUP BY (mind the existing comment about `month` resolving to the SELECT alias — `method` has the same property; extend that comment).
  - `stats`: `NARROW_AERIAL = 'aerial'`; `NARROW_CHOICES` gains `(NARROW_AERIAL, 'Applied by air')` last; `narrow_needs_rollup` returns `narrow in {NARROW_FUMIGANT, NARROW_AERIAL}`; `narrow_rows(rows, narrow, method_field='method')`: `if narrow == NARROW_AERIAL: return rows.filter(**{method_field: 'A'})`; `narrow_notices`: `notices.filter(application_method__iexact='Aircraft')`.
  - Records browser: pass `method_field='aerial_ground'` where it calls `narrow_rows` on `PesticideUse`.
  - `base.html` banner `{% elif concern == 'aerial' %}` with copy in the same voice as the others: "Showing only pesticide use applied by aircraft." `scope-picker.html` tooltip for the option: "Applications reported as made by aircraft (CDPR's application method A)". About: one sentence in the Narrow-to description.
- [ ] **Step 4: Run to verify they pass; then** `HARNESS camp/apps/pesticides/tests camp/api/v2/pesticides -n 4 --dist loadscope`.
- [ ] **Step 5: Leave uncommitted.**

---

### Task 5: "How it was applied" breakdown

**Files:**
- Modify: `stats.py` (`METHOD_LABELS`, `METHOD_ORDER`, `by_method`)
- Create: `camp/templates/pesticides/includes/method-breakdown.html`
- Modify: `views.py` (`ExplorerDetailMixin.get_context_data` ~900: `by_method=self.cached_stat('by_method', lambda: stats.by_method(rows, year, self.lbs_field, all_years=all_years))`; `section_summary` ~1644-1687 adds `by_method`), `places.py` (`_place_stats` adds `by_method` to its cached `data`)
- Modify: templates `detail-base.html` (inside `{% if by_year %}`, left column, after the by-year table include at ~:35), `place.html` (a block after the By year / By month row, ~:111), `includes/section-summary.html` (after "Applications by year", ~:31)
- Modify: `forms.py:106-110` (`RecordsFilterForm.method` choices from `METHOD_LABELS` in display order), `includes/records-table.html:41` (label via `METHOD_LABELS`, "Not reported" for blank)
- Modify: CSS for the stacked bar — the explorer's stylesheet (grep `assets/sass` for the pesticides partial the stat row / by-year table use; plain CSS file `assets/css/pesticides/*.css` if that's where page styles live) — tones from the existing palette custom properties; each segment has a `title`/`aria-label` "Air: 6.1%".
- Test: `test_stats.py`, `test_views.py`, `test_places.py`, `test_sections.py`, `test_records.py`

**Interfaces:**
- Consumes: `PesticideUseRollup.method` (Task 4).
- Produces: `stats.METHOD_LABELS = {'G': 'Ground', 'A': 'Air', 'F': 'Field fumigation', 'O': 'Other', '': 'Not reported'}`, `stats.METHOD_ORDER = ('G', 'A', 'F', 'O', '')`, `stats.by_method(rows, year, lbs_field='lbs_chemical', all_years=False) -> list[dict]` of `{'method', 'label', 'lbs', 'share', 'applications'}` in `METHOD_ORDER`, rows with zero pounds and zero applications omitted, `share` = lbs / total lbs (0–1; 0 when total is 0).

- [ ] **Step 1: Write failing tests.**
  ```python
  class ByMethodTests(RollupTestMixin, TestCase):
      fixtures = ['pesticides-explorer']

      def test_breakdown_and_shares(self):
          rows = PesticideUseRollup.objects.all()
          out = stats.by_method(rows, 2023)
          assert [r['method'] for r in out] == ['G', 'A']
          assert [r['lbs'] for r in out] == [670.0, 70.0]
          assert abs(sum(r['share'] for r in out) - 1) < 1e-9
          assert out[1]['label'] == 'Air' and out[1]['applications'] == 2

      def test_not_reported_is_labelled_not_dropped(self):
          PesticideUseRollup.objects.filter(year=2023).update(method='')
          out = stats.by_method(PesticideUseRollup.objects.all(), 2023)
          assert [(r['method'], r['label'], r['share']) for r in out] == [('', 'Not reported', 1.0)]

      def test_all_years(self):
          out = stats.by_method(PesticideUseRollup.objects.all(), None, all_years=True)
          assert {r['method']: r['lbs'] for r in out} == {'G': 1150.0, 'A': 130.0}
  ```
  Page tests: a chemical page (`Chemical pk 1`, 2023) renders `method-breakdown` with "Ground" and "Air" and the verbatim Not-reported note; the Kern county page and section 9102's page render it; a page with no use in the scope year doesn't render it; `narrow=aerial` on a chemical page shows a single "Air 100%" row; records browser method select lists "Field fumigation" and "Not reported" in order.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.**
  ```python
  METHOD_LABELS = {'G': 'Ground', 'A': 'Air', 'F': 'Field fumigation', 'O': 'Other', '': 'Not reported'}
  METHOD_ORDER = ('G', 'A', 'F', 'O', '')


  def by_method(rows, year, lbs_field='lbs_chemical', all_years=False):
      """
      How the scope's use was applied, from CDPR's per-record method
      (aer_gnd_ind): pounds, share of pounds and applications per method, in
      a fixed order. Blank stays as "Not reported" -- mostly the monthly
      summaries of structural and landscape use -- rather than being dropped.
      """
      totals = {
          r['method']: r
          for r in in_year(rows, year, all_years).values('method').annotate(
              lbs=Sum(lbs_field), applications=Sum('applications'))
      }
      total = sum((r['lbs'] or 0) for r in totals.values())
      out = []
      for method in METHOD_ORDER:
          r = totals.get(method)
          if not r or not (r['lbs'] or r['applications']):
              continue
          lbs = r['lbs'] or 0
          out.append({
              'method': method, 'label': METHOD_LABELS[method], 'lbs': lbs,
              'share': lbs / total if total else 0, 'applications': r['applications'] or 0,
          })
      return out
  ```
  `includes/method-breakdown.html` (loads `pesticides_explorer` for `lbs`, `humanize` for `intcomma`): heading "How it was applied" (`h3`/`title is-6` matching the neighbouring section headings), a stacked bar (`<div class="method-bar">` with one `<span class="method-bar-seg is-{{ row.method|default:'none' }}" style="width: {{ row.share|percentage }}" title="{{ row.label }}: …">`), a table (Method / Lbs / Share / Applications; hide the Lbs column when `hide_lbs`), and the verbatim note when a `''` row is present. Use `{% widthratio %}` or an existing percent filter for widths — check `pesticides_explorer` templatetags for one before adding a `percent` filter (add it there with a test if none exists).
- [ ] **Step 4: Run to verify they pass; then the full suite** `HARNESS camp -n 4 --dist loadscope`.
- [ ] **Step 5: Browser pass on :8002** (the 8002 server serves the worktree; migrations must be applied to its DB and the rollup rebuilt for the new column — run `docker exec sjvair-web-run-9fa08fbbbf15 python manage.py migrate pesticides` then `... rebuild_pesticide_rollup --all` (long: ~10 years of PUR; run in the background and wait) — then check: the landing Fumigants trend 2020→2023 no longer drops ~34%; a TELONE II product page shows the badge + tooltip; "Applied by air" across the landing, a chemical page, a county page, the map (map shading changes), records and notices; the breakdown on a chemical, place and section page; the Restricted narrowing's map now differs from Flagged's. Record findings in the report.
- [ ] **Step 6: Leave uncommitted.**

---

## Deploy notes (for the PR description, not code)

`migrate` → `rebuild_pesticide_rollup --all` (full: the rollup grain changed; it also classifies fumigants) → cache flush (LANDING_KEY bumped to v4; other narrowed keys now include the narrow value).
