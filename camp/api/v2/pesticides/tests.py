import pytest
from datetime import date, timedelta

from django.contrib.gis.geos import GEOSGeometry
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from camp.apps.pesticides.models import Chemical, Commodity, PesticideNotice, PesticideUse, Product
from camp.apps.regions.models import Boundary, Region


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
        assert set(item.keys()) == {
            'id', 'chem_code', 'name', 'preferred_name', 'display_name', 'cas_number', 'dtxsid', 'iarc_group', 'categories',
        }
        assert item['display_name'] == item['name'].capitalize()

    def test_display_name_prefers_the_comptox_name(self):
        make_chemical(chem_code=633, name='1080', preferred_name='Sodium fluoroacetate')
        rows = {c['chem_code']: c for c in self.client.get(self.url).json()['data']}
        assert rows[633]['name'] == '1080'
        assert rows[633]['display_name'] == 'Sodium fluoroacetate'

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
            'id', 'chem_code', 'name', 'preferred_name', 'display_name', 'cas_number', 'dtxsid', 'iarc_group', 'categories',
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


# ---------------------------------------------------------------------------
# region_id filter — PesticideUse
# ---------------------------------------------------------------------------

def make_mtrs_region(geometry_wkt, slug='test-mtrs', external_id='9001'):
    region = Region.objects.create(
        name='Test MTRS', slug=slug, type=Region.Type.MTRS, external_id=external_id,
    )
    boundary = Boundary.objects.create(
        region=region, version='2020',
        geometry=GEOSGeometry(geometry_wkt, srid=4326),
    )
    region.boundary = boundary
    region.save()
    return region


def make_city_region(geometry_wkt, slug='test-city', external_id='9002'):
    region = Region.objects.create(
        name='Test City', slug=slug, type=Region.Type.CITY, external_id=external_id,
    )
    boundary = Boundary.objects.create(
        region=region, version='2020',
        geometry=GEOSGeometry(geometry_wkt, srid=4326),
    )
    region.boundary = boundary
    region.save()
    return region


class PesticideUseRegionFilterTests(TestCase):
    def setUp(self):
        self.url = reverse('api:v2:pesticides:use-list')
        self.county = make_county()
        self.use = make_use(self.county, year=2023, use_no=1)

    def test_county_region_filters_by_county_fk(self):
        other_county = Region.objects.create(
            name='Kern', slug='kern', type=Region.Type.COUNTY, external_id='06029',
        )
        make_use(other_county, year=2023, use_no=2)
        data = self.client.get(self.url, {'region_id': self.county.sqid}).json()
        assert data['count'] == 1

    def test_spatial_region_filters_by_mtrs_intersection(self):
        mtrs_geom = 'MULTIPOLYGON (((-119.9 36.6, -119.8 36.6, -119.8 36.7, -119.9 36.7, -119.9 36.6)))'
        city_geom = 'MULTIPOLYGON (((-120.0 36.5, -119.7 36.5, -119.7 36.8, -120.0 36.8, -120.0 36.5)))'
        mtrs = make_mtrs_region(mtrs_geom)
        city = make_city_region(city_geom)
        use_in_region = make_use(self.county, year=2023, use_no=2, mtrs=mtrs)
        data = self.client.get(self.url, {'region_id': city.sqid}).json()
        assert data['count'] == 1
        assert data['data'][0]['id'] == str(use_in_region.sqid)

    def test_region_without_boundary_returns_empty(self):
        city = Region.objects.create(
            name='No Boundary City', slug='no-boundary', type=Region.Type.CITY, external_id='9099',
        )
        data = self.client.get(self.url, {'region_id': city.sqid}).json()
        assert data['count'] == 0

    def test_invalid_region_id_returns_empty(self):
        data = self.client.get(self.url, {'region_id': 'BOGUS'}).json()
        assert data['count'] == 0


# ---------------------------------------------------------------------------
# region_id filter — PesticideNotice
# ---------------------------------------------------------------------------

