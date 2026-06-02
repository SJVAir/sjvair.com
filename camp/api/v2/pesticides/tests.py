import pytest
from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from camp.apps.pesticides.models import Chemical, Commodity, PesticideNotice, PesticideUse, Product
from camp.apps.regions.models import Region


def make_county():
    return Region.objects.create(
        name='Fresno County',
        slug='fresno',
        type=Region.Type.COUNTY,
        external_id='06019',
        metadata={'ca_county_code': '10'},
    )


def make_chemical(**kwargs):
    defaults = {'chem_code': 1, 'name': 'SULFUR'}
    defaults.update(kwargs)
    return Chemical.objects.create(**defaults)


def make_commodity(**kwargs):
    defaults = {'site_code': '01', 'name': 'ALMOND'}
    defaults.update(kwargs)
    return Commodity.objects.create(**defaults)


def make_product(**kwargs):
    defaults = {'prodno': 1, 'reg_number': '100-1', 'name': 'SULFUR DUST'}
    defaults.update(kwargs)
    return Product.objects.create(**defaults)


def make_use(county, chemical=None, commodity=None, product=None, **kwargs):
    defaults = {'year': 2023, 'use_no': 1, 'county': county}
    defaults.update(kwargs)
    use = PesticideUse.objects.create(**defaults)
    if chemical:
        use.chemical = chemical
    if commodity:
        use.commodity = commodity
    if product:
        use.product = product
    use.save()
    return use


def make_notice(county, **kwargs):
    defaults = {
        'application_id': 1,
        'comtrs': '1017S16E08',
        'county': county,
        'scheduled_application': timezone.now() + timedelta(days=1),
    }
    defaults.update(kwargs)
    return PesticideNotice.objects.create(**defaults)


# ---------------------------------------------------------------------------
# Chemicals
# ---------------------------------------------------------------------------

class ChemicalListTests(TestCase):
    def setUp(self):
        self.url = reverse('api:v2:pesticides:chemical-list')
        self.chemical = make_chemical(
            chem_code=100,
            name='GLYPHOSATE',
            iarc_group='2A',
            categories=['carcinogen'],
        )

    def test_list_returns_200(self):
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_list_fields(self):
        data = self.client.get(self.url).json()
        assert 'count' in data
        assert 'data' in data
        item = data['data'][0]
        assert set(item.keys()) == {'id', 'chem_code', 'name', 'cas_number', 'dtxsid', 'iarc_group', 'categories'}

    def test_filter_by_name(self):
        make_chemical(chem_code=200, name='COPPER SULFATE')
        data = self.client.get(self.url, {'name': 'glyph'}).json()
        assert data['count'] == 1
        assert data['data'][0]['name'] == 'GLYPHOSATE'

    def test_filter_by_chem_code(self):
        data = self.client.get(self.url, {'chem_code': 100}).json()
        assert data['count'] == 1

    def test_filter_by_iarc_group(self):
        make_chemical(chem_code=201, name='OTHER CHEM', iarc_group='1')
        data = self.client.get(self.url, {'iarc_group': '2A'}).json()
        assert data['count'] == 1
        assert data['data'][0]['iarc_group'] == '2A'

    def test_filter_by_category(self):
        make_chemical(chem_code=202, name='SAFE CHEM', categories=[])
        data = self.client.get(self.url, {'category': 'carcinogen'}).json()
        assert data['count'] == 1


