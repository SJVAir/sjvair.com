from django.test import TestCase
from django.urls import reverse

from camp.apps.pesticides import notes
from camp.apps.pesticides.models import Chemical, PesticideNotice, Product
from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin


class NotesModuleTests(TestCase):
    fixtures = ['pesticides-explorer']

    def test_datafile_is_complete(self):
        data = notes.all_notes()
        for key in notes.REQUIRED_KEYS:
            entry = data[key]
            assert entry['title'] and entry['summary'] and entry['source_url'].startswith('https://'), key
            assert entry['summary'].count('. ') <= 2, key

    def test_keys_for_chemical(self):
        assert notes.keys_for_chemical(Chemical.objects.get(pk=1)) == ['prop65', 'iarc_2a']
        assert notes.keys_for_chemical(Chemical.objects.get(pk=2)) == [
            'carb_tac', 'cholinesterase_inhibitor', 'california_restricted']
        assert notes.keys_for_chemical(Chemical.objects.get(pk=3)) == []

    def test_keys_for_product_and_notice(self):
        assert notes.keys_for_product(Product.objects.get(pk=2)) == ['fumigant', 'restricted_material']
        assert notes.keys_for_product(Product.objects.get(pk=1)) == []
        notice = PesticideNotice.objects.prefetch_related('chemicals', 'products').get(pk=3)
        assert notes.keys_for_notice(notice) == [
            'noi_meaning', 'restricted_material', 'prop65', 'iarc_2a', 'carb_tac',
            'cholinesterase_inhibitor', 'california_restricted', 'fumigant']

    def test_notes_for_skips_unknown(self):
        assert [n['key'] for n in notes.notes_for(['prop65', 'nope', 'prop65'])] == ['prop65']


class NotesRenderingTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def test_badge_tooltips_and_block_on_chemical_page(self):
        html = self.client.get(Chemical.objects.get(pk=1).get_absolute_url()).content.decode()
        prop65 = notes.note('prop65')['summary']
        assert f'data-tooltip="{prop65}"' in html
        assert 'What this means' in html and notes.note('iarc_2a')['title'] in html

    def test_no_block_without_badges(self):
        html = self.client.get(Chemical.objects.get(pk=3).get_absolute_url()).content.decode()
        assert 'What this means' not in html

    def test_product_page(self):
        html = self.client.get(Product.objects.get(pk=2).get_absolute_url()).content.decode()
        assert notes.note('restricted_material')['summary'] in html

    def test_notice_page_has_no_notes_block(self):
        # Badges carry their own tooltips; the block only lives on chemical and product pages.
        notice = PesticideNotice.objects.get(pk=3)
        html = self.client.get(reverse('pesticides:notice-detail', kwargs={'sqid': notice.sqid})).content.decode()
        assert 'What this means' not in html

    def test_landing_and_how_to_read_use_notes(self):
        html = self.client.get(reverse('pesticides:home')).content.decode()
        assert notes.note('prop65')['summary'] in html
        assert notes.note('pur_lag')['summary'] in html and notes.note('shades')['summary'] in html

    def test_list_pages_have_tooltips(self):
        html = self.client.get(reverse('pesticides:product-list')).content.decode()
        assert f'data-tooltip="{notes.note("fumigant")["summary"]}"' in html