class PesticideNoticeRegionFilterTests(TestCase):
    def setUp(self):
        self.url = reverse('api:v2:pesticides:notice-list')
        self.county = make_county()
        self.notice = make_notice(self.county, application_id=1)

    def test_county_region_filters_by_county_fk(self):
        other_county = Region.objects.create(
            name='Kern', slug='kern', type=Region.Type.COUNTY, external_id='06029',
        )
        make_notice(other_county, application_id=2)
        data = self.client.get(self.url, {'region_id': self.county.sqid}).json()
        assert data['count'] == 1

    def test_spatial_region_filters_by_mtrs_intersection(self):
        mtrs_geom = 'MULTIPOLYGON (((-119.9 36.6, -119.8 36.6, -119.8 36.7, -119.9 36.7, -119.9 36.6)))'
        city_geom = 'MULTIPOLYGON (((-120.0 36.5, -119.7 36.5, -119.7 36.8, -120.0 36.8, -120.0 36.5)))'
        mtrs = make_mtrs_region(mtrs_geom)
        city = make_city_region(city_geom)
        notice_in_region = make_notice(self.county, application_id=2, mtrs=mtrs)
        data = self.client.get(self.url, {'region_id': city.sqid}).json()
        assert data['count'] == 1
        assert data['data'][0]['id'] == str(notice_in_region.sqid)

    def test_region_without_boundary_returns_empty(self):
        city = Region.objects.create(
            name='No Boundary City', slug='no-boundary', type=Region.Type.CITY, external_id='9099',
        )
        data = self.client.get(self.url, {'region_id': city.sqid}).json()
        assert data['count'] == 0

    def test_invalid_region_id_returns_empty(self):
        data = self.client.get(self.url, {'region_id': 'BOGUS'}).json()
        assert data['count'] == 0


# ---------------------------------------------------------------------------
# Section endpoints (bbox/radius GeoJSON list + detail), backed by the fixture
# rollup
# ---------------------------------------------------------------------------

from camp.apps.pesticides import rollup
from camp.apps.pesticides.models import PesticideUseRollup


