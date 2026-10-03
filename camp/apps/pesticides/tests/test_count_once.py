from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.pesticides import places, rollup, stats
from camp.apps.pesticides.models import (
    Chemical, Commodity, FumigationMethod, PesticideUse, PesticideUseRollup, Product,
)
from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin
from camp.apps.regions.models import Region

BBOX = '-119.9,36.6,-119.7,36.8'


class CountEachRecordOnceTests(RollupTestMixin, TestCase):
    """
    One use record with two active ingredients is two PesticideUse rows. Every
    surface that sums across chemicals counts it once; a chemical's own page
    counts it (with that chemical's pounds) for each ingredient.

    On top of the fixture's 2023 section 9101 (4 applications, 970 lbs of
    product), so a surface that counts rows reads one more than it should.
    """

    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.product = Product.objects.create(prodno=95001, reg_number='95001-1', name='MULTI PRODUCT')
        self.commodity = Commodity.objects.create(site_code='95001', name='MULTI CROP')
        # C1 sorts first, so it holds the designated row; C2 is the one that
        # must not lose its count.
        self.c1 = Chemical.objects.create(chem_code=8001, name='FIRST CHEM')
        self.c2 = Chemical.objects.create(chem_code=8002, name='SECOND CHEM')
        for chemical, lbs in ((self.c2, 20), (self.c1, 30)):
            PesticideUse.objects.create(
                year=2023, use_no=900, county_id=9001, mtrs_id=9101, product=self.product,
                chemical=chemical, commodity=self.commodity, lbs_chemical=lbs, lbs_product=100,
                acres_treated=10, application_date='2023-07-05', aerial_ground='G',
            )
        rollup.rebuild_year(2023)
        cache.clear()

    def test_product_page_counts_the_record_once(self):
        context = self.client.get(self.product.get_absolute_url(), {'year': 2023}).context
        assert context['totals']['applications'] == 1
        assert context['totals']['lbs'] == 100
        assert [(r['year'], r['applications'], r['lbs']) for r in context['by_year']] == [(2023, 1, 100)]
        assert [(c['county_name'], c['applications']) for c in context['by_county']] == [('Fresno County', 1)]
        assert [(m['label'], m['applications']) for m in context['by_method']] == [('Ground', 1)]
        assert context['by_month'][6]['applications'] == 1

    def test_commodity_page_counts_the_record_once(self):
        context = self.client.get(self.commodity.get_absolute_url(), {'year': 2023}).context
        assert context['totals']['applications'] == 1
        assert context['related_b']['rows'][0].lbs == 100

    def test_each_chemical_page_keeps_its_own_application_and_pounds(self):
        for chemical, lbs in ((self.c1, 30), (self.c2, 20)):
            context = self.client.get(chemical.get_absolute_url(), {'year': 2023}).context
            assert context['totals']['applications'] == 1
            assert context['totals']['lbs'] == lbs
            assert [(c['applications'], c['lbs']) for c in context['by_county']] == [(1, lbs)]
            assert context['by_month'][6]['applications'] == 1

    def test_product_list_counts_pounds_once_but_a_chemical_filter_keeps_them_per_row(self):
        def listed(**params):
            response = self.client.get(reverse('pesticides:product-list'), {'year': 2023, **params})
            return {obj.pk: obj.lbs_applied for obj in response.context['object_list']}

        assert listed()[self.product.pk] == 100
        # The pair's own pounds, whichever ingredient holds the designated row.
        assert listed(chemical=self.c1.sqid)[self.product.pk] == 100
        assert listed(chemical=self.c2.sqid)[self.product.pk] == 100

    def test_place_section_and_landing_count_the_record_once(self):
        fresno = Region.objects.get(pk=9001)
        place = places.place_context(places.region_area(fresno), 2023)
        assert place['totals']['applications'] == 5
        assert next(r.lbs for r in place['top_products'] if r.obj == self.product) == 100
        assert place['by_month'][6]['lbs'] == 50
        assert [m['applications'] for m in place['by_method']] == [5]

        section = Region.objects.get(pk=9101)
        url = reverse('pesticides:section-detail', kwargs={'sqid': section.sqid})
        context = self.client.get(url, {'year': 2023}).context
        assert context['totals']['applications'] == 5
        assert next(r.lbs for r in context['top_products'] if r.obj == self.product) == 100

        landing = stats.landing_stats(2023)
        assert landing['applications'] == 7
        assert next(r.lbs for r in landing['top_products'] if r.obj == self.product) == 100
        all_years = stats.landing_stats(all_years=True)
        assert all_years['applications'] == 10

    def test_county_table_counts_the_record_once(self):
        fresno = next(r for r in stats.county_totals(2023) if r['county_id'] == 9001)
        assert fresno['applications'] == 5

    def test_school_block_counts_the_record_once(self):
        totals = stats.block_totals(PesticideUseRollup.objects.all(), Region.objects.get(pk=9101).boundary.geometry.centroid, 2023)
        assert totals['applications'] == 5

    def test_sections_api_counts_the_record_once(self):
        url = reverse('api:v2:pesticides:section-list')

        def props(**params):
            body = self.client.get(url, {'bbox': BBOX, 'year': 2023, **params}).json()
            return {f['properties']['mtrs']: f['properties'] for f in body['features']}['MDM-T14S-R20E-01']

        totals = props()
        assert totals['applications'] == 5
        assert totals['lbs_product'] == 1070
        # The rollup path (a month filter) agrees with the totals table.
        rolled = props(month=7)
        assert (rolled['applications'], rolled['lbs_product']) == (1, 100)
        # One chemical: per-row measures, so the non-designated one is still 1.
        for chemical in (self.c1, self.c2):
            scoped = props(chemical=chemical.chem_code)
            assert (scoped['applications'], scoped['lbs_product']) == (1, 100)

    def test_section_detail_api_counts_the_record_once(self):
        section = Region.objects.get(pk=9101)
        url = reverse('api:v2:pesticides:section-detail', kwargs={'section_id': section.sqid})
        body = self.client.get(url, {'year': 2023}).json()
        assert next(y for y in body['years'] if y['year'] == 2023)['applications'] == 5
        assert body['months'][6]['applications'] == 1
        assert next(p['lbs'] for p in body['top_products'] if p['name'] == 'MULTI PRODUCT') == 100

    def test_townships_api_counts_the_record_once(self):
        url = reverse('api:v2:pesticides:township-list')

        def props(**params):
            body = self.client.get(url, {'year': 2023, **params}).json()
            return {f['properties']['id']: f['properties'] for f in body['features']}['MDM-T14S-R20E']

        assert props()['applications'] == 5
        for chemical in (self.c1, self.c2):
            assert props(chemical=chemical.chem_code)['applications'] == 1

    def test_records_browser_displays_records_but_pages_rows(self):
        response = self.client.get(reverse('pesticides:records'), {'year': 2023, 'product': self.product.sqid})
        assert response.context['totals']['records'] == 1
        assert response.context['totals']['applications'] == 2
        assert response.context['paginator'].count == 2
        assert len(response.context['object_list']) == 2
        assert response.context['summary_sentence'].startswith('1 applications')

    def test_records_browser_chemical_filter_shows_the_chemical_rows(self):
        response = self.client.get(reverse('pesticides:records'), {'year': 2023, 'chemical': self.c2.sqid})
        assert response.context['totals']['records'] == 1
        assert response.context['totals']['applications'] == 1


    def test_acres_are_counted_once_per_record(self):
        # Both ingredient rows carry acres_treated=10.
        context = self.client.get(self.product.get_absolute_url(), {'year': 2023}).context
        assert context['totals']['acres'] == 10
        assert context['totals']['lbs_per_acre'] == 10
        assert context['by_county'][0]['acres'] == 10
        assert context['by_month'][6]['acres'] == 10
        assert context['by_year'][0]['acres'] == 10

        place = places.place_context(places.region_area(Region.objects.get(pk=9001)), 2023)
        assert place['totals']['acres'] == 77

        section = Region.objects.get(pk=9101)
        url = reverse('pesticides:section-detail', kwargs={'sqid': section.sqid})
        assert self.client.get(url, {'year': 2023}).context['totals']['acres'] == 77

        assert stats.landing_stats(2023)['acres'] == 84
        fresno = next(r for r in stats.county_totals(2023) if r['county_id'] == 9001)
        assert fresno['acres'] == 77

    def test_acres_in_the_apis_and_records_browser(self):
        body = self.client.get(reverse('api:v2:pesticides:section-list'), {'bbox': BBOX, 'year': 2023}).json()
        props = {f['properties']['mtrs']: f['properties'] for f in body['features']}['MDM-T14S-R20E-01']
        assert props['acres_treated'] == 77
        scoped = self.client.get(reverse('api:v2:pesticides:section-list'),
            {'bbox': BBOX, 'year': 2023, 'chemical': self.c2.chem_code}).json()
        assert scoped['features'][0]['properties']['acres_treated'] == 10
        body = self.client.get(reverse('api:v2:pesticides:township-list'), {'year': 2023}).json()
        townships = {f['properties']['id']: f['properties'] for f in body['features']}
        assert townships['MDM-T14S-R20E']['acres_treated'] == 77

        records = reverse('pesticides:records')
        assert self.client.get(records, {'year': 2023, 'product': self.product.sqid}).context['totals']['acres'] == 10
        assert self.client.get(records, {'year': 2023, 'chemical': self.c2.sqid}).context['totals']['acres'] == 10

    def test_chemical_pages_keep_per_row_acres(self):
        for chemical in (self.c1, self.c2):
            context = self.client.get(chemical.get_absolute_url(), {'year': 2023}).context
            assert context['totals']['acres'] == 10


class FumigationCountOnceTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        method = FumigationMethod.objects.create(code=1107, name='Tarpaulin [6447]')
        self.product = Product.objects.create(prodno=95002, reg_number='95002-1', name='FUME PRODUCT', is_fumigant=True)
        for code, lbs in ((8101, 30), (8102, 20)):
            PesticideUse.objects.create(
                year=2023, use_no=901, county_id=9001, mtrs_id=9101, product=self.product,
                chemical=Chemical.objects.create(chem_code=code, name=f'FUME CHEM {code}'),
                lbs_chemical=lbs, lbs_product=100, application_date='2023-07-05',
                aerial_ground='F', fume_method=method,
            )
        rollup.rebuild_year(2023)
        cache.clear()

    def test_product_page_counts_the_fumigation_once(self):
        context = self.client.get(self.product.get_absolute_url(), {'year': 2023}).context
        (row,) = context['by_fume_method']
        assert (row['applications'], row['lbs']) == (1, 100)

    def test_a_chemical_page_counts_its_own_row(self):
        chemical = Chemical.objects.get(chem_code=8102)
        chemical.categories = [Chemical.Category.FUMIGANT]
        chemical.save()
        context = self.client.get(chemical.get_absolute_url(), {'year': 2023}).context
        (row,) = context['by_fume_method']
        assert (row['applications'], row['lbs']) == (1, 20)


