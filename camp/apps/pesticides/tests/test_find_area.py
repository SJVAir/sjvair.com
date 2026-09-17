from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin
from camp.apps.regions.models import Region


@override_settings(MAPTILER_API_KEY='test-key')
class FindAreaTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.url = reverse('pesticides:home')

    def test_landing_has_find_area_block(self):
        response = self.client.get(self.url)
        html = response.content.decode()
        assert 'data-maptiler-key="test-key"' in html
        assert reverse('pesticides:near-me') in html
        assert 'find-area.js' in html
        assert 'How to read this page' in html
        fresno = Region.objects.get(pk=9001)
        assert f'<option value="{fresno.sqid}:fresno">Fresno County</option>' in html
        assert html.index('id="find"') < html.index('stat-row')

    def test_picker_redirects_to_region_page(self):
        fresno = Region.objects.get(pk=9001)
        response = self.client.get(self.url, {'county': f'{fresno.sqid}:fresno', 'year': 2022})
        assert response.status_code == 302
        assert response['Location'] == reverse('pesticides:region', kwargs={'sqid': fresno.sqid, 'slug': 'fresno'}) + '?year=2022'

    def test_bad_picker_value_renders_landing(self):
        assert self.client.get(self.url, {'county': 'nope:x'}).status_code == 200

    def test_focus_flag(self):
        assert 'autofocus' in self.client.get(self.url, {'find': 1}).content.decode()

    def test_county_names_link_to_region_pages(self):
        from camp.apps.pesticides.models import Chemical
        chem = Chemical.objects.get(pk=2)  # chlorpyrifos: on notices 2 and 3
        html = self.client.get(chem.get_absolute_url()).content.decode()
        kern = Region.objects.get(pk=9002)
        assert reverse('pesticides:region', kwargs={'sqid': kern.sqid, 'slug': 'kern'}) in html