class SectionEndpointTests(TestCase):
    fixtures = ['pesticides-explorer']

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        rollup.rebuild_all()

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.url = reverse('api:v2:pesticides:section-list')

    def test_bbox_returns_geojson_with_totals(self):
        response = self.client.get(self.url, {'bbox': '-119.9,36.6,-119.7,36.8', 'year': 2023})
        assert response.status_code == 200
        data = response.json()
        assert data['type'] == 'FeatureCollection'
        assert len(data['features']) == 1
        feature = data['features'][0]
        assert feature['id'] == Region.objects.get(pk=9101).sqid
        assert feature['geometry']['type'] == 'MultiPolygon'
        assert feature['properties']['mtrs'] == 'MDM-T14S-R20E-01'
        assert feature['properties']['county'] == 'Fresno County'
        # 2023 in section 9101: uses 1, 2, 4, 6 = 100 + 50 + 20 + 500 lbs, 4 applications
        assert feature['properties']['lbs_chemical'] == 670.0
        assert feature['properties']['applications'] == 4

    def test_bbox_includes_empty_sections_with_zeros(self):
        response = self.client.get(self.url, {'bbox': '-119.9,36.6,-119.7,36.8', 'year': 2022, 'chemical': 253})
        feature = response.json()['features'][0]
        assert feature['properties']['lbs_chemical'] == 0
        assert feature['properties']['applications'] == 0

    def test_filters(self):
        response = self.client.get(self.url, {'bbox': '-119.9,36.6,-119.7,36.8', 'year': 2023, 'chemical': 1855})
        assert response.json()['features'][0]['properties']['lbs_chemical'] == 150.0
        response = self.client.get(self.url, {'bbox': '-119.9,36.6,-119.7,36.8', 'year': 2023, 'month': 8})
        assert response.json()['features'][0]['properties']['lbs_chemical'] == 500.0
        response = self.client.get(self.url, {'bbox': '-119.9,36.6,-119.7,36.8', 'year': 2023, 'commodity': '3001'})
        assert response.json()['features'][0]['properties']['lbs_chemical'] == 120.0

    def test_radius(self):
        response = self.client.get(self.url, {'lat': 35.36, 'lng': -119.04, 'radius': 1, 'year': 2023})
        data = response.json()
        assert [f['properties']['mtrs'] for f in data['features']] == ['MDM-T30S-R28E-01']
        assert data['features'][0]['properties']['lbs_chemical'] == 70.0

    def test_radius_must_be_allowed_value(self):
        assert self.client.get(self.url, {'lat': 35.36, 'lng': -119.04, 'radius': 2}).status_code == 400

    def test_lat_lng_nan_is_bad_request_not_500(self):
        response = self.client.get(self.url, {'lat': 'nan', 'lng': 'nan', 'radius': 1})
        assert response.status_code == 400

    def test_lat_lng_out_of_range_is_bad_request(self):
        response = self.client.get(self.url, {'lat': 95, 'lng': -119, 'radius': 1})
        assert response.status_code == 400

    def test_radius_bbox_prefilter_keeps_exact_distance(self):
        # Section 9102's square spans lng -119.05..-119.03, lat 35.35..35.37,
        # so its southwest corner is (-119.05, 35.35). Point (35.339,
        # -119.0635) sits diagonally off that corner:
        #   - 0.011 deg south of the corner's latitude -> 0.011 * 69 ~= 0.76 mi
        #   - 0.0135 deg west of the corner's longitude, at ~35.345 deg lat,
        #     where a degree of longitude is ~69.17 * cos(35.345 deg) ~= 56.3
        #     mi -> 0.0135 * 56.3 ~= 0.76 mi
        #   - straight-line distance to the corner: sqrt(0.76^2 + 0.76^2)
        #     ~= 1.07 mi -- outside a 1-mile radius, inside a 3-mile radius.
        # radius_bbox(35.339, -119.0635, 1) has lat_deg = 1/69 ~= 0.0145 and
        # lng_deg = 1/(69 * cos(35.339 deg)) ~= 0.0178, so the box spans
        # lat 35.339 +/- 0.0145 (north edge 35.3535 > 35.35) and
        # lng -119.0635 +/- 0.0178 (east edge -119.0457 > -119.05): the box
        # overlaps section 9102's bbox at radius 1 even though the point is
        # actually ~1.07 mi away. So a bbox-only implementation would wrongly
        # include this section at radius 1; only the exact ST_Distance filter
        # correctly excludes it. The second assertion below proves the bbox
        # alone really would have matched, so the first assertion is only
        # passing because of the distance filter, not despite it being a
        # no-op.
        from camp.api.v2.pesticides import sections

        bbox_only = Region.objects.filter(
            type=Region.Type.MTRS,
            boundary__geometry__bboverlaps=sections.radius_bbox(35.339, -119.0635, 1),
        )
        assert Region.objects.get(pk=9102) in bbox_only

        response = self.client.get(self.url, {'lat': 35.339, 'lng': -119.0635, 'radius': 1, 'year': 2023})
        assert response.json()['features'] == []
        response = self.client.get(self.url, {'lat': 35.339, 'lng': -119.0635, 'radius': 3, 'year': 2023})
        assert [f['properties']['mtrs'] for f in response.json()['features']] == ['MDM-T30S-R28E-01']

    def test_requires_bbox_or_point(self):
        assert self.client.get(self.url, {'year': 2023}).status_code == 400

    def test_bbox_cap(self):
        from camp.api.v2.pesticides import sections
        old = sections.MAX_SECTIONS
        sections.MAX_SECTIONS = 1
        try:
            response = self.client.get(self.url, {'bbox': '-120,35,-118,37', 'year': 2023})
        finally:
            sections.MAX_SECTIONS = old
        assert response.status_code == 400
        assert 'zoom' in response.json()['error']

    def test_default_year_is_latest(self):
        response = self.client.get(self.url, {'bbox': '-119.9,36.6,-119.7,36.8'})
        assert response.json()['year'] == 2023

    def test_all_years_sums_every_loaded_year(self):
        # Section 9101 has 670 lbs / 4 applications in 2023 and 480 / 2 in 2022.
        response = self.client.get(self.url, {'bbox': '-119.9,36.6,-119.7,36.8', 'year': 'all'})
        data = response.json()
        assert data['year'] == 'all'
        props = next(f['properties'] for f in data['features'] if f['properties']['mtrs'] == 'MDM-T14S-R20E-01')
        assert (props['lbs_chemical'], props['applications']) == (1150.0, 6)
        assert props['county'] == 'Fresno County'

    def test_cached(self):
        self.client.get(self.url, {'bbox': '-119.9,36.6,-119.7,36.8', 'year': 2023})
        PesticideUseRollup.objects.all().delete()
        response = self.client.get(self.url, {'bbox': '-119.9,36.6,-119.7,36.8', 'year': 2023})
        assert response.json()['features'][0]['properties']['applications'] == 4

    def test_detail(self):
        section = Region.objects.get(pk=9101)
        response = self.client.get(reverse('api:v2:pesticides:section-detail', kwargs={'section_id': section.sqid}))
        assert response.status_code == 200
        data = response.json()
        assert data['mtrs'] == 'MDM-T14S-R20E-01'
        assert data['geometry']['type'] == 'MultiPolygon'
        assert [(y['year'], y['lbs_chemical'], y['applications']) for y in data['years']] == [(2023, 670.0, 4), (2022, 480.0, 2)]
        assert len(data['months']) == 12 and data['months'][7]['lbs_chemical'] == 500.0
        assert [c['name'] for c in data['top_chemicals']] == ['SULFUR', 'GLYPHOSATE', 'CHLORPYRIFOS']
        assert data['top_commodities'][0]['name'] == 'GRAPE'

    def test_detail_404(self):
        assert self.client.get(reverse('api:v2:pesticides:section-detail', kwargs={'section_id': 'nope'})).status_code == 404


