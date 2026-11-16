from unittest.mock import patch

from django.test import TestCase

from camp.apps.pesticides import classes, maps, stats
from camp.apps.pesticides.models import PesticideUseRollup
from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin


class BreaksForTests(TestCase):
    def test_breaks_for(self):
        result = classes.breaks_for({1: 0, 2: 5, 3: 10})
        quantiles = maps.quantile_classes({2: 5, 3: 10})
        assert result == {'breaks': quantiles.breaks, 'min': 5, 'colors': quantiles.colors}

    def test_colors_one_per_class_sampled_from_the_ramp(self):
        # Fewer distinct values than ramp stops: the colors are sampled across the
        # whole ramp (maps.sample_ramp), not its first stops, and end on the darkest.
        result = classes.breaks_for({1: 5, 2: 10, 3: 20})
        assert len(result['colors']) == len(result['breaks']) == 3
        assert result['colors'] == maps.sample_ramp(maps.RAMP, 3)
        assert result['colors'][-1] == maps.RAMP[-1]
        assert result['colors'][0] == maps.RAMP[0]

    def test_cache_key_is_versioned_for_colors(self):
        # Entries cached before `colors` existed must never be served.
        assert ':classes-v2:' in classes.cache_key('section', 2023, False, {}, {})

    def test_all_zero(self):
        assert classes.breaks_for({1: 0, 2: 0}) == {'breaks': [], 'min': None, 'colors': []}
        assert classes.breaks_for({}) == {'breaks': [], 'min': None, 'colors': []}


class ValleyClassesTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        super().setUp()
        self.year = stats.latest_year()

    def test_unfiltered_sections(self):
        # 2023: section 9101 has 670 lbs, 9102 70 lbs.
        result = classes.valley_classes('section', self.year, False, {})
        assert set(result) == set(classes.FIGURES)
        assert result['lbs_chemical'] == {'breaks': [70.0, 670.0], 'min': 70.0, 'colors': maps.sample_ramp(maps.RAMP, 2)}

    def test_unfiltered_matches_rollup(self):
        # The PesticideSectionTotal fast path gives what the rollup path would.
        from camp.api.v2.pesticides.sections import section_figures
        rows = stats.in_year(PesticideUseRollup.objects.filter(mtrs__isnull=False), self.year)
        figures = section_figures(rows, {}, {})
        expected = {f: classes.breaks_for({k: v[f] for k, v in figures.items()}) for f in classes.FIGURES}
        assert classes.valley_classes('section', self.year, False, {}) == expected

    def test_township_unfiltered_matches_by_township(self):
        by_township = stats.by_township(PesticideUseRollup.objects.all(), self.year)
        expected = {f: classes.breaks_for({k: v[f] for k, v in by_township.items()}) for f in classes.FIGURES}
        assert classes.valley_classes('township', self.year, False, {}) == expected

    def test_all_years(self):
        # 9101: 670 + 480; 9102: 70 + 60.
        result = classes.valley_classes('section', None, True, {})
        assert result['lbs_chemical'] == {'breaks': [130.0, 1150.0], 'min': 130.0, 'colors': maps.sample_ramp(maps.RAMP, 2)}

    def test_county_ignored(self):
        with patch.object(classes, 'build_classes', wraps=classes.build_classes) as build:
            a = classes.valley_classes('section', self.year, False, {'county': 'fresno'})
            b = classes.valley_classes('section', self.year, False, {})
        assert a == b
        assert build.call_count == 1

    def test_cache_key_normalizes(self):
        key = lambda params, filters=None: classes.cache_key('section', self.year, False, params, filters or {})  # noqa: E731
        assert key({'month': '6'}) == key({'month': '06'}) == key({'month': 6})
        assert key({'narrow': 'Concern'}) == key({'narrow': 'concern'}) == key({'concern': '1'})
        assert key({'narrow': 'junk'}) == key({})
        assert key({'chemical': '0253'}) == key({'chemical': '253'})
        assert key({'commodity': '29143'}) != key({})
        cats = ['carcinogen', 'toxic_air_contaminant']
        assert key({}, {'category': cats}) != key({}, {'category': ['carcinogen']})
        assert key({}, {'category': cats}) != classes.cache_key('township', self.year, False, {}, {'category': cats})
        assert key({'month': '6'}) != key({'month': '7'})

    def test_import_retires(self):
        with patch.object(classes, 'build_classes', wraps=classes.build_classes) as build:
            classes.valley_classes('section', self.year, False, {})
            classes.valley_classes('section', self.year, False, {})
            assert build.call_count == 1
            stats.bump_data_version()
            classes.valley_classes('section', self.year, False, {})
            assert build.call_count == 2
