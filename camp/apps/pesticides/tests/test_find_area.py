import json

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

    def embedded_places(self, html):
        start = html.index('id="find-area-places"')
        start = html.index('>', start) + 1
        return json.loads(html[start:html.index('</script>', start)])

    def test_landing_has_find_area_block(self):
        response = self.client.get(self.url)
        html = response.content.decode()
        assert 'data-maptiler-key="test-key"' in html
        assert reverse('pesticides:near-me') in html
        assert 'find-area.js' in html
        assert 'How to read this page' in html
        assert 'Search a city, ZIP, county, or address' in html
        assert html.index('id="find"') < html.index('section-cards')

    def test_embedded_places_include_counties_with_their_region_urls(self):
        html = self.client.get(self.url).content.decode()
        places = self.embedded_places(html)
        by_name = {place['name']: place for place in places}

        for pk, slug in [(9001, 'fresno'), (9002, 'kern')]:
            region = Region.objects.get(pk=pk)
            place = by_name[region.name]
            assert place['type'] == Region.Type.COUNTY
            assert place['type_label'] == 'County'
            assert place['url'] == reverse('pesticides:region', kwargs={'sqid': region.sqid, 'slug': slug})

        # Sorted by name, and only places that have a boundary to scope.
        assert [place['name'] for place in places] == sorted(place['name'] for place in places)

    def test_county_links_row(self):
        html = self.client.get(self.url).content.decode()
        fresno = Region.objects.get(pk=9001)
        assert 'find-area-counties' in html
        assert reverse('pesticides:region', kwargs={'sqid': fresno.sqid, 'slug': 'fresno'}) in html
        # Links use the short name, not "Fresno County".
        assert '>Fresno</a>' in html

    def test_county_links_keep_the_year(self):
        html = self.client.get(self.url, {'year': 2022}).content.decode()
        fresno = Region.objects.get(pk=9001)
        url = reverse('pesticides:region', kwargs={'sqid': fresno.sqid, 'slug': 'fresno'})
        assert f'{url}?year=2022' in html

    def test_no_picker_form(self):
        html = self.client.get(self.url).content.decode()
        assert 'find-area-pickers' not in html
        # The old pickers redirected on ?county=; that GET handling is gone.
        assert self.client.get(self.url, {'county': 'nope:x'}).status_code == 200

    def test_focus_flag(self):
        assert 'autofocus' in self.client.get(self.url, {'find': 1}).content.decode()

    def test_county_names_link_to_region_pages(self):
        from camp.apps.pesticides.models import Chemical
        chem = Chemical.objects.get(pk=2)  # chlorpyrifos: on notices 2 and 3
        html = self.client.get(chem.get_absolute_url()).content.decode()
        kern = Region.objects.get(pk=9002)
        assert reverse('pesticides:region', kwargs={'sqid': kern.sqid, 'slug': 'kern'}) in html