# ---------------------------------------------------------------------------
# Active notices GeoJSON endpoint
# ---------------------------------------------------------------------------

class ActiveNoticeEndpointTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.url = reverse('api:v2:pesticides:notice-active')

    def test_returns_active_notices_as_geojson(self):
        from camp.apps.pesticides.models import PesticideNotice
        from django.contrib.gis.geos import Point
        PesticideNotice.objects.filter(pk=2).update(point=Point(-119.79, 36.71, srid=4326))
        data = self.client.get(self.url).json()
        assert data['type'] == 'FeatureCollection'
        ids = {f['properties']['id'] for f in data['features']}
        assert ids == {PesticideNotice.objects.get(pk=2).sqid, PesticideNotice.objects.get(pk=3).sqid}
        two = next(f for f in data['features'] if f['properties']['id'] == PesticideNotice.objects.get(pk=2).sqid)
        assert two['geometry'] == {'type': 'Point', 'coordinates': [-119.79, 36.71]}
        assert two['properties']['county'] == 'Fresno County'
        assert two['properties']['scheduled_end'] > two['properties']['scheduled_application']
        assert [c['name'] for c in two['properties']['chemicals']] == ['CHLORPYRIFOS']
        assert two['properties']['chemicals'][0]['is_of_concern'] is True
        assert [p['name'] for p in two['properties']['products']] == ['LORSBAN 4E']
        # No MTRS on the fixture notices, so no section to link.
        assert two['properties']['section'] is None
        assert two['properties']['section_id'] is None

    def test_section_id_is_the_mtrs_sqid(self):
        # The map popup links the section name, so the sqid rides along.
        from django.core.cache import cache

        from camp.apps.pesticides.models import PesticideNotice
        from camp.apps.regions.models import Region
        section = Region.objects.get(pk=9101)
        PesticideNotice.objects.filter(pk=2).update(mtrs=section)
        cache.clear()
        data = self.client.get(self.url).json()
        two = next(f for f in data['features'] if f['properties']['id'] == PesticideNotice.objects.get(pk=2).sqid)
        assert two['properties']['section'] == section.external_id
        assert two['properties']['section_id'] == section.sqid

    def test_past_notice_excluded(self):
        from camp.apps.pesticides.models import PesticideNotice
        data = self.client.get(self.url).json()
        assert PesticideNotice.objects.get(pk=1).sqid not in {f['properties']['id'] for f in data['features']}

    def test_bbox_and_filters(self):
        from camp.apps.pesticides.models import PesticideNotice
        from django.contrib.gis.geos import Point
        PesticideNotice.objects.filter(pk=2).update(point=Point(-119.79, 36.71, srid=4326))
        PesticideNotice.objects.filter(pk=3).update(point=Point(-119.04, 35.36, srid=4326))
        data = self.client.get(self.url, {'bbox': '-119.9,36.6,-119.7,36.8'}).json()
        assert [f['properties']['county'] for f in data['features']] == ['Fresno County']
        data = self.client.get(self.url, {'chemical': 1855}).json()   # glyphosate: only notice 3
        assert [f['properties']['id'] for f in data['features']] == [PesticideNotice.objects.get(pk=3).sqid]
        assert self.client.get(self.url, {'bbox': 'nope'}).status_code == 400

    def test_capped_by_count(self):
        from django.core.cache import cache

        from camp.api.v2.pesticides import sections
        old = sections.MAX_NOTICES
        sections.MAX_NOTICES = 1
        try:
            response = self.client.get(self.url)
        finally:
            sections.MAX_NOTICES = old
        assert response.status_code == 400
        assert 'zoom' in response.json()['error']
        # Under the cap (the whole fixture, no bbox) it still answers. Same
        # querystring, so drop the cached 400 first.
        cache.clear()
        assert self.client.get(self.url).status_code == 200

    def test_notice_without_point_has_null_geometry(self):
        data = self.client.get(self.url).json()
        assert all(f['geometry'] is None or f['geometry']['type'] == 'Point' for f in data['features'])


