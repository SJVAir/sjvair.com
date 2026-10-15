from django.test import TestCase

from camp.apps.pesticides import fumigants
from camp.apps.pesticides.models import Chemical, PesticideUse, Product, ProductChemical


def make_telone_products():
    telone = Chemical.objects.create(chem_code=90001, name='1,3-DICHLOROPROPENE')
    flagged = Product.objects.create(prodno=90001, reg_number='62719-32-AA', name='TELONE OLD', fumigant=True)
    reregistered = Product.objects.create(prodno=90002, reg_number='95290-1-AA', name='TELONE II', fumigant=False)
    for product in (flagged, reregistered):
        ProductChemical.objects.create(product=product, chemical=telone, pct_active=97.5)
    return telone, flagged, reregistered


def add_use(product, chemical, lbs, method, year=2023):
    return PesticideUse.objects.create(
        year=year, use_no=PesticideUse.objects.count() + 10_000, county_id=9001,
        product=product, chemical=chemical, lbs_chemical=lbs, aerial_ground=method,
    )


class ClassifyFumigantsTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        self.telone, self.flagged, self.reregistered = make_telone_products()
        add_use(self.reregistered, self.telone, 1000, 'F')
        add_use(self.flagged, self.telone, 50, 'G')

    def test_unflagged_product_with_a_fumigant_ingredient_becomes_fumigant(self):
        result = fumigants.classify_fumigants()
        self.telone.refresh_from_db()
        self.reregistered.refresh_from_db()
        assert Chemical.Category.FUMIGANT in self.telone.categories
        assert self.reregistered.is_fumigant and not self.reregistered.fumigant
        assert result['added'] >= 1

    def test_cdpr_flagged_products_stay_fumigant(self):
        fumigants.classify_fumigants()
        assert Product.objects.get(pk=self.flagged.pk).is_fumigant
        assert Product.objects.get(pk=2).is_fumigant  # LORSBAN 4E, fumigant=True in the fixture

    def test_below_share_threshold_does_not_qualify(self):
        add_use(self.reregistered, self.telone, 200, 'G')  # 1050/1250 = 84% < 90%
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
        fumigants.classify_fumigants()
        first = set(Product.objects.filter(is_fumigant=True).values_list('pk', flat=True))
        fumigants.classify_fumigants()
        assert set(Product.objects.filter(is_fumigant=True).values_list('pk', flat=True)) == first
        add_use(self.reregistered, self.telone, 5000, 'G')
        fumigants.classify_fumigants()
        self.telone.refresh_from_db()
        assert Chemical.Category.FUMIGANT not in (self.telone.categories or [])

    def test_other_categories_are_untouched(self):
        chlorpyrifos = Chemical.objects.get(pk=2)
        before = set(chlorpyrifos.categories)
        fumigants.classify_fumigants()
        chlorpyrifos.refresh_from_db()
        assert set(chlorpyrifos.categories) - {Chemical.Category.FUMIGANT} == before - {Chemical.Category.FUMIGANT}
