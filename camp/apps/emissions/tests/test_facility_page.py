import re

from django.core.cache import cache
from django.test import TestCase

from camp.apps.emissions.models import Facility


class FacilityHeaderTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()

    def detail(self, name):
        return self.client.get(Facility.objects.get(name=name).get_absolute_url()).content.decode()

    def test_identity_where_and_regulator(self):
        content = self.detail('TEST PLANT')
        # Sector as a tag linking to its page; SIC on the grey identifiers line.
        assert re.search(r'<a class="tag[^"]*" href="/tools/emissions/sectors/glass/', content)
        assert 'class="identifiers has-text-grey"' in content and 'SIC 3221' in content
        # The address as reported, and the regulator's card.
        assert '123 Main St' in content and 'Fresno, CA 93728' in content
        # The county is in Counted in, not repeated in the address.
        assert 'Fresno, CA 93728 · Fresno County' not in content
        # The regulator is one line under the tags, not a card.
        assert re.search(r'<p class="facility-regulator">\s*Regulated by', content)
        assert 'San Joaquin Valley APCD' in content
        assert 'card-header-title">Regulated by' not in content
        # The district's phone is tappable, and the complaint form is the page's one button.
        assert 'href="tel:5592306000"' in content
        assert re.search(r'<a class="button[^"]*" href="https://ww2.valleyair.org/file-a-complaint"', content)

    def test_minor_source_tag(self):
        content = self.detail('TEST GAS STATION')
        assert re.search(r'<a class="tag[^"]*" href="/tools/emissions/about/#minor-sources"', content)

    def test_no_complaint_form_keeps_the_phone(self):
        content = self.detail('TEST CEMENT')
        assert 'href="tel:6618625250"' in content
        assert 'Report an air pollution problem' not in content


class HomeSearchTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def test_find_a_facility_sits_beside_find_your_area(self):
        cache.clear()
        from django.urls import reverse

        content = self.client.get(reverse('emissions:home'), {'minor': '1'}).content.decode()
        row = content[content.index('class="columns find-row"'):]
        assert row.index('id="find"') < row.index('class="box find-facility"') < row.index('Top 10 facilities')
        # The search keeps the scope, and there's only one facility search on the page.
        assert '<input type="hidden" name="minor" value="1">' in row[:row.index('Top 10 facilities')]
        assert content.count('id="facility-search"') == 1