# ---------------------------------------------------------------------------
# County outlines and township grid GeoJSON endpoints
# ---------------------------------------------------------------------------

from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin
from camp.apps.pesticides.townships import township_of


class TownshipAndCountyTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def test_township_of(self):
        assert township_of('MDM-T14S-R20E-01') == 'MDM-T14S-R20E'
        assert township_of('MDM-T14S-R20E') == 'MDM-T14S-R20E'

    def test_counties_geojson(self):
        response = self.client.get('/api/2.0/pesticides/counties/')
        assert response.status_code == 200
        data = response.json()
        assert data['type'] == 'FeatureCollection'
        names = sorted(f['properties']['name'] for f in data['features'])
        assert names == ['Fresno County', 'Kern County']
        assert data['features'][0]['geometry']['type'] in ('Polygon', 'MultiPolygon')

    def test_townships_geojson_totals(self):
        response = self.client.get('/api/2.0/pesticides/townships/', {'year': 2023})
        assert response.status_code == 200
        features = {f['properties']['id']: f['properties'] for f in response.json()['features']}
        # 2023 in section 9101 (township MDM-T14S-R20E): uses 1, 2, 4, 6.
        assert features['MDM-T14S-R20E']['lbs_chemical'] == 670.0
        assert features['MDM-T14S-R20E']['applications'] == 4
        assert features['MDM-T14S-R20E']['sections'] == 1
        # Section 9102 (township MDM-T30S-R28E): uses 3, 5.
        assert features['MDM-T30S-R28E']['lbs_chemical'] == 70.0

    def test_townships_all_years(self):
        response = self.client.get('/api/2.0/pesticides/townships/', {'year': 'all'})
        assert response.json()['year'] == 'all'
        features = {f['properties']['id']: f['properties'] for f in response.json()['features']}
        assert features['MDM-T14S-R20E']['lbs_chemical'] == 1150.0
        assert features['MDM-T14S-R20E']['applications'] == 6

    def test_townships_bbox_and_filters(self):
        kern_only = self.client.get('/api/2.0/pesticides/townships/', {'year': 2023, 'bbox': '-119.1,35.3,-119.0,35.4'}).json()
        assert [f['properties']['id'] for f in kern_only['features']] == ['MDM-T30S-R28E']
        chem = self.client.get('/api/2.0/pesticides/townships/', {'year': 2023, 'chemical': 253}).json()
        by_id = {f['properties']['id']: f['properties'] for f in chem['features']}
        assert by_id['MDM-T14S-R20E']['lbs_chemical'] == 20.0
        assert self.client.get('/api/2.0/pesticides/townships/', {'bbox': 'nope'}).status_code == 400

    def test_county_filter_narrows_the_geometry(self):
        # The fixture's two sections sit one in Fresno (9101) and one in Kern (9102).
        valley = {'bbox': '-121,35,-118,37.5', 'year': 2023}
        both = self.client.get('/api/2.0/pesticides/sections/', valley).json()
        assert {f['properties']['mtrs'] for f in both['features']} >= {'MDM-T14S-R20E-01', 'MDM-T30S-R28E-01'}
        kern = self.client.get('/api/2.0/pesticides/sections/', {**valley, 'county': 'kern'}).json()
        assert [f['properties']['mtrs'] for f in kern['features']] == ['MDM-T30S-R28E-01']
        townships = self.client.get('/api/2.0/pesticides/townships/', {**valley, 'county': 'kern'}).json()
        assert [f['id'] for f in townships['features']] == ['MDM-T30S-R28E']
        # An unknown county narrows the numbers to nothing but leaves the geometry alone.
        nowhere = self.client.get('/api/2.0/pesticides/sections/', {**valley, 'county': 'nowhere'}).json()
        assert len(nowhere['features']) == len(both['features'])

    def test_townships_values_only(self):
        full = self.client.get('/api/2.0/pesticides/townships/', {'year': 2023}).json()
        values = self.client.get('/api/2.0/pesticides/townships/', {'year': 2023, 'geometry': '0'}).json()
        assert [f['id'] for f in values['features']] == [f['id'] for f in full['features']]
        assert all(f['geometry'] is None for f in values['features'])
        assert all(f['geometry'] is not None for f in full['features'])
        by_id = {f['properties']['id']: f['properties'] for f in values['features']}
        assert by_id['MDM-T14S-R20E']['lbs_chemical'] == 670.0

    def test_section_coordinates_rounded(self):
        response = self.client.get('/api/2.0/pesticides/sections/', {'year': 2023, 'bbox': '-119.9,36.6,-119.7,36.8'})
        ring = response.json()['features'][0]['geometry']['coordinates'][0][0]
        assert all(len(str(abs(v)).split('.')[-1]) <= 5 for pair in ring for v in pair)