class ChemicalDetailTests(TestCase):
    def setUp(self):
        self.county = make_county()
        self.chemical = make_chemical(chem_code=100, name='GLYPHOSATE')
        self.commodity = make_commodity()
        self.product = make_product()
        self.product.chemicals.through.objects.create(product=self.product, chemical=self.chemical)
        make_use(self.county, chemical=self.chemical, commodity=self.commodity, product=self.product)
        self.url = reverse('api:v2:pesticides:chemical-detail', kwargs={'chemical_id': self.chemical.sqid})

    def test_detail_returns_200(self):
        assert self.client.get(self.url).status_code == 200

    def test_detail_fields(self):
        item = self.client.get(self.url).json()['data']
        assert set(item.keys()) == {
            'id', 'chem_code', 'name', 'cas_number', 'dtxsid', 'iarc_group', 'categories',
            'products', 'commodities',
        }

    def test_detail_includes_products(self):
        item = self.client.get(self.url).json()['data']
        assert len(item['products']) == 1
        assert item['products'][0]['name'] == 'SULFUR DUST'

    def test_detail_includes_commodities(self):
        item = self.client.get(self.url).json()['data']
        assert len(item['commodities']) == 1
        assert item['commodities'][0]['name'] == 'ALMOND'

    def test_no_n_plus_1_queries(self):
        # Add more PesticideUse records linking the same chemical to the same commodity —
        # query count should not grow.
        for i in range(5):
            make_use(self.county, chemical=self.chemical, commodity=self.commodity, use_no=i + 10)
        with self.assertNumQueries(3):
            self.client.get(self.url)


# ---------------------------------------------------------------------------
# Commodities
# ---------------------------------------------------------------------------

class CommodityListTests(TestCase):
    def setUp(self):
        self.url = reverse('api:v2:pesticides:commodity-list')
        self.commodity = make_commodity(site_code='01', name='ALMOND')

    def test_list_returns_200(self):
        assert self.client.get(self.url).status_code == 200

    def test_list_fields(self):
        data = self.client.get(self.url).json()
        assert 'count' in data
        item = data['data'][0]
        assert set(item.keys()) == {'id', 'site_code', 'name'}

    def test_filter_by_name(self):
        make_commodity(site_code='02', name='GRAPE')
        data = self.client.get(self.url, {'name': 'alm'}).json()
        assert data['count'] == 1
        assert data['data'][0]['name'] == 'ALMOND'

    def test_filter_by_site_code(self):
        data = self.client.get(self.url, {'site_code': '01'}).json()
        assert data['count'] == 1


class CommodityDetailTests(TestCase):
    def setUp(self):
        self.county = make_county()
        self.commodity = make_commodity()
        self.chemical = make_chemical()
        self.product = make_product()
        make_use(self.county, chemical=self.chemical, commodity=self.commodity, product=self.product)
        self.url = reverse('api:v2:pesticides:commodity-detail', kwargs={'commodity_id': self.commodity.sqid})

    def test_detail_returns_200(self):
        assert self.client.get(self.url).status_code == 200

    def test_detail_fields(self):
        item = self.client.get(self.url).json()['data']
        assert set(item.keys()) == {'id', 'site_code', 'name', 'chemicals', 'products'}

    def test_detail_includes_chemicals(self):
        item = self.client.get(self.url).json()['data']
        assert len(item['chemicals']) == 1
        assert item['chemicals'][0]['name'] == 'SULFUR'

    def test_detail_includes_products(self):
        item = self.client.get(self.url).json()['data']
        assert len(item['products']) == 1
        assert item['products'][0]['name'] == 'SULFUR DUST'

    def test_no_n_plus_1_queries(self):
        for i in range(5):
            make_use(self.county, chemical=self.chemical, commodity=self.commodity, use_no=i + 10)
        with self.assertNumQueries(3):
            self.client.get(self.url)


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

class ProductListTests(TestCase):
    def setUp(self):
        self.url = reverse('api:v2:pesticides:product-list')
        self.product = make_product(fumigant=True, california_restricted=True)

    def test_list_returns_200(self):
        assert self.client.get(self.url).status_code == 200

    def test_list_fields(self):
        data = self.client.get(self.url).json()
        item = data['data'][0]
        assert set(item.keys()) == {'id', 'prodno', 'reg_number', 'name', 'fumigant', 'california_restricted'}

    def test_filter_by_name(self):
        make_product(prodno=2, reg_number='100-2', name='COPPER SPRAY')
        data = self.client.get(self.url, {'name': 'sulfur'}).json()
        assert data['count'] == 1

    def test_filter_by_fumigant(self):
        make_product(prodno=2, reg_number='100-2', name='OTHER', fumigant=False)
        data = self.client.get(self.url, {'fumigant': 'true'}).json()
        assert data['count'] == 1
        assert data['data'][0]['fumigant'] is True

    def test_filter_by_california_restricted(self):
        make_product(prodno=2, reg_number='100-2', name='OTHER', california_restricted=False)
        data = self.client.get(self.url, {'california_restricted': 'true'}).json()
        assert data['count'] == 1


