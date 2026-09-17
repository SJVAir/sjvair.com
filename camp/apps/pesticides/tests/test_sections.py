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
        assert ctx['totals'] == {'lbs': 670.0, 'applications': 4, 'counties': 1}
        assert [r.obj.name for r in ctx['top_chemicals']] == ['SULFUR', 'GLYPHOSATE', 'CHLORPYRIFOS']
        assert len(ctx['by_month']) == 12 and ctx['peak_month'] == 'August'
        assert [u.pk for u in ctx['recent_uses']] == [6, 4, 2, 1]
        assert ctx['map_config']['zoom'] == 13 and ctx['map_config']['center'] == '36.7100,-119.7900'
        html = response.content.decode()
        assert 'month-bars' in html and 'Spraying here peaks in August' in html
        assert reverse('pesticides:records') + f'?section={self.section.sqid}' in html

    def test_year_param(self):
        ctx = self.client.get(self.url, {'year': 2022}).context
        assert ctx['totals']['lbs'] == 480.0 and ctx['peak_month'] == 'August'

    def test_notices_in_section(self):
        from camp.apps.pesticides.models import PesticideNotice
        PesticideNotice.objects.filter(pk=2).update(mtrs=self.section)
        ctx = self.client.get(self.url).context
        assert [n.pk for n in ctx['upcoming']] == [2]

    def test_404_for_non_section(self):
        county = Region.objects.get(pk=9001)
        assert self.client.get(reverse('pesticides:section-detail', kwargs={'sqid': county.sqid})).status_code == 404
