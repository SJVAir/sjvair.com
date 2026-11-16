from unittest.mock import patch

from django.test import TestCase

from camp.apps.pesticides import classes, maps, stats
from camp.apps.pesticides.models import PesticideUseRollup
from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin


class BreaksForTests(TestCase):
    def test_breaks_for(self):
        result = classes.breaks_for({1: 0, 2: 5, 3: 10})
        assert result == {'breaks': maps.quantile_classes({2: 5, 3: 10}).breaks, 'min': 5}

    def test_all_zero(self):
        assert classes.breaks_for({1: 0, 2: 0}) == {'breaks': [], 'min': None}
        assert classes.breaks_for({}) == {'breaks': [], 'min': None}


class ValleyClassesTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        super().setUp()
        self.year = stats.latest_year()

    def test_unfiltered_sections(self):
        # 2023: section 9101 has 670 lbs, 9102 70 lbs.
        result = classes.valley_classes('section', self.year, False, {})
        assert set(result) == set(classes.FIGURES)
        assert result['lbs_chemical'] == {'breaks': [70.0, 670.0], 'min': 70.0}

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
        assert result['lbs_chemical'] == {'breaks': [130.0, 1150.0], 'min': 130.0}

    def test_county_ignored(self):
        with patch.object(classes, 'build_classes', wraps=classes.build_classes) as build:
            a = classes.valley_classes('section', self.year, False, {'county': 'fresno'})
            b = classes.valley_classes('section', self.year, False, {})
        assert a == b
        assert build.call_count == 1

    def test_category_spellings_share_a_key(self):
        a = classes.cache_key('section', self.year, False, {}, {'category': ['carcinogen', 'toxic_air_contaminant']})
        b = classes.cache_key('section', self.year, False, {}, {'category': ['carcinogen', 'toxic_air_contaminant']})
        assert a == b
        assert a != classes.cache_key('section', self.year, False, {}, {'category': ['carcinogen']})
        assert a != classes.cache_key('township', self.year, False, {}, {'category': ['carcinogen', 'toxic_air_contaminant']})

    def test_import_retires(self):
        with patch.object(classes, 'build_classes', wraps=classes.build_classes) as build:
            classes.valley_classes('section', self.year, False, {})
            classes.valley_classes('section', self.year, False, {})
            assert build.call_count == 1
            stats.bump_data_version()
            classes.valley_classes('section', self.year, False, {})
            assert build.call_count == 2
