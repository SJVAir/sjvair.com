from django.core.cache import cache
from django.test import TestCase

from camp.apps.pesticides import rollup, stats, tasks
from camp.apps.pesticides.models import Chemical, Commodity, PesticideNotice, PesticideUse, PesticideUseRollup, Product
from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin


class StatsTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()

    def test_latest_year(self):
        assert stats.latest_year() == 2023

    def test_latest_year_is_cached(self):
        assert stats.latest_year() == 2023
        PesticideUse.objects.all().delete()
        PesticideUseRollup.objects.all().delete()
        assert stats.latest_year() == 2023
        cache.clear()
        assert stats.latest_year() is None

    def test_years_loaded(self):
        assert stats.years_loaded() == (2022, 2023)

    def test_by_year_for_chemical(self):
        rows = stats.by_year(PesticideUseRollup.objects.filter(chemical_id=1))
        assert [(r['year'], r['lbs'], r['acres'], r['applications']) for r in rows] == [
            (2023, 180.0, 18.0, 3),
            (2022, 80.0, 8.0, 1),
        ]

    def test_by_year_uses_lbs_product_for_products(self):
        rows = stats.by_year(PesticideUseRollup.objects.filter(product_id=1), lbs_field='lbs_product')
        assert rows[0]['lbs'] == 450.0

    def test_by_county(self):
        rows = stats.by_county(PesticideUseRollup.objects.filter(chemical_id=1), 2023)
        assert [(r['county_name'], r['lbs'], r['applications']) for r in rows] == [
            ('Fresno County', 150.0, 2),
            ('Kern County', 30.0, 1),
        ]

    def test_year_totals(self):
        totals = stats.year_totals(PesticideUseRollup.objects.filter(chemical_id=1), 2023)
        assert totals == {'lbs': 180.0, 'applications': 3, 'counties': 2}

    def test_year_totals_empty(self):
        totals = stats.year_totals(PesticideUseRollup.objects.none(), 2023)
        assert totals == {'lbs': 0, 'applications': 0, 'counties': 0}

    def test_top_related_commodities_for_chemical(self):
        rows = stats.top_related(PesticideUseRollup.objects.filter(chemical_id=1), 2023, 'commodity')
        assert [(r.obj.name, r.lbs) for r in rows] == [('ALMOND', 130.0), ('GRAPE', 50.0)]
        assert isinstance(rows[0].obj, Commodity)

    def test_top_related_ignores_rows_with_unknown_pounds(self):
        # PUR reports confidential active ingredients with no pounds; the
        # rollup sums those to 0 (COALESCE), so a zero-pound row must rank
        # last, not float to the top.
        secret = Chemical.objects.create(chem_code=9999, name='AI IS CONFIDENTIAL')
        PesticideUse.objects.create(
            year=2023, use_no=99, county_id=9001, chemical=secret, commodity_id=1,
            lbs_chemical=None, application_date='2023-09-01',
        )
        rollup.rebuild_year(2023)
        rows = stats.top_related(PesticideUseRollup.objects.all(), 2023, 'chemical')
        assert [r.obj.name for r in rows] == ['SULFUR', 'GLYPHOSATE', 'CHLORPYRIFOS', 'AI IS CONFIDENTIAL']
        assert rows[-1].obj.name == 'AI IS CONFIDENTIAL'

    def test_top_related_respects_limit(self):
        rows = stats.top_related(PesticideUseRollup.objects.all(), 2023, 'chemical', limit=2)
        assert [r.obj.name for r in rows] == ['SULFUR', 'GLYPHOSATE']
        assert isinstance(rows[0].obj, Chemical)

    def test_by_month_fills_twelve(self):
        rows = stats.by_month(PesticideUseRollup.objects.filter(chemical_id=1), 2023)
        assert [r['month'] for r in rows] == list(range(1, 13))
        assert [r['lbs'] for r in rows][2:5] == [100.0, 50.0, 30.0]   # Mar, Apr, May
        assert sum(r['applications'] for r in rows) == 3

    def test_by_section(self):
        rows = stats.by_section(PesticideUseRollup.objects.filter(chemical_id=1), 2023)
        assert [(r['mtrs_id'], r['lbs'], r['applications']) for r in rows] == [(9101, 150.0, 2), (9102, 30.0, 1)]

    def test_by_township(self):
        totals = stats.by_township(PesticideUseRollup.objects.all(), 2023)
        assert set(totals) == {'MDM-T14S-R20E', 'MDM-T30S-R28E'}
        # Section 9101 rolls up into MDM-T14S-R20E: uses 1, 2, 4, 6.
        assert totals['MDM-T14S-R20E']['lbs_chemical'] == 670.0
        assert totals['MDM-T14S-R20E']['lbs_product'] == 970.0
        assert totals['MDM-T14S-R20E']['acres_treated'] == 67.0
        assert totals['MDM-T14S-R20E']['applications'] == 4
        # Section 9102 rolls up into MDM-T30S-R28E: uses 3, 5.
        assert totals['MDM-T30S-R28E']['lbs_chemical'] == 70.0
        assert totals['MDM-T30S-R28E']['applications'] == 2

    def test_by_township_respects_filters(self):
        totals = stats.by_township(PesticideUseRollup.objects.filter(chemical_id=1), 2023)
        assert totals['MDM-T14S-R20E']['lbs_chemical'] == 150.0
        assert totals['MDM-T30S-R28E']['lbs_chemical'] == 30.0

    def test_recent_uses_newest_first(self):
        uses = list(stats.recent_uses(PesticideUse.objects.filter(chemical_id=1), limit=2))
        assert [u.pk for u in uses] == [3, 2]

    def test_upcoming_notices_excludes_past(self):
        notices = list(stats.upcoming_notices(PesticideNotice.objects.filter(chemicals=2)))
        assert [n.pk for n in notices] == [2, 3]

    def test_notice_stays_active_through_the_four_day_grace_period(self):
        from datetime import timedelta
        from django.utils import timezone
        recent = PesticideNotice.objects.create(
            application_id=9001, comtrs='10M13S14E10', county_id=9001,
            scheduled_application=timezone.now() - timedelta(days=3),
        )
        stale = PesticideNotice.objects.create(
            application_id=9002, comtrs='10M13S14E11', county_id=9001,
            scheduled_application=timezone.now() - timedelta(days=5),
        )
        active = set(stats.upcoming_notices(PesticideNotice.objects.all(), limit=50).values_list('pk', flat=True))
        assert recent.pk in active
        assert stale.pk not in active

    def test_upcoming_by_county(self):
        rows = stats.upcoming_by_county(PesticideNotice.objects.filter(chemicals=2))
        assert rows == [
            {'county_name': 'Fresno County', 'count': 1},
            {'county_name': 'Kern County', 'count': 1},
        ]

    def test_notice_window(self):
        window = stats.notice_window()
        assert window['count'] == 3
        assert window['first'].year == 2020
        assert window['last'].year == 2099

    def test_landing_stats(self):
        data = stats.landing_stats()
        assert data['latest_year'] == 2023
        assert data['years'] == (2022, 2023)
        assert data['chemical_count'] == 3
        assert data['product_count'] == 3
        assert data['commodity_count'] == 3
        assert data['total_lbs'] == 740.0
        assert data['active_notices'] == 2   # the two 2099 notices; the 2020 one is long past
        assert [r.obj.name for r in data['top_chemicals']] == ['SULFUR', 'GLYPHOSATE', 'CHLORPYRIFOS']
        assert [r.obj.name for r in data['top_chemicals_of_concern']] == ['GLYPHOSATE', 'CHLORPYRIFOS']
        assert [r.obj.name for r in data['top_commodities']] == ['GRAPE', 'ALMOND', 'COTTON']
        assert [r.obj.name for r in data['top_products']] and all(r.lbs >= 0 for r in data['top_products'])
        assert [(r['county_name'], r['lbs']) for r in data['by_county']] == [('Fresno County', 670.0), ('Kern County', 70.0)]

    def test_available_years_and_resolve(self):
        assert stats.available_years() == [2022, 2023]
        assert stats.resolve_year('2022') == 2022
        assert stats.resolve_year('2023') == 2023
        assert stats.resolve_year('1999') == 2023
        assert stats.resolve_year('abc') == 2023
        assert stats.resolve_year(None) == 2023
        assert stats.year_query(2023) == ''
        assert stats.year_query(2022) == '?year=2022'

    def test_resolve_year_param(self):
        assert stats.resolve_year_param('all') == (None, True)
        assert stats.resolve_year_param('ALL') == (None, True)
        assert stats.resolve_year_param('2022') == (2022, False)
        assert stats.resolve_year_param('1999') == (2023, False)
        assert stats.resolve_year_param(None) == (2023, False)
        assert stats.year_query(None, True) == '?year=all'
        assert stats.year_param(None, True) == 'year=all'
        assert stats.year_label(None, True) == '2022\u20132023'
        assert stats.year_label(2022) == '2022'
        assert stats.year_label(None) == ''

    def test_resolve_year_param_empty_db(self):
        PesticideUse.objects.all().delete()
        PesticideUseRollup.objects.all().delete()
        cache.clear()
        assert stats.resolve_year_param('all') == (None, False)
        assert stats.year_label(None, True) == ''

    def test_all_years_aggregates_span_every_year(self):
        rows = PesticideUseRollup.objects.filter(chemical_id=1)
        assert stats.year_totals(rows, None, all_years=True) == {'lbs': 260.0, 'applications': 4, 'counties': 2}
        assert [(r['county_name'], r['lbs']) for r in stats.by_county(rows, None, all_years=True)] == [
            ('Fresno County', 230.0), ('Kern County', 30.0),
        ]
        by_month = stats.by_month(rows, None, all_years=True)
        assert by_month[2]['lbs'] == 180.0   # March 2023 (100) + March 2022 (80)
        assert sum(r['applications'] for r in by_month) == 4
        assert [(r.obj.name, r.lbs) for r in stats.top_related(rows, None, 'commodity', all_years=True)] == [
            ('ALMOND', 210.0), ('GRAPE', 50.0),
        ]

    def test_landing_stats_for_all_years(self):
        data = stats.landing_stats(all_years=True)
        assert data['all_years'] is True
        assert data['year'] is None
        assert data['year_label'] == '2022\u20132023'
        assert data['total_lbs'] == 1280.0      # 740 in 2023 + 540 in 2022
        assert data['applications'] == 9
        assert (data['chemical_count'], data['product_count'], data['commodity_count']) == (3, 3, 3)
        assert [r.obj.name for r in data['top_chemicals']] == ['SULFUR', 'GLYPHOSATE', 'CHLORPYRIFOS']
        assert [(r['county_name'], r['lbs']) for r in data['by_county']] == [
            ('Fresno County', 1150.0), ('Kern County', 130.0),
        ]
        # Its own cache key, alongside the per-year ones.
        assert cache.get(stats.landing_key('all')) is not None
        assert cache.get(stats.landing_key(2023)) is None

    def test_refresh_landing_stats_also_builds_the_all_years_entry(self):
        stats.refresh_landing_stats()
        assert cache.get(stats.landing_key('all'))['total_lbs'] == 1280.0

    def test_resolve_year_empty_db(self):
        PesticideUse.objects.all().delete()
        PesticideUseRollup.objects.all().delete()
        assert stats.available_years() == []
        assert stats.resolve_year('2022') is None
        assert stats.year_query(None) == ''

    def test_landing_stats_for_an_earlier_year(self):
        data = stats.landing_stats(2022)
        assert data['year'] == 2022
        assert data['latest_year'] == 2023
        assert data['total_lbs'] == 540.0
        assert data['applications'] == 3
        assert (data['chemical_count'], data['product_count'], data['commodity_count']) == (3, 3, 3)
        assert [r.obj.name for r in data['top_chemicals']] == ['SULFUR', 'GLYPHOSATE', 'CHLORPYRIFOS']
        assert [(r['county_name'], r['lbs']) for r in data['by_county']] == [('Fresno County', 480.0), ('Kern County', 60.0)]
        # Cached under its own key; the latest year is untouched.
        assert cache.get(stats.landing_key(2022)) is not None
        assert cache.get(stats.landing_key(2023)) is None

    def test_landing_stats_cached(self):
        stats.landing_stats()
        new = Chemical.objects.create(chem_code=999, name='NEW')
        PesticideUse.objects.create(
            year=2023, use_no=97, county_id=9001, chemical=new, commodity_id=1,
            lbs_chemical=5, application_date='2023-10-01',
        )
        rollup.rebuild_year(2023)
        assert stats.landing_stats()['chemical_count'] == 3

    def test_landing_stats_empty_db(self):
        PesticideNotice.objects.all().delete()
        PesticideUse.objects.all().delete()
        PesticideUseRollup.objects.all().delete()
        data = stats.landing_stats()
        assert data['latest_year'] is None
        assert data['total_lbs'] == 0
        assert data['top_chemicals'] == []
        assert data['by_county'] == []

    def test_refresh_landing_stats_repopulates_cache(self):
        first = stats.landing_stats()
        assert first['chemical_count'] == 3
        new = Chemical.objects.create(chem_code=999, name='NEW')
        PesticideUse.objects.create(
            year=2023, use_no=98, county_id=9001, chemical=new, commodity_id=1,
            lbs_chemical=5, application_date='2023-10-01',
        )
        rollup.rebuild_year(2023)
        assert stats.landing_stats()['chemical_count'] == 3   # still the cached value
        refreshed = stats.refresh_landing_stats()
        assert refreshed['chemical_count'] == 4
        assert stats.landing_stats()['chemical_count'] == 4

    def test_refresh_pesticide_landing_stats_task_populates_cache(self):
        cache.delete(stats.landing_key(2023))
        tasks.refresh_pesticide_landing_stats.call_local()
        assert cache.get(stats.landing_key(2023)) is not None