class ProductDetailTests(TestCase):
    def setUp(self):
        self.county = make_county()
        self.product = make_product()
        self.chemical = make_chemical()
        self.commodity = make_commodity()
        self.product.chemicals.through.objects.create(product=self.product, chemical=self.chemical)
        make_use(self.county, chemical=self.chemical, commodity=self.commodity, product=self.product)
        self.url = reverse('api:v2:pesticides:product-detail', kwargs={'product_id': self.product.sqid})

    def test_detail_returns_200(self):
        assert self.client.get(self.url).status_code == 200

    def test_detail_fields(self):
        item = self.client.get(self.url).json()['data']
        assert set(item.keys()) == {
            'id', 'prodno', 'reg_number', 'name', 'fumigant', 'california_restricted',
            'chemicals', 'commodities',
        }

    def test_detail_includes_chemicals(self):
        item = self.client.get(self.url).json()['data']
        assert len(item['chemicals']) == 1
        assert item['chemicals'][0]['name'] == 'SULFUR'

    def test_detail_includes_commodities(self):
        item = self.client.get(self.url).json()['data']
        assert len(item['commodities']) == 1
        assert item['commodities'][0]['name'] == 'ALMOND'

    def test_no_n_plus_1_queries(self):
        for i in range(5):
            make_use(self.county, chemical=self.chemical, commodity=self.commodity, product=self.product, use_no=i + 10)
        with self.assertNumQueries(3):
            self.client.get(self.url)


# ---------------------------------------------------------------------------
# PesticideUse
# ---------------------------------------------------------------------------

class PesticideUseListTests(TestCase):
    def setUp(self):
        self.url = reverse('api:v2:pesticides:use-list')
        self.county = make_county()
        self.chemical = make_chemical()
        self.commodity = make_commodity()
        self.product = make_product()
        self.use = make_use(
            self.county,
            chemical=self.chemical,
            commodity=self.commodity,
            product=self.product,
            year=2023,
            use_no=1,
            lbs_chemical=500.0,
            acres_treated=10.0,
            application_date=date(2023, 6, 1),
            aerial_ground='G',
        )

    def test_list_returns_200(self):
        assert self.client.get(self.url).status_code == 200

    def test_list_fields(self):
        data = self.client.get(self.url).json()
        item = data['data'][0]
        assert set(item.keys()) == {
            'id', 'year', 'use_no', 'comtrs', 'lbs_chemical', 'acres_treated',
            'application_date', 'aerial_ground', 'county', 'mtrs',
            'product', 'chemical', 'commodity',
        }

    def test_nested_fk_fields(self):
        item = self.client.get(self.url).json()['data'][0]
        assert item['chemical']['name'] == 'SULFUR'
        assert item['commodity']['name'] == 'ALMOND'
        assert item['product']['name'] == 'SULFUR DUST'

    def test_filter_by_year(self):
        make_use(self.county, year=2022, use_no=2)
        data = self.client.get(self.url, {'year': 2023}).json()
        assert data['count'] == 1

    def test_filter_by_county(self):
        other = Region.objects.create(name='Kern', slug='kern', type=Region.Type.COUNTY, external_id='06029')
        make_use(other, year=2023, use_no=3)
        data = self.client.get(self.url, {'county': 'fresno'}).json()
        assert data['count'] == 1

    def test_filter_by_aerial_ground(self):
        make_use(self.county, year=2023, use_no=4, aerial_ground='A')
        data = self.client.get(self.url, {'aerial_ground': 'G'}).json()
        assert data['count'] == 1

    def test_filter_by_commodity(self):
        other = make_commodity(site_code='99', name='GRAPE')
        make_use(self.county, commodity=other, year=2023, use_no=5)
        data = self.client.get(self.url, {'commodity': '01'}).json()
        assert data['count'] == 1
        assert data['data'][0]['commodity']['name'] == 'ALMOND'

    def test_county_in_response(self):
        item = self.client.get(self.url).json()['data'][0]
        assert item['county']['slug'] == 'fresno'

    def test_mtrs_null_when_unset(self):
        item = self.client.get(self.url).json()['data'][0]
        assert item['mtrs'] is None

    def test_no_n_plus_1_queries(self):
        # select_related means query count stays flat as rows grow
        for i in range(4):
            make_use(self.county,
                chemical=self.chemical,
                commodity=self.commodity,
                product=self.product,
                year=2023, use_no=i + 10)
        with self.assertNumQueries(2):
            self.client.get(self.url)