# ---------------------------------------------------------------------------
# Entity search (the explorer's cross-entity autocomplete filters)
# ---------------------------------------------------------------------------

class EntitySearchTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.url = reverse('api:v2:pesticides:entity-search')

    def results(self, **params):
        response = self.client.get(self.url, params)
        assert response.status_code == 200
        return response.json()['results']

    def test_chemical_search_matches_and_shows_the_preferred_name(self):
        Chemical.objects.filter(pk=3).update(name='1080', preferred_name='Sodium fluoroacetate')
        by_name = self.results(type='chemical', q='fluoro')
        assert [r['name'] for r in by_name] == ['Sodium fluoroacetate']
        assert by_name[0]['detail'] == '1080 · 560'
        by_cdpr = self.results(type='chemical', q='1080')
        assert [r['name'] for r in by_cdpr] == ['Sodium fluoroacetate']

    def test_search_is_scoped_by_year_and_county(self):
        # Sulfur has use in 2023 in Fresno only (fixture totals); 2022 and Kern don't offer it.
        names = lambda **p: [r['name'] for r in self.results(type='chemical', q='sulf', **p)]
        assert names() == ['Sulfur']
        assert names(year='2023') == ['Sulfur']
        assert names(year='all') == ['Sulfur']
        assert names(year='2023', county='fresno') == ['Sulfur']
        assert names(county='kern') == []
        assert self.client.get(self.url, {'type': 'chemical', 'q': 'sulf', 'year': 'nope'}).status_code == 400

    def test_chemical_search_returns_name_and_chem_code(self):
        results = self.results(type='chemical', q='glyphosate')
        assert [r['name'] for r in results] == ['Glyphosate']
        chemical = Chemical.objects.get(name='GLYPHOSATE')
        assert results[0]['id'] == chemical.sqid
        assert results[0]['detail'] == str(chemical.chem_code)

    def test_product_search_detail_is_the_reg_number(self):
        results = self.results(type='product', q='roundup')
        assert [(r['name'], r['detail']) for r in results] == [('ROUNDUP PRO', '524-475')]

    def test_commodity_search_detail_is_the_site_code(self):
        results = self.results(type='commodity', q='grape')
        commodity = Commodity.objects.get(name='GRAPE')
        assert [(r['name'], r['detail']) for r in results] == [('Grape', commodity.site_code)]

    def test_partial_match_falls_back_to_icontains(self):
        assert 'Chlorpyrifos' in [r['name'] for r in self.results(type='chemical', q='chlorpy')]

    def test_unused_entities_are_not_offered(self):
        Chemical.objects.create(chem_code=30001, name='NEVER USED')
        assert self.results(type='chemical', q='never') == []

    def test_short_query_returns_nothing(self):
        assert self.results(type='chemical', q='g') == []
        assert self.results(type='chemical') == []

    def test_limit_is_honoured_and_capped(self):
        assert len(self.results(type='chemical', q='o', limit=1)) <= 1
        # Over the cap is clamped, not rejected.
        assert self.client.get(self.url, {'type': 'chemical', 'q': 'glyphosate', 'limit': 500}).status_code == 200

    def test_bad_type_is_a_400(self):
        response = self.client.get(self.url, {'type': 'nope', 'q': 'glyphosate'})
        assert response.status_code == 400
        assert 'type' in response.json()['error']

    def test_missing_type_is_a_400(self):
        assert self.client.get(self.url, {'q': 'glyphosate'}).status_code == 400

    def test_bad_limit_is_a_400(self):
        response = self.client.get(self.url, {'type': 'chemical', 'q': 'glyphosate', 'limit': 'nope'})
        assert response.status_code == 400

    def test_cached(self):
        assert len(self.results(type='chemical', q='glyphosate')) == 1
        Chemical.objects.filter(name='GLYPHOSATE').delete()
        assert [r['name'] for r in self.results(type='chemical', q='glyphosate')] == ['Glyphosate']


