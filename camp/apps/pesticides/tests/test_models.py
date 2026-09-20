from django.test import TestCase

from camp.apps.pesticides.models import Chemical, Commodity, Product, display_chemical_name


class ChemicalClassificationTests(TestCase):
    fixtures = ['pesticides-explorer']

    def test_prop65_derived_from_categories(self):
        assert Chemical.objects.get(pk=1).is_prop65 is True   # carcinogen
        assert Chemical.objects.get(pk=2).is_prop65 is False
        assert Chemical.objects.get(pk=3).is_prop65 is False

    def test_tac_derived_from_categories(self):
        assert Chemical.objects.get(pk=2).is_tac is True
        assert Chemical.objects.get(pk=1).is_tac is False

    def test_of_concern(self):
        assert Chemical.objects.get(pk=1).is_of_concern is True   # prop65 + 2A
        assert Chemical.objects.get(pk=2).is_of_concern is True   # tac
        assert Chemical.objects.get(pk=3).is_of_concern is False

    def test_iarc_group_3_alone_is_not_of_concern(self):
        chem = Chemical.objects.get(pk=3)
        chem.iarc_group = Chemical.IARCGroup.GROUP_3
        assert chem.is_of_concern is False

    def test_other_categories_excludes_badge_implied_ones(self):
        chlorpyrifos = Chemical.objects.get(pk=2)   # TAC + cholinesterase inhibitor
        assert chlorpyrifos.other_categories == ['cholinesterase_inhibitor']
        glyphosate = Chemical.objects.get(pk=1)     # carcinogen only
        assert glyphosate.other_categories == []
        assert Chemical.objects.get(pk=3).other_categories == []

    def test_comptox_url(self):
        assert Chemical.objects.get(pk=1).comptox_url == 'https://comptox.epa.gov/dashboard/chemical/details/DTXSID1024143'
        assert Chemical.objects.get(pk=2).comptox_url is None


class ProductClassificationTests(TestCase):
    fixtures = ['pesticides-explorer']

    def test_contains_flags(self):
        roundup = Product.objects.get(pk=1)
        lorsban = Product.objects.get(pk=2)
        dust = Product.objects.get(pk=3)
        assert roundup.contains_prop65 is True
        assert roundup.contains_iarc is True
        assert roundup.contains_tac is False
        assert lorsban.contains_tac is True
        assert lorsban.contains_prop65 is False
        assert dust.is_of_concern is False
        assert roundup.is_of_concern is True


class AbsoluteUrlTests(TestCase):
    fixtures = ['pesticides-explorer']

    def test_chemical_url(self):
        chem = Chemical.objects.get(pk=1)
        assert chem.slug == 'glyphosate'
        assert chem.get_absolute_url() == f'/tools/pesticides/chemicals/{chem.sqid}/glyphosate/'

    def test_preferred_name_is_the_display_name_and_slug(self):
        chem = Chemical.objects.create(chem_code=633, name='1080', preferred_name='Sodium fluoroacetate')
        assert chem.display_name == 'Sodium fluoroacetate'
        assert str(chem) == 'Sodium fluoroacetate'
        assert chem.slug == 'sodium-fluoroacetate'
        assert chem.get_absolute_url().endswith('/sodium-fluoroacetate/')
        # Without one, the CDPR name stands.
        plain = Chemical.objects.get(pk=1)
        assert plain.preferred_name == ''
        assert plain.display_name == plain.name == 'GLYPHOSATE'
        assert Product.objects.get(pk=2).display_name == 'LORSBAN 4E'

    def test_preferred_name_only_replaces_the_same_name_or_a_bare_code(self):
        # Same name, better casing: CompTox's wins.
        assert display_chemical_name('GLYPHOSATE, ISOPROPYLAMINE SALT', 'Glyphosate isopropylamine salt') == 'Glyphosate isopropylamine salt'
        assert display_chemical_name('2,4-D, SODIUM SALT', '2,4-D sodium salt') == '2,4-D sodium salt'
        # A different name (CompTox's systematic name, or a mismatched DTXSID): CDPR's stays.
        assert display_chemical_name('2,4-D', '2,4-Dichlorophenoxyacetic acid') == '2,4-D'
        assert display_chemical_name('2,4-DINITROPHENOL', '3-Iodo-2-propynyl-N-butylcarbamate') == '2,4-DINITROPHENOL'
        # A CDPR name with no letters is a code, not a name: CompTox's wins.
        assert display_chemical_name('1080', 'Sodium fluoroacetate') == 'Sodium fluoroacetate'
        assert display_chemical_name('1080', '') == '1080'

    def test_product_url(self):
        product = Product.objects.get(pk=2)
        assert product.get_absolute_url() == f'/tools/pesticides/products/{product.sqid}/lorsban-4e/'

    def test_commodity_url(self):
        commodity = Commodity.objects.get(pk=1)
        assert commodity.get_absolute_url() == f'/tools/pesticides/commodities/{commodity.sqid}/almond/'

    def test_slug_never_empty(self):
        chem = Chemical(name='???', chem_code=999)
        assert chem.slug == 'chemical'