class PesticideUseDetailTests(TestCase):
    def setUp(self):
        self.county = make_county()
        self.use = make_use(self.county, year=2023, use_no=1)
        self.url = reverse('api:v2:pesticides:use-detail', kwargs={'use_id': self.use.sqid})

    def test_detail_returns_200(self):
        assert self.client.get(self.url).status_code == 200

    def test_detail_fields(self):
        item = self.client.get(self.url).json()['data']
        assert set(item.keys()) == {
            'id', 'year', 'use_no', 'comtrs', 'lbs_chemical', 'acres_treated',
            'application_date', 'aerial_ground', 'county', 'mtrs',
            'product', 'chemical', 'commodity',
        }


# ---------------------------------------------------------------------------
# PesticideNotice
# ---------------------------------------------------------------------------

class PesticideNoticeListTests(TestCase):
    def setUp(self):
        self.url = reverse('api:v2:pesticides:notice-list')
        self.county = make_county()
        self.chemical = make_chemical()
        self.product = make_product()
        self.notice = make_notice(self.county, application_id=1)
        self.notice.chemicals.add(self.chemical)
        self.notice.products.add(self.product)

    def test_list_returns_200(self):
        assert self.client.get(self.url).status_code == 200

    def test_list_fields(self):
        item = self.client.get(self.url).json()['data'][0]
        assert set(item.keys()) == {
            'id', 'application_id', 'comtrs', 'county', 'point', 'scheduled_application',
            'treated_amount', 'treated_units', 'application_method',
            'chemicals', 'products',
        }

    def test_nested_m2m_fields(self):
        item = self.client.get(self.url).json()['data'][0]
        assert len(item['chemicals']) == 1
        assert item['chemicals'][0]['name'] == 'SULFUR'
        assert len(item['products']) == 1
        assert item['products'][0]['name'] == 'SULFUR DUST'

    def test_filter_upcoming(self):
        make_notice(self.county, application_id=2,
            scheduled_application=timezone.now() - timedelta(days=1))
        data = self.client.get(self.url, {'upcoming': 'true'}).json()
        assert data['count'] == 1
        assert data['data'][0]['application_id'] == 1

    def test_filter_by_county(self):
        other = Region.objects.create(name='Kern', slug='kern', type=Region.Type.COUNTY, external_id='06029')
        make_notice(other, application_id=2)
        data = self.client.get(self.url, {'county': 'fresno'}).json()
        assert data['count'] == 1

    def test_filter_by_chemical(self):
        other_chem = make_chemical(chem_code=999, name='OTHER')
        other_notice = make_notice(self.county, application_id=2)
        other_notice.chemicals.add(other_chem)
        data = self.client.get(self.url, {'chemical': self.chemical.chem_code}).json()
        assert data['count'] == 1

    def test_no_n_plus_1_queries(self):
        for i in range(4):
            n = make_notice(self.county, application_id=i + 10)
            n.chemicals.add(self.chemical)
            n.products.add(self.product)
        with self.assertNumQueries(4):
            self.client.get(self.url)