class TrendTests(TestCase):
    """`trend_deltas` and `trend_points` are pure: by_year rows in, geometry out."""

    def rows(self, *pairs):
        return [{'year': year, 'lbs': lbs, 'acres': 0, 'applications': 1} for year, lbs in pairs]

    def test_deltas_up_and_first_year(self):
        rows = self.rows((2023, 150.0), (2022, 100.0), (2014, 200.0))
        deltas = stats.trend_deltas(rows, 2023)
        assert deltas['previous'] == {'year': 2022, 'pct': 50.0}
        assert deltas['first'] == {'year': 2014, 'pct': -25.0}

    def test_deltas_down(self):
        rows = self.rows((2023, 88.0), (2022, 100.0), (2014, 128.0))
        deltas = stats.trend_deltas(rows, 2023)
        assert deltas['previous']['pct'] == -12.0
        assert round(deltas['first']['pct'], 2) == -31.25

    def test_deltas_unchanged_is_a_zero_pct_not_a_none(self):
        rows = self.rows((2023, 100.0), (2022, 100.0), (2014, 100.0))
        deltas = stats.trend_deltas(rows, 2023)
        assert deltas['previous'] == {'year': 2022, 'pct': 0.0}
        assert deltas['first'] == {'year': 2014, 'pct': 0.0}

    def test_deltas_from_a_zero_year_are_undefined(self):
        rows = self.rows((2023, 100.0), (2022, 0.0), (2014, None))
        deltas = stats.trend_deltas(rows, 2023)
        assert deltas['previous'] == {'year': 2022, 'pct': None}
        assert deltas['first'] == {'year': 2014, 'pct': None}

    def test_deltas_for_an_older_selected_year(self):
        rows = self.rows((2023, 150.0), (2022, 100.0), (2014, 50.0))
        deltas = stats.trend_deltas(rows, 2022)
        assert deltas['previous'] == {'year': 2014, 'pct': 100.0}
        assert deltas['first'] is None    # 2014 is the previous year; don't say it twice

    def test_deltas_under_all_years_reference_the_first_year_only(self):
        rows = self.rows((2023, 150.0), (2022, 100.0), (2014, 300.0))
        deltas = stats.trend_deltas(rows, None)
        assert deltas['previous'] is None
        assert deltas['first'] == {'year': 2014, 'pct': -50.0}

    def test_deltas_single_year(self):
        assert stats.trend_deltas(self.rows((2023, 150.0)), 2023) == {'previous': None, 'first': None}

    def test_deltas_empty(self):
        assert stats.trend_deltas([], 2023) == {'previous': None, 'first': None}

    def test_deltas_selected_year_missing_from_the_rows(self):
        assert stats.trend_deltas(self.rows((2023, 1.0), (2022, 1.0)), 1999) == {'previous': None, 'first': None}

    def test_deltas_on_another_field(self):
        rows = [
            {'year': 2023, 'lbs': None, 'acres': 0, 'applications': 4},
            {'year': 2022, 'lbs': None, 'acres': 0, 'applications': 2},
        ]
        assert stats.trend_deltas(rows, 2023, field='applications')['previous'] == {'year': 2022, 'pct': 100.0}

    def test_points_run_oldest_to_newest_within_bounds(self):
        rows = self.rows((2023, 100.0), (2022, 0.0), (2021, 50.0))
        points = stats.trend_points(rows, 'lbs')
        assert [p[2] for p in points] == [2021, 2022, 2023]
        assert [p[0] for p in points] == [6.0, 160.0, 314.0]
        assert [p[1] for p in points] == [45.0, 84.0, 6.0]
        assert all(6 <= p[1] <= 84 for p in points)

    def test_points_treat_missing_values_as_zero(self):
        points = stats.trend_points(self.rows((2023, 10.0), (2022, None)), 'lbs')
        assert [(p[1], p[3]) for p in points] == [(84.0, 0), (6.0, 10.0)]

    def test_points_all_zero_sit_on_the_baseline(self):
        points = stats.trend_points(self.rows((2023, 0.0), (2022, 0.0)), 'lbs')
        assert [p[1] for p in points] == [84.0, 84.0]

    def test_points_single_year_is_centered(self):
        points = stats.trend_points(self.rows((2023, 10.0)), 'lbs')
        assert [(p[0], p[1], p[2]) for p in points] == [(160.0, 6.0, 2023)]

    def test_points_empty(self):
        assert stats.trend_points([], 'lbs') == []


