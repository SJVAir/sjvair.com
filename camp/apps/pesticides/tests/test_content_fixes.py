import re
from types import SimpleNamespace

from django.core.cache import cache
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from django.urls import reverse

from camp.apps.pesticides.models import Chemical, PesticideNotice, display_chemical_name
from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin
from camp.apps.regions.models import Boundary, Region


def squash(html):
    return ' '.join(html.split())


class PlaceContentTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.fresno = Region.objects.get(pk=9001)

    def make_city(self):
        city = Region.objects.create(name='Selma', slug='selma', type=Region.Type.CITY, external_id='c-selma')
        city.boundary = Boundary.objects.create(
            region=city, version='t',
            geometry='SRID=4326;MULTIPOLYGON (((-119.85 36.65, -119.75 36.65, -119.75 36.75, -119.85 36.75, -119.85 36.65)))')
        city.save()
        return city

    # M9 ------------------------------------------------------------------

    def test_a_county_views_all_in_each_kinds_own_list(self):
        ctx = self.client.get(self.fresno.get_pesticides_tab_url('overview'), {'year': 2023}).context
        for card, url_name in (('products_card', 'product-list'), ('chemicals_card', 'chemical-list'),
                               ('commodities_card', 'commodity-list')):
            url = ctx[card]['show_all_url']
            assert url.startswith(reverse(f'pesticides:{url_name}')), card
            assert 'county=fresno' in url, card
        assert len({ctx[c]['show_all_url'] for c in ('products_card', 'chemicals_card', 'commodities_card')}) == 3

    def test_another_place_falls_back_to_its_records(self):
        city = self.make_city()
        ctx = self.client.get(city.get_pesticides_tab_url('overview'), {'year': 2023}).context
        assert ctx['products_card']['show_all_url'] == ctx['records_url']

    def test_view_all_links_name_what_they_list(self):
        html = squash(self.client.get(self.fresno.get_pesticides_tab_url('overview'), {'year': 2023}).content.decode())
        names = re.findall(r'class="card-header-icon view-all"[^>]*>View all<span class="is-sr-only"> (\w+)</span>', html)
        assert set(names) <= {'products', 'chemicals', 'commodities'} and len(names) == len(set(names))

    # L5 ------------------------------------------------------------------

    def test_every_place_tab_titles_tab_then_place(self):
        for tab, label in (('overview', 'Overview'), ('notices', 'Notices'), ('records', 'Records'),
                           ('schools', 'Schools'), ('community', 'Community')):
            html = self.client.get(self.fresno.get_pesticides_tab_url(tab)).content.decode()
            assert f'<title>{label} · Fresno County | Pesticides | SJVAir</title>' in html, tab

    # M21 / L11 -----------------------------------------------------------

    def test_empty_scheduled_list_points_on(self):
        PesticideNotice.objects.all().delete()
        html = squash(self.client.get(self.fresno.get_pesticides_tab_url('notices')).content.decode())
        assert 'Nothing is scheduled.' in html
        assert 'Browse past notices' in html and 'past=1' in html
        assert 'sign up with SprayDays' in html and 'https://spraydays.cdpr.ca.gov/' in html
        assert 'No notices match' not in html

    def test_empty_archive_says_so_without_the_dead_end_links(self):
        PesticideNotice.objects.all().delete()
        html = squash(self.client.get(self.fresno.get_pesticides_tab_url('notices'), {'past': 1}).content.decode())
        assert 'No past notices match.' in html and 'Browse past notices' not in html

    def test_notice_count_copy(self):
        url = self.fresno.get_pesticides_tab_url('notices')
        past = squash(self.client.get(url, {'past': 1, 'month': 'all'}).content.decode())
        assert re.search(r'\d+ past notices? here\.', past)
        assert 'in the archive' not in past
        active = squash(self.client.get(url).content.decode())
        assert re.search(r'\d+ notices? currently scheduled here\.', active)

    # M23 -----------------------------------------------------------------

    def test_acre_treatments_is_the_one_term(self):
        html = self.client.get(self.fresno.get_pesticides_tab_url('records'), {'year': 2023}).content.decode()
        assert 'Acre-treatments' in html and 'Acres treated' not in html
        summary = self.client.get(reverse('pesticides:records'), {'year': 2023}).context['summary_sentence']
        assert 'acre-treatments' in summary and 'acres treated' not in summary

    # L7 / M13 ------------------------------------------------------------

    def test_section_codes_do_not_wrap(self):
        html = self.client.get(reverse('pesticides:records'), {'year': 2023}).content.decode()
        assert 'class="mtrs-code"' in html


class ChemicalNameTests(TestCase):
    def test_confidential_active_ingredient_is_spelled_out(self):
        assert display_chemical_name('AI IS CONFIDENTIAL', '') == 'Confidential active ingredient'
        chemical = Chemical(chem_code=-2, name='AI IS CONFIDENTIAL')
        assert chemical.display_name == 'Confidential active ingredient'
        assert chemical.cdpr_alias == 'AI IS CONFIDENTIAL'
        assert display_chemical_name('GLYPHOSATE', '') == 'Glyphosate'


class CommunityCardTests(TestCase):
    def render(self, **community):
        base = {'label': 'CalEnviroScreen 5.0', 'count': 2, 'scored': 2, 'dac_share': None, 'top25_tracts': 1,
                'min_p': None, 'max_p': None, 'lowest': None, 'highest': None, 'top': [], 'containing': None}
        base.update(community)
        return squash(render_to_string('regions/includes/community-card.html', {
            'community': base, 'show_top_tracts': True, 'community_about_url': '/about/'}))

    def test_heading_names_the_model_once(self):
        html = self.render()
        assert '<h2 class="title is-4">CalEnviroScreen 5.0</h2>' in html
        assert 'CalEnviroScreen CalEnviroScreen' not in html

    def test_tracts_read_as_number_and_place(self):
        row = {'region': SimpleNamespace(name='06019002001'), 'number': '20.01', 'place': 'Fresno',
               'ci_score_p': 99.4, 'dac': True}
        html = self.render(top=[row])
        assert 'Tract 20.01 · Fresno' in html and '06019002001' not in html
        bare = dict(row, place=None)
        assert 'Tract 20.01 <span' in self.render(top=[bare])