# ---------------------------------------------------------------------------
# Region-scoped endpoints
# ---------------------------------------------------------------------------

class PesticideRegionSummaryTests(TestCase):
    def setUp(self):
        self.county = make_county()
        self.chemical = make_chemical(chem_code=100, name='GLYPHOSATE', iarc_group='2A', categories=['carcinogen'])
        self.commodity = make_commodity(site_code='01', name='ALMOND')
        self.product = make_product()
        make_use(
            self.county,
            chemical=self.chemical,
            commodity=self.commodity,
            product=self.product,
            year=2023,
            use_no=1,
            lbs_chemical=500.0,
            acres_treated=10.0,
        )
        self.url = reverse('api:v2:pesticides:region-summary', kwargs={'region_id': self.county.sqid})

    def test_returns_200(self):
        assert self.client.get(self.url).status_code == 200

    def test_404_for_unknown_region(self):
        url = reverse('api:v2:pesticides:region-summary', kwargs={'region_id': 'BOGUS'})
        assert self.client.get(url).status_code == 404

    def test_response_shape(self):
        data = self.client.get(self.url).json()
        assert set(data.keys()) == {'region', 'data', 'count'}
        assert data['count'] == 1
        assert set(data['region'].keys()) == {'id', 'name', 'slug', 'type'}
        item = data['data'][0]
        assert set(item.keys()) == {'year', 'chemical', 'commodity', 'total_lbs', 'total_acres', 'application_count'}

    def test_nested_objects(self):
        item = self.client.get(self.url).json()['data'][0]
        assert item['chemical']['name'] == 'GLYPHOSATE'
        assert item['commodity']['name'] == 'ALMOND'

    def test_aggregates_correctly(self):
        make_use(self.county, chemical=self.chemical, commodity=self.commodity,
                 year=2023, use_no=2, lbs_chemical=300.0, acres_treated=5.0)
        item = self.client.get(self.url).json()['data'][0]
        assert item['total_lbs'] == 800.0
        assert item['total_acres'] == 15.0
        assert item['application_count'] == 2

    def test_filter_by_year(self):
        make_use(self.county, chemical=self.chemical, commodity=self.commodity,
                 year=2022, use_no=10, lbs_chemical=100.0)
        data = self.client.get(self.url, {'year': 2023}).json()
        assert data['count'] == 1
        assert data['data'][0]['year'] == 2023

    def test_filter_by_chemical(self):
        other_chem = make_chemical(chem_code=999, name='OTHER')
        make_use(self.county, chemical=other_chem, commodity=self.commodity,
                 year=2023, use_no=10)
        data = self.client.get(self.url, {'chemical': self.chemical.chem_code}).json()
        assert data['count'] == 1

    def test_filter_by_category(self):
        safe_chem = make_chemical(chem_code=999, name='SAFE', categories=[])
        make_use(self.county, chemical=safe_chem, commodity=self.commodity,
                 year=2023, use_no=10)
        data = self.client.get(self.url, {'category': 'carcinogen'}).json()
        assert data['count'] == 1
        assert data['data'][0]['chemical']['name'] == 'GLYPHOSATE'

    def test_non_county_region_without_boundary_returns_empty(self):
        city = Region.objects.create(
            name='Fresno',
            slug='fresno-city',
            type=Region.Type.CITY,
            external_id='2027000',
        )
        url = reverse('api:v2:pesticides:region-summary', kwargs={'region_id': city.sqid})
        data = self.client.get(url).json()
        assert data['count'] == 0
        assert data['data'] == []


