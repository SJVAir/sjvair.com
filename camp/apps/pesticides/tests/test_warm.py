from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from camp.apps.pesticides import stats, warm
from camp.apps.pesticides.models import Chemical
from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin
from camp.apps.regions.models import Region
from camp.utils import warm as utils_warm


class WarmTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def test_paths_cover_the_landing_counties_and_top_entities_both_scopes(self):
        paths = warm.warm_paths()
        fresno = Region.objects.get(pk=9001)
        county = reverse('pesticides:region', kwargs={'sqid': fresno.sqid, 'slug': fresno.slug})
        chemical = Chemical.objects.filter(totals__year=stats.latest_year()).first().get_absolute_url()
        for page in (reverse('pesticides:home'), county, chemical):
            assert page in paths
            assert f'{page}?year=all' in paths
        assert reverse('api:v2:pesticides:township-list') in paths

    def test_warm_renders_each_page_once_per_data_version(self):
        first = warm.warm()
        assert first['warmed'] == len(warm.warm_paths()) and first['failed'] == 0
        # The pages' stats are now cached under the current version.
        assert stats.cached(stats.all_years_key('valley-by-year', ''), lambda: None) is not None

        second = warm.warm()
        assert (second['warmed'], second['skipped']) == (0, first['warmed'])
        # Unless forced: then every page renders again.
        assert warm.warm(force=True)['warmed'] == first['warmed']

        stats.bump_data_version()
        assert warm.warm()['warmed'] == first['warmed']

    def test_a_failed_page_is_retried_next_pass(self):
        home = reverse('pesticides:home')
        real = utils_warm.warm_path

        def fail_home(path):
            if path == home:
                raise RuntimeError('boom')
            return real(path)

        with mock.patch.object(utils_warm, 'warm_path', side_effect=fail_home):
            assert warm.warm()['failed'] == 1
        assert warm.warm()['warmed'] == 1

    @override_settings(BETA_TOOLS_GATE=True)
    def test_warms_behind_the_beta_gate(self):
        # Rendered without the middleware, so the gate never 404s the warmer.
        assert utils_warm.warm_path(reverse('pesticides:home')) == 200