# ---------------------------------------------------------------------------
# Locations endpoint
# ---------------------------------------------------------------------------

from django.contrib.gis.geos import Point

from camp.apps.regions.models import Location


class LocationEndpointTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.url = reverse('api:v2:pesticides:location-list')
        self.county = Region.objects.get(pk=9001)
        self.district = Region.objects.create(
            name='Fresno Unified',
            slug='fresno-unified',
            type=Region.Type.SCHOOL_DISTRICT,
            external_id='0610170',
        )
        # Inside the fixture's Fresno square (-119.9,36.6 -> -119.7,36.8).
        self.school = Location.objects.create(
            type=Location.Type.PUBLIC_SCHOOL,
            name='Alpha Elementary',
            external_id='1',
            source='cde-public',
            address='1 Main St',
            city='Fresno',
            point=Point(-119.79, 36.71, srid=4326),
            county=self.county,
            district=self.district,
            metadata={'grades': 'K-6'},
            imported_at=timezone.now(),
        )
        self.daycare = Location.objects.create(
            type=Location.Type.CHILD_CARE,
            name='Bravo Child Care',
            external_id='2',
            source='cdss-ccl',
            city='Fresno',
            point=Point(-119.78, 36.72, srid=4326),
            county=self.county,
            metadata={'capacity': 42},
            imported_at=timezone.now(),
        )
        # Outside that bbox, down in Kern.
        self.private = Location.objects.create(
            type=Location.Type.PRIVATE_SCHOOL,
            name='Charlie Academy',
            external_id='3',
            source='cde-private',
            point=Point(-119.04, 35.36, srid=4326),
            county=Region.objects.get(pk=9002),
            metadata={'grade_low': 'K', 'grade_high': '8'},
            imported_at=timezone.now(),
        )

    def features(self, **params):
        response = self.client.get(self.url, params)
        assert response.status_code == 200, response.content
        return response.json()['features']

    def test_bbox_returns_geojson_points(self):
        response = self.client.get(self.url, {'bbox': '-119.9,36.6,-119.7,36.8'})
        assert response.status_code == 200
        data = response.json()
        assert data['type'] == 'FeatureCollection'
        assert [f['properties']['name'] for f in data['features']] == ['Alpha Elementary', 'Bravo Child Care']
        feature = data['features'][0]
        assert feature['type'] == 'Feature'
        assert feature['id'] == self.school.sqid
        assert feature['geometry'] == {'type': 'Point', 'coordinates': [-119.79, 36.71]}
        assert feature['properties'] == {
            'id': self.school.sqid,
            'name': 'Alpha Elementary',
            'type': 'public_school',
            'type_label': 'Public school',
            'address': '1 Main St',
            'city': 'Fresno',
            'district': 'Fresno Unified',
            'district_id': self.district.sqid,
            'grade_span': 'K-6',
            'capacity': None,
        }

    def test_child_care_properties(self):
        features = self.features(bbox='-119.9,36.6,-119.7,36.8', type='child_care')
        assert [f['properties']['name'] for f in features] == ['Bravo Child Care']
        props = features[0]['properties']
        assert props['capacity'] == 42
        assert props['grade_span'] is None
        assert props['district'] is None
        assert props['district_id'] is None
        assert props['type_label'] == 'Child care'

    def test_private_school_grade_span_from_low_high(self):
        features = self.features(bbox='-119.1,35.3,-119.0,35.4')
        assert [f['properties']['name'] for f in features] == ['Charlie Academy']
        assert features[0]['properties']['grade_span'] == 'K-8'

    def test_type_filter_accepts_a_comma_list(self):
        features = self.features(bbox='-120.0,35.0,-119.0,37.0', type='public_school,private_school')
        assert [f['properties']['name'] for f in features] == ['Alpha Elementary', 'Charlie Academy']

    def test_unknown_type_is_a_400(self):
        response = self.client.get(self.url, {'bbox': '-119.9,36.6,-119.7,36.8', 'type': 'nope'})
        assert response.status_code == 400
        assert 'type' in response.json()['error']

    def test_missing_bbox_is_a_400(self):
        assert self.client.get(self.url).status_code == 400

    def test_bad_bbox_is_a_400(self):
        assert self.client.get(self.url, {'bbox': '-119.9,36.6'}).status_code == 400
        assert self.client.get(self.url, {'bbox': '-119.7,36.6,-119.9,36.8'}).status_code == 400

    def test_huge_bbox_is_a_400(self):
        response = self.client.get(self.url, {'bbox': '-124,32,-114,42'})
        assert response.status_code == 400
        assert response.json()['error'] == 'bbox too large; zoom in'

    def test_cached(self):
        assert len(self.features(bbox='-119.9,36.6,-119.7,36.8')) == 2
        Location.objects.all().delete()
        assert len(self.features(bbox='-119.9,36.6,-119.7,36.8')) == 2


