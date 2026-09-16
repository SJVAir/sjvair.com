from django.test import TestCase

from camp.apps.pesticides.models import Chemical, Commodity, PesticideNotice, PesticideUse, Product


class FixtureTests(TestCase):
    fixtures = ['pesticides-explorer']

    def test_fixture_loads_expected_counts(self):
        assert Chemical.objects.count() == 3
        assert Product.objects.count() == 3
        assert Commodity.objects.count() == 3
        assert PesticideUse.objects.count() == 9
        assert PesticideNotice.objects.count() == 3

    def test_counties_have_boundaries(self):
        from camp.apps.regions.models import Region
        for region in Region.objects.filter(type='county'):
            assert region.boundary is not None
            assert region.boundary.geometry.srid == 4326

    def test_array_field_and_m2m_loaded(self):
        chlorpyrifos = Chemical.objects.get(pk=2)
        assert 'toxic_air_contaminant' in chlorpyrifos.categories
        notice = PesticideNotice.objects.get(pk=3)
        assert set(notice.chemicals.values_list('pk', flat=True)) == {1, 2}
