from django.core.cache import cache
from django.test import TestCase
from django.utils.html import escape

from camp.apps.pesticides import notes, stats
from camp.apps.pesticides.models import PesticideNotice, PesticideUseRollup, Product
from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin

TOOLTIP = 'Not flagged as a fumigant by CDPR; its active ingredient is almost always applied as a fumigant.'


class IsFumigantReadTests(RollupTestMixin, TestCase):
    """The explorer reads Product.is_fumigant; CDPR's raw flag is only shown beside it."""

    fixtures = ['pesticides-explorer']

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # ROUNDUP: CDPR says no, the classifier says yes. LORSBAN: both say yes.
        Product.objects.filter(pk=1).update(is_fumigant=True, fumigant=False)
        Product.objects.filter(pk=2).update(is_fumigant=True)
        Product.objects.filter(pk=3).update(is_fumigant=False)

    def setUp(self):
        cache.clear()

    def test_narrow_rows_follows_is_fumigant(self):
        rows = stats.narrow_rows(PesticideUseRollup.objects.all(), stats.NARROW_FUMIGANT)
        products = set(rows.values_list('product_id', flat=True))
        assert 1 in products
        assert 3 not in products

    def test_narrow_notices_follows_is_fumigant(self):
        notices = stats.narrow_notices(PesticideNotice.objects.all(), stats.NARROW_FUMIGANT)
        assert 3 in set(notices.values_list('pk', flat=True))

    def test_narrow_notices_counts_a_fumigation_notice_with_no_linked_product(self):
        notice = PesticideNotice.objects.get(pk=1)
        notice.products.clear()
        assert notice.pk not in set(stats.narrow_notices(PesticideNotice.objects.all(), stats.NARROW_FUMIGANT).values_list('pk', flat=True))
        PesticideNotice.objects.filter(pk=1).update(application_method='fumigation')
        assert notice.pk in set(stats.narrow_notices(PesticideNotice.objects.all(), stats.NARROW_FUMIGANT).values_list('pk', flat=True))

    def test_landing_counts_is_fumigant_products(self):
        cache.clear()
        data = stats.landing_stats(2023)
        assert data['products_fumigant'] >= 2
        expected = Product.objects.filter(is_fumigant=True, pesticide_uses__year=2023).distinct().count()
        assert data['products_fumigant'] == expected

    def test_landing_cache_key_was_bumped(self):
        assert stats.LANDING_KEY.endswith(':v5')

    def test_keys_for_product_uses_is_fumigant(self):
        assert 'fumigant' in notes.keys_for_product(Product.objects.get(pk=1))
        assert 'fumigant' not in notes.keys_for_product(Product.objects.get(pk=3))

    def test_product_list_filter(self):
        from django.urls import reverse
        html = self.client.get(reverse('pesticides:product-list'), {'fumigant': 'true'}).content.decode()
        assert 'ROUNDUP PRO' in html and 'LORSBAN 4E' in html and 'SULFUR DUST' not in html

    def test_unflagged_badge_carries_the_tooltip(self):
        html = self.client.get(Product.objects.get(pk=1).get_absolute_url()).content.decode()
        assert f'data-tooltip="{escape(TOOLTIP)}">Fumigant</a>' in html

    def test_flagged_badge_has_no_extra_tooltip(self):
        html = self.client.get(Product.objects.get(pk=2).get_absolute_url()).content.decode()
        assert '>Fumigant</a>' in html
        assert escape(TOOLTIP) not in html

    def test_about_explains_the_classification(self):
        from django.urls import reverse
        html = self.client.get(reverse('pesticides:about')).content.decode()
        assert 'Telone' in html
        assert 'field fumigation' in html

    def test_fumigants_banner_names_classified_products(self):
        from django.urls import reverse
        html = self.client.get(reverse('pesticides:records'), {'narrow': 'fumigant'}).content.decode()
        assert 'products CDPR flags as fumigants, or whose active ingredient' in html

    def test_records_browser_narrows_to_classified_fumigants(self):
        from django.urls import reverse
        Product.objects.filter(pk=2).update(is_fumigant=False)
        response = self.client.get(reverse('pesticides:records'), {'narrow': 'fumigant'})
        assert [u.pk for u in response.context['object_list']] == [3, 2, 1]

    def test_sections_api_narrows_to_classified_fumigants(self):
        Product.objects.filter(pk=2).update(is_fumigant=False)
        params = {'bbox': '-119.9,36.6,-119.7,36.8', 'year': 2023}
        data = self.client.get('/api/2.0/pesticides/sections/', {**params, 'narrow': 'fumigant'}).json()
        assert data['features'][0]['properties']['lbs_chemical'] == 100.0 + 50.0

    def test_product_list_rows_render_the_unflagged_badge(self):
        from django.urls import reverse
        html = self.client.get(reverse('pesticides:product-list')).content.decode()
        assert f'data-tooltip="{escape(TOOLTIP)}">Fumigant</a>' in html

    def test_related_card_renders_product_badges_include(self):
        from django.template.loader import render_to_string
        html = render_to_string('pesticides/includes/product-badges.html', {'product': Product.objects.get(pk=1)})
        assert f'data-tooltip="{escape(TOOLTIP)}">Fumigant</a>' in html
