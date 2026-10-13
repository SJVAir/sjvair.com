from django.test import TestCase

from camp.apps.pesticides.models import Chemical, Commodity, Product


class ChemicalSearchTests(TestCase):
    fixtures = ['pesticides-explorer']

    def test_partial_substring_matches(self):
        names = list(Chemical.objects.search('chlor').values_list('name', flat=True))
        assert names == ['CHLORPYRIFOS']

    def test_case_insensitive_full_word(self):
        names = list(Chemical.objects.search('glyphosate').values_list('name', flat=True))
        assert names == ['GLYPHOSATE']

    def test_cas_number_matches(self):
        names = list(Chemical.objects.search('7704-34-9').values_list('name', flat=True))
        assert names == ['SULFUR']

    def test_no_match(self):
        assert Chemical.objects.search('zzzz').count() == 0

    def test_exact_name_ranks_first(self):
        Chemical.objects.create(chem_code=9999, name='SULFUR DIOXIDE')
        names = list(Chemical.objects.search('sulfur').values_list('name', flat=True))
        assert names[0] == 'SULFUR'
        assert set(names) == {'SULFUR', 'SULFUR DIOXIDE'}

    def test_chainable_with_filter(self):
        qs = Chemical.objects.search('sulfur').filter(iarc_group='')
        assert qs.count() == 1


class ProductSearchTests(TestCase):
    fixtures = ['pesticides-explorer']

    def test_name(self):
        assert list(Product.objects.search('lorsban').values_list('pk', flat=True)) == [2]

    def test_reg_number(self):
        assert list(Product.objects.search('62719-220').values_list('pk', flat=True)) == [2]


class CommoditySearchTests(TestCase):
    fixtures = ['pesticides-explorer']

    def test_name(self):
        assert list(Commodity.objects.search('alm').values_list('pk', flat=True)) == [1]

    def test_site_code(self):
        assert list(Commodity.objects.search('29143').values_list('pk', flat=True)) == [2]
