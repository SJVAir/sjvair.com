from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.regions.models import Region

from .rollup_mixin import RollupTestMixin


class SectionDetailTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        self.section = Region.objects.get(pk=9101)
        self.url = reverse('pesticides:section-detail', kwargs={'sqid': self.section.sqid})

    def test_renders(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        ctx = response.context
        assert ctx['county_name'] == 'Fresno County'
        assert (ctx['totals']['lbs'], ctx['totals']['applications'], ctx['totals']['counties']) == (670.0, 4, 1)
        assert [r.obj.name for r in ctx['top_chemicals']] == ['SULFUR', 'GLYPHOSATE', 'CHLORPYRIFOS']
        assert len(ctx['by_month']) == 12 and ctx['peak_month'] == 'August'
        assert ctx['map_config']['zoom'] == 13 and ctx['map_config']['center'] == '36.7100,-119.7900'
        html = response.content.decode()
        assert 'month-chart' in html and 'Spraying here peaks in August' in html
        assert reverse('pesticides:records') + f'?section={self.section.sqid}' in html

    def test_year_param(self):
        ctx = self.client.get(self.url, {'year': 2022}).context
        assert ctx['totals']['lbs'] == 480.0 and ctx['peak_month'] == 'August'

    def test_all_years(self):
        response = self.client.get(self.url, {'year': 'all'})
        ctx = response.context
        assert ctx['all_years'] is True
        # 670 lbs in 2023 (uses 1, 2, 4, 6) + 480 in 2022 (uses 7, 9).
        assert (ctx['totals']['lbs'], ctx['totals']['applications'], ctx['totals']['counties']) == (1150.0, 6, 1)
        assert ctx['chemical_count'] == 3
        assert ctx['by_month'][7]['lbs'] == 900.0   # August in both years
        assert [(r.obj.name, r.lbs) for r in ctx['top_chemicals']][0] == ('SULFUR', 900.0)
        assert ctx['records_url'] == reverse('pesticides:records') + f'?section={self.section.sqid}&year=all'
        assert 'Lbs applied in 2022\u20132023' in response.content.decode()

    def test_notices_in_section(self):
        from camp.apps.pesticides.models import PesticideNotice
        PesticideNotice.objects.filter(pk=2).update(mtrs=self.section)
        response = self.client.get(self.url)
        ctx = response.context
        assert [n.pk for n in ctx['upcoming']] == [2]
        # The badge counts every scheduled notice, not just the listed ones.
        assert ctx['upcoming_count'] == 1
        assert '1 scheduled' in response.content.decode()

    def test_404_for_non_section(self):
        county = Region.objects.get(pk=9001)
        assert self.client.get(reverse('pesticides:section-detail', kwargs={'sqid': county.sqid})).status_code == 404

    def test_api_detail_flags_top_chemicals_of_concern(self):
        # The map's section popup marks chemicals of concern with a dot, so
        # the detail endpoint it reads has to say which of the top chemicals
        # those are (Prop 65, TAC, or an IARC group of concern).
        url = reverse('api:v2:pesticides:section-detail', kwargs={'section_id': self.section.sqid})
        data = self.client.get(url, {'year': 2023}).json()
        assert {c['name']: c['is_of_concern'] for c in data['top_chemicals']} == {
            'SULFUR': False,
            'GLYPHOSATE': True,
            'CHLORPYRIFOS': True,
        }
