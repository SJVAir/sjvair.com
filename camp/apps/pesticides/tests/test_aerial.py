from django.core.cache import cache
from django.db.models import Sum
from django.test import TestCase
from django.urls import reverse

from camp.apps.pesticides import rollup, stats
from camp.apps.pesticides.models import (
    Commodity, Product,
    Chemical, PesticideNotice, PesticideUse, PesticideUseRollup, PesticideUseTotal,
)
from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin
from camp.apps.regions.models import Region


class AerialNarrowingTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()

    def test_rollup_carries_method(self):
        assert set(PesticideUseRollup.objects.filter(year=2023).values_list('method', flat=True)) == {'A', 'G'}
        assert PesticideUseRollup.objects.filter(year=2023, method='A').aggregate(s=Sum('lbs_chemical'))['s'] == 70.0

    def test_totals_still_sum_every_method(self):
        assert PesticideUseTotal.objects.filter(year=2023, chemical__isnull=False).aggregate(s=Sum('lbs_chemical'))['s'] == 740.0

    def test_two_records_differing_only_by_method_make_two_rows(self):
        use = PesticideUse.objects.get(pk=1)
        use.pk = None
        use.use_no = 99999
        use.aerial_ground = 'A'
        use.save()
        rollup.rebuild_year(2023)
        assert PesticideUseRollup.objects.filter(year=2023, mtrs_id=9101, chemical_id=1, product_id=1, commodity_id=1, month=3).count() == 2

    def test_pages_narrow_to_air(self):
        chem = Chemical.objects.get(pk=1)
        assert self.client.get(chem.get_absolute_url(), {'narrow': 'aerial'}).context['totals']['lbs'] == 30.0
        place = Region.objects.get(pk=9001)
        ctx = self.client.get(reverse('pesticides:region', kwargs={'sqid': place.sqid, 'slug': place.slug}), {'narrow': 'aerial'}).context
        assert not ctx['totals']['applications']

    def test_county_totals_and_landing_under_aerial(self):
        assert {r['county_name'] for r in stats.county_totals(2023, False, 'aerial') if r['lbs']} == {'Kern County'}
        landing = stats.landing_stats(2023, concern='aerial')
        assert sum(r['lbs'] for r in landing['by_year'] if r['year'] == 2023) == 70.0

    def test_sections_api_narrows_to_air(self):
        data = self.client.get(reverse('api:v2:pesticides:section-list'), {'bbox': '-121,35,-118,38', 'year': 2023, 'narrow': 'aerial'}).json()
        lbs = {f['id']: f['properties']['lbs_chemical'] for f in data['features']}
        assert lbs.get(Region.objects.get(pk=9101).sqid, 0) == 0
        assert lbs[Region.objects.get(pk=9102).sqid] == 70.0

    def test_notices_narrow_to_aircraft(self):
        PesticideNotice.objects.filter(pk=3).update(application_method='Aircraft')
        assert list(stats.narrow_notices(PesticideNotice.objects.all(), 'aerial').values_list('pk', flat=True)) == [3]

    def test_records_browser_narrows_raw_records(self):
        ctx = self.client.get(reverse('pesticides:records'), {'narrow': 'aerial', 'year': 2023}).context
        assert {u.pk for u in ctx['object_list']} == {3, 5}

    def test_county_page_all_years_under_aerial_reads_the_rollup(self):
        kern = Region.objects.get(pk=9002)
        ctx = self.client.get(reverse('pesticides:region', kwargs={'sqid': kern.sqid, 'slug': kern.slug}), {'year': 'all', 'narrow': 'aerial'}).context
        assert ctx['totals']['lbs'] == 130.0

    def test_scope_bar_offers_applied_by_air(self):
        html = self.client.get(reverse('pesticides:chemical-list')).content.decode()
        assert 'narrow=aerial' in html and 'Applied by air' in html

    def test_banner_names_the_narrowing(self):
        html = self.client.get(reverse('pesticides:chemical-list'), {'narrow': 'aerial'}).content.decode()
        assert 'Showing only pesticide use applied by aircraft.' in html


class NarrowingExcludesSubjectTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()

    def test_commodity_never_applied_by_air_renders_the_empty_states(self):
        grape = Commodity.objects.get(pk=2)  # only ground use in the fixture
        ctx = self.client.get(grape.get_absolute_url(), {'narrow': 'aerial', 'year': 2023}).context
        assert ctx['concern_excluded'] is False
        assert not ctx['totals']['lbs']
        html = self.client.get(grape.get_absolute_url(), {'narrow': 'aerial', 'year': 2023}).content.decode()
        assert 'Showing only pesticide use applied by aircraft.' in html
        assert 'No flagged chemical was reported' not in html

    def test_commodity_with_no_fumigant_use_renders_the_empty_states(self):
        Product.objects.update(is_fumigant=False)
        grape = Commodity.objects.get(pk=2)
        ctx = self.client.get(grape.get_absolute_url(), {'narrow': 'fumigant', 'year': 2023}).context
        assert ctx['concern_excluded'] is False
        assert not ctx['totals']['lbs']

    def test_active_notices_narrow_to_aircraft(self):
        PesticideNotice.objects.filter(pk=3).update(application_method='Aircraft')
        url = reverse('api:v2:pesticides:notice-active')
        every = self.client.get(url).json()['features']
        narrowed = self.client.get(url, {'narrow': 'aerial'}).json()['features']
        assert len(every) > len(narrowed) == 1
        assert narrowed[0]['id'] == PesticideNotice.objects.get(pk=3).sqid

    def test_picker_help_comes_from_the_choices(self):
        html = self.client.get(reverse('pesticides:chemical-list')).content.decode()
        assert stats.NARROW_HELP['aerial'].replace("'", '&#x27;') in html


class MethodBreakdownPageTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']
    NOTE = 'Not reported is mostly structural, landscape and right-of-way use, which is reported in monthly summaries without a method.'

    def setUp(self):
        cache.clear()

    def test_chemical_page(self):
        chem = Chemical.objects.get(pk=1)
        html = self.client.get(chem.get_absolute_url(), {'year': 2023}).content.decode()
        assert 'method-breakdown' in html and 'How it was applied' in html
        assert 'Ground' in html and 'Air' in html
        assert self.NOTE not in html

    def test_note_shown_when_not_reported_present(self):
        PesticideUseRollup.objects.filter(year=2023, method='A').update(method='')
        chem = Chemical.objects.get(pk=1)
        ctx = self.client.get(chem.get_absolute_url(), {'year': 2023}).context
        assert [r['label'] for r in ctx['by_method']] == ['Ground', 'Not reported']
        assert self.NOTE in self.client.get(chem.get_absolute_url(), {'year': 2023}).content.decode()

    def test_county_and_section_pages(self):
        kern = Region.objects.get(name__startswith='Kern', type='county')
        html = self.client.get(reverse('pesticides:region', kwargs={'sqid': kern.sqid, 'slug': kern.slug}), {'year': 2023}).content.decode()
        assert 'method-breakdown' in html
        section = Region.objects.get(pk=9102)
        ctx = self.client.get(reverse('pesticides:section-detail', kwargs={'sqid': section.sqid}), {'year': 2023}).context
        assert [r['method'] for r in ctx['by_method']] == ['A']
        assert 'method-breakdown' in self.client.get(reverse('pesticides:section-detail', kwargs={'sqid': section.sqid}), {'year': 2023}).content.decode()

    def test_no_use_in_scope_year_hides_it(self):
        chem = Chemical.objects.get(pk=1)
        PesticideUseRollup.objects.filter(chemical=chem, year=2023).delete()
        response = self.client.get(chem.get_absolute_url(), {'year': 2023})
        assert response.context['by_method'] == []
        assert 'method-breakdown' not in response.content.decode()

    def test_aerial_narrowing_is_one_row(self):
        chem = Chemical.objects.get(pk=1)
        ctx = self.client.get(chem.get_absolute_url(), {'year': 2023, 'narrow': 'aerial'}).context
        assert [(r['label'], r['share']) for r in ctx['by_method']] == [('Air', 1.0)]
        html = self.client.get(chem.get_absolute_url(), {'year': 2023, 'narrow': 'aerial'}).content.decode()
        assert '100%' in html

    def test_records_method_select_and_labels(self):
        ctx = self.client.get(reverse('pesticides:records'), {'year': 2023}).context
        labels = [str(label) for value, label in ctx['form'].fields['method'].choices]
        assert labels == ['Any', 'Ground', 'Air', 'Field fumigation', 'Other', 'Not reported']
        html = self.client.get(reverse('pesticides:records'), {'year': 2023}).content.decode()
        assert '>Air<' in html and '>Ground<' in html

    def test_records_not_reported_filter(self):
        PesticideUse.objects.filter(pk=1).update(aerial_ground='')
        ctx = self.client.get(reverse('pesticides:records'), {'year': 2023, 'method': 'none'}).context
        assert [u.pk for u in ctx['object_list']] == [1]

    def test_placeholder_chemical_shares_applications(self):
        placeholder = Chemical.objects.create(chem_code=-2, name='AI IS CONFIDENTIAL')
        for method, apps in (('G', 3), ('A', 1)):
            row = PesticideUseRollup.objects.filter(year=2023, method='G').first()
            row.pk = None
            row.chemical = placeholder
            row.method = method
            row.lbs_chemical = 0
            row.lbs_product = 0
            row.applications = apps
            row.records = apps
            row.lbs_product_once = 0
            row.save()
        response = self.client.get(placeholder.get_absolute_url(), {'year': 2023})
        assert [(r['label'], r['app_share']) for r in response.context['by_method']] == [('Ground', 0.75), ('Air', 0.25)]
        html = response.content.decode()
        block = html[html.index('method-breakdown'):]
        assert 'Share of applications' in block and '75%' in block and '25%' in block
        assert '>Lbs<' not in block.split('</table>')[0]