class NarrowedCountOnceTests(RollupTestMixin, TestCase):
    """
    A chemical-based narrowing keeps a record through its flagged ingredient,
    even when an unflagged ingredient has the lower chemical_id: the rollup
    designates restricted, then of-concern, ingredients first.
    """

    fixtures = ['pesticides-explorer']
    CASES = (
        (Chemical.Category.TOXIC_AIR_CONTAMINANT, 'concern'),
        (Chemical.Category.CALIFORNIA_RESTRICTED, 'restricted'),
        (Chemical.Category.CALIFORNIA_RESTRICTED, 'concern'),
    )

    def setUp(self):
        cache.clear()
        self.section = Region.objects.get(pk=9101)
        self.area = places.region_area(Region.objects.get(pk=9001))

    def baselines(self, narrow):
        cache.clear()
        section_url = reverse('pesticides:section-detail', kwargs={'sqid': self.section.sqid})
        return (
            places.place_context(self.area, 2023, concern=narrow)['totals']['applications'],
            self.client.get(section_url, {'year': 2023, 'narrow': narrow}).context['totals']['applications'],
        )

    def add_record(self, category, prodno):
        product = Product.objects.create(prodno=prodno, reg_number=f'{prodno}-1', name=f'NARROW PRODUCT {prodno}')
        low = Chemical.objects.create(chem_code=prodno, name=f'PLAIN {prodno}')
        flagged = Chemical.objects.create(chem_code=prodno + 1, name=f'FLAGGED {prodno}', categories=[category])
        assert low.pk < flagged.pk
        for chemical, lbs in ((flagged, 20), (low, 30)):
            PesticideUse.objects.create(
                year=2023, use_no=prodno, county_id=9001, mtrs_id=9101, product=product,
                chemical=chemical, lbs_chemical=lbs, lbs_product=100, acres_treated=10,
                application_date='2023-07-05', aerial_ground='G',
            )
        rollup.rebuild_year(2023)
        cache.clear()
        return product, low, flagged

    def test_a_narrowed_page_counts_the_record_once(self):
        for i, (category, narrow) in enumerate(self.CASES):
            before_place, before_section = self.baselines(narrow)
            product, low, flagged = self.add_record(category, 96000 + i * 10)

            context = self.client.get(product.get_absolute_url(), {'year': 2023, 'narrow': narrow}).context
            assert context['totals']['applications'] == 1, (category, narrow)
            assert context['totals']['lbs'] == 100, (category, narrow)

            place = places.place_context(self.area, 2023, concern=narrow)
            assert place['totals']['applications'] == before_place + 1, (category, narrow)
            assert next(r.lbs for r in place['top_products'] if r.obj == product) == 100

            section_url = reverse('pesticides:section-detail', kwargs={'sqid': self.section.sqid})
            section = self.client.get(section_url, {'year': 2023, 'narrow': narrow}).context
            assert section['totals']['applications'] == before_section + 1, (category, narrow)

    def test_unnarrowed_and_chemical_pages_are_unchanged(self):
        product, low, flagged = self.add_record(Chemical.Category.TOXIC_AIR_CONTAMINANT, 96100)
        context = self.client.get(product.get_absolute_url(), {'year': 2023}).context
        assert (context['totals']['applications'], context['totals']['lbs']) == (1, 100)
        for chemical, lbs in ((low, 30), (flagged, 20)):
            context = self.client.get(chemical.get_absolute_url(), {'year': 2023}).context
            assert (context['totals']['applications'], context['totals']['lbs']) == (1, lbs)