# ---------------------------------------------------------------------------
# Chemicals-of-concern scope (`?concern=1`)
# ---------------------------------------------------------------------------

class ConcernScopeEndpointTests(RollupTestMixin, TestCase):
    """
    GLYPHOSATE (IARC 2A / Prop 65) and CHLORPYRIFOS (CARB TAC) are of
    concern in the fixture; SULFUR is not and carries most of the pounds.
    """

    fixtures = ['pesticides-explorer']

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def test_sections_narrow_to_concern_chemicals(self):
        params = {'bbox': '-119.9,36.6,-119.7,36.8', 'year': 2023}
        assert self.client.get('/api/2.0/pesticides/sections/', params).json()['features'][0]['properties']['lbs_chemical'] == 670.0
        scoped = self.client.get('/api/2.0/pesticides/sections/', {**params, 'concern': '1'}).json()
        assert scoped['features'][0]['properties']['lbs_chemical'] == 170.0
        assert scoped['features'][0]['properties']['applications'] == 3

    def test_townships_narrow_to_concern_chemicals(self):
        response = self.client.get('/api/2.0/pesticides/townships/', {'year': 2023, 'concern': '1'})
        features = {f['properties']['id']: f['properties'] for f in response.json()['features']}
        assert features['MDM-T14S-R20E']['lbs_chemical'] == 170.0
        assert features['MDM-T30S-R28E']['lbs_chemical'] == 70.0

    def test_section_detail_narrows_to_concern_chemicals(self):
        section = Region.objects.get(pk=9101)
        url = f'/api/2.0/pesticides/sections/{section.sqid}/'
        data = self.client.get(url, {'year': 2023, 'concern': '1'}).json()
        assert [r.get('lbs_chemical') for r in data['years'] if r['year'] == 2023] == [170.0]
        assert [c['name'] for c in data['top_chemicals']] == ['GLYPHOSATE', 'CHLORPYRIFOS']

    def test_entity_search_narrows_chemicals_and_products(self):
        url = reverse('api:v2:pesticides:entity-search')
        results = lambda **p: [r['name'] for r in self.client.get(url, p).json()['results']]
        assert results(type='chemical', q='sulf') == ['Sulfur']
        assert results(type='chemical', q='sulf', concern='1') == []
        assert results(type='chemical', q='glyphosate', concern='1') == ['Glyphosate']
        assert results(type='product', q='sulfur', concern='1') == []
        assert results(type='product', q='roundup', concern='1') == ['ROUNDUP PRO']
