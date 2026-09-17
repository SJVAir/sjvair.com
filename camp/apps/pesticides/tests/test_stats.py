from django.core.cache import cache
from django.test import TestCase

from camp.apps.pesticides import stats, tasks
from camp.apps.pesticides.models import Chemical, Commodity, PesticideNotice, PesticideUse, Product


class StatsTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()

    def test_latest_year(self):
        assert stats.latest_year() == 2023

    def test_latest_year_is_cached(self):
        assert stats.latest_year() == 2023
        PesticideUse.objects.all().delete()
        assert stats.latest_year() == 2023
        cache.clear()
        assert stats.latest_year() is None

    def test_years_loaded(self):
        assert stats.years_loaded() == (2022, 2023)

    def test_by_year_for_chemical(self):
        rows = stats.by_year(PesticideUse.objects.filter(chemical_id=1))
        assert [(r['year'], r['lbs'], r['acres'], r['applications']) for r in rows] == [
            (2023, 180.0, 18.0, 3),
            (2022, 80.0, 8.0, 1),
        ]

    def test_by_year_uses_lbs_product_for_products(self):
        rows = stats.by_year(PesticideUse.objects.filter(product_id=1), lbs_field='lbs_product')
        assert rows[0]['lbs'] == 450.0

    def test_by_county(self):
        rows = stats.by_county(PesticideUse.objects.filter(chemical_id=1), 2023)
        assert [(r['county_name'], r['lbs'], r['applications']) for r in rows] == [
            ('Fresno County', 150.0, 2),
            ('Kern County', 30.0, 1),
        ]

    def test_year_totals(self):
        totals = stats.year_totals(PesticideUse.objects.filter(chemical_id=1), 2023)
        assert totals == {'lbs': 180.0, 'applications': 3, 'counties': 2}

    def test_year_totals_empty(self):
        totals = stats.year_totals(PesticideUse.objects.none(), 2023)
        assert totals == {'lbs': 0, 'applications': 0, 'counties': 0}

    def test_top_related_commodities_for_chemical(self):
        rows = stats.top_related(PesticideUse.objects.filter(chemical_id=1), 2023, 'commodity')
        assert [(r.obj.name, r.lbs) for r in rows] == [('ALMOND', 130.0), ('GRAPE', 50.0)]
        assert isinstance(rows[0].obj, Commodity)

    def test_top_related_respects_limit(self):
        rows = stats.top_related(PesticideUse.objects.all(), 2023, 'chemical', limit=2)
        assert [r.obj.name for r in rows] == ['SULFUR', 'GLYPHOSATE']
        assert isinstance(rows[0].obj, Chemical)

    def test_recent_uses_newest_first(self):
        uses = list(stats.recent_uses(PesticideUse.objects.filter(chemical_id=1), limit=2))
        assert [u.pk for u in uses] == [3, 2]

    def test_upcoming_notices_excludes_past(self):
        notices = list(stats.upcoming_notices(PesticideNotice.objects.filter(chemicals=2)))
        assert [n.pk for n in notices] == [2, 3]

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
        assert data['upcoming_week'] == 0
        assert [r.obj.name for r in data['top_chemicals']] == ['SULFUR', 'GLYPHOSATE', 'CHLORPYRIFOS']
        assert [r.obj.name for r in data['top_chemicals_of_concern']] == ['GLYPHOSATE', 'CHLORPYRIFOS']
        assert [r.obj.name for r in data['top_commodities']] == ['GRAPE', 'ALMOND', 'COTTON']
        assert [(r['county_name'], r['lbs']) for r in data['by_county']] == [('Fresno County', 670.0), ('Kern County', 70.0)]

    def test_landing_stats_cached(self):
        stats.landing_stats()
        Chemical.objects.create(chem_code=1, name='NEW')
        assert stats.landing_stats()['chemical_count'] == 3

    def test_landing_stats_empty_db(self):
        PesticideNotice.objects.all().delete()
        PesticideUse.objects.all().delete()
        data = stats.landing_stats()
        assert data['latest_year'] is None
        assert data['total_lbs'] == 0
        assert data['top_chemicals'] == []
        assert data['by_county'] == []

    def test_refresh_landing_stats_repopulates_cache(self):
        first = stats.landing_stats()
        assert first['chemical_count'] == 3
        Chemical.objects.create(chem_code=999, name='NEW')
        refreshed = stats.refresh_landing_stats()
        assert refreshed['chemical_count'] == 4
        assert stats.landing_stats()['chemical_count'] == 4

    def test_refresh_pesticide_landing_stats_task_populates_cache(self):
        cache.delete(stats.LANDING_KEY)
        tasks.refresh_pesticide_landing_stats.call_local()
        assert cache.get(stats.LANDING_KEY) is not None