class ConcernScopeTests(RollupTestMixin, TestCase):
    """
    The "chemicals of concern" scope. In the fixture GLYPHOSATE (IARC 2A,
    Prop 65 carcinogen) and CHLORPYRIFOS (CARB TAC) are of concern; SULFUR
    is not, and it carries most of the pounds.
    """

    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()

    def test_scope_param_carries_concern(self):
        assert stats.scope_param(2023, concern=True) == 'concern=1'
        assert stats.scope_query(2023, concern=True) == '?concern=1'
        assert stats.scope_param(2022, False, 'kern', concern=True) == 'year=2022&county=kern&concern=1'
        assert stats.scope_param(2023) == ''

    def test_of_concern_chemicals(self):
        assert sorted(c.name for c in stats.of_concern_chemicals()) == ['CHLORPYRIFOS', 'GLYPHOSATE']

    def test_concern_rows_drop_the_rest(self):
        rows = stats.concern_rows(PesticideUseRollup.objects.all())
        assert stats.year_totals(rows, 2023) == {'lbs': 240.0, 'applications': 5, 'counties': 2}
        assert stats.year_totals(rows, None, all_years=True)['lbs'] == 380.0

    def test_landing_stats_narrow_to_chemicals_of_concern(self):
        data = stats.landing_stats(2023, concern=True)
        assert data['total_lbs'] == 240.0
        assert data['applications'] == 5
        assert data['chemical_count'] == 2
        assert data['product_count'] == 2
        assert [r.obj.name for r in data['top_chemicals']] == ['GLYPHOSATE', 'CHLORPYRIFOS']
        assert [(r['county_name'], r['lbs']) for r in data['by_county']] == [
            ('Fresno County', 170.0), ('Kern County', 70.0),
        ]
        assert [(r['year'], r['lbs']) for r in data['by_year']] == [(2023, 240.0), (2022, 140.0)]
        # Redundant under the toggle: everything listed is already of concern.
        assert 'top_chemicals_of_concern' not in data

    def test_landing_stats_cache_key_is_separate(self):
        stats.landing_stats(2023, concern=True)
        assert cache.get(stats.landing_key(2023, concern=True)) is not None
        assert cache.get(stats.landing_key(2023)) is None
        assert stats.landing_stats(2023)['total_lbs'] == 740.0

    def test_county_totals_narrow(self):
        assert [(r['county_name'], r['lbs']) for r in stats.county_totals(2023, concern=True)] == [
            ('Fresno County', 170.0), ('Kern County', 70.0),
        ]
        assert [(r['county_name'], r['lbs']) for r in stats.county_totals(2023)] == [
            ('Fresno County', 670.0), ('Kern County', 70.0),
        ]