class PesticideRegionNoticeTests(TestCase):
    def setUp(self):
        self.county = make_county()
        self.chemical = make_chemical()
        self.notice = make_notice(self.county, application_id=1)
        self.notice.chemicals.add(self.chemical)
        self.url = reverse('api:v2:pesticides:region-notice', kwargs={'region_id': self.county.sqid})

    def test_returns_200(self):
        assert self.client.get(self.url).status_code == 200

    def test_404_for_unknown_region(self):
        url = reverse('api:v2:pesticides:region-notice', kwargs={'region_id': 'BOGUS'})
        assert self.client.get(url).status_code == 404

    def test_scoped_to_region(self):
        other = Region.objects.create(name='Kern', slug='kern', type=Region.Type.COUNTY, external_id='06029')
        make_notice(other, application_id=2)
        data = self.client.get(self.url).json()
        assert data['count'] == 1
        assert data['data'][0]['application_id'] == 1

    def test_non_county_region_without_boundary_returns_empty(self):
        city = Region.objects.create(name='Fresno', slug='fresno-city', type=Region.Type.CITY, external_id='2027000')
        url = reverse('api:v2:pesticides:region-notice', kwargs={'region_id': city.sqid})
        assert self.client.get(url).json()['count'] == 0

    def test_filter_upcoming(self):
        make_notice(self.county, application_id=3,
            scheduled_application=timezone.now() - timedelta(days=1))
        data = self.client.get(self.url, {'upcoming': 'true'}).json()
        assert data['count'] == 1
        assert data['data'][0]['application_id'] == 1

    def test_filter_by_chemical(self):
        other_chem = make_chemical(chem_code=999, name='OTHER')
        other_notice = make_notice(self.county, application_id=4)
        other_notice.chemicals.add(other_chem)
        data = self.client.get(self.url, {'chemical': self.chemical.chem_code}).json()
        assert data['count'] == 1


class PesticideRegionUseTests(TestCase):
    def setUp(self):
        self.county = make_county()
        self.chemical = make_chemical()
        self.commodity = make_commodity()
        self.use = make_use(self.county, chemical=self.chemical, commodity=self.commodity,
                            year=2023, use_no=1, lbs_chemical=100.0)
        self.url = reverse('api:v2:pesticides:region-use', kwargs={'region_id': self.county.sqid})

    def test_returns_200(self):
        assert self.client.get(self.url).status_code == 200

    def test_404_for_unknown_region(self):
        url = reverse('api:v2:pesticides:region-use', kwargs={'region_id': 'BOGUS'})
        assert self.client.get(url).status_code == 404

    def test_scoped_to_region(self):
        other = Region.objects.create(name='Kern', slug='kern', type=Region.Type.COUNTY, external_id='06029')
        make_use(other, year=2023, use_no=2)
        data = self.client.get(self.url).json()
        assert data['count'] == 1
        assert data['data'][0]['use_no'] == 1

    def test_non_county_region_without_boundary_returns_empty(self):
        city = Region.objects.create(name='Fresno', slug='fresno-city', type=Region.Type.CITY, external_id='2027000')
        url = reverse('api:v2:pesticides:region-use', kwargs={'region_id': city.sqid})
        assert self.client.get(url).json()['count'] == 0

    def test_filter_by_year(self):
        make_use(self.county, year=2022, use_no=10)
        data = self.client.get(self.url, {'year': 2023}).json()
        assert data['count'] == 1

    def test_filter_by_chemical(self):
        other_chem = make_chemical(chem_code=999, name='OTHER')
        make_use(self.county, chemical=other_chem, year=2023, use_no=10)
        data = self.client.get(self.url, {'chemical': self.chemical.chem_code}).json()
        assert data['count'] == 1


class PesticideNoticeDetailTests(TestCase):
    def setUp(self):
        self.county = make_county()
        self.notice = make_notice(self.county)
        self.url = reverse('api:v2:pesticides:notice-detail', kwargs={'notice_id': self.notice.sqid})

    def test_detail_returns_200(self):
        assert self.client.get(self.url).status_code == 200

    def test_detail_fields(self):
        item = self.client.get(self.url).json()['data']
        assert set(item.keys()) == {
            'id', 'application_id', 'comtrs', 'county', 'point', 'scheduled_application',
            'treated_amount', 'treated_units', 'application_method',
            'chemicals', 'products',
        }
