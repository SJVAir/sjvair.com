import pytest
from django.db import IntegrityError, transaction
from django.test import TestCase

from camp.apps.pesticides.models import PesticideUseRollup, PesticideUseTotal


class RollupModelTests(TestCase):
    fixtures = ['pesticides-explorer']

    def test_key_is_unique(self):
        kwargs = dict(year=2023, month=3, county_id=9001, mtrs_id=9101, chemical_id=1, product_id=1, commodity_id=1)
        PesticideUseRollup.objects.create(lbs_chemical=1, lbs_product=1, acres_treated=1, applications=1, **kwargs)
        with transaction.atomic(), pytest.raises(IntegrityError):
            PesticideUseRollup.objects.create(lbs_chemical=2, lbs_product=2, acres_treated=2, applications=2, **kwargs)

    def test_null_dimensions_are_part_of_the_key(self):
        kwargs = dict(year=2023, month=0, county_id=9001, mtrs=None, chemical=None, product=None, commodity=None)
        PesticideUseRollup.objects.create(applications=1, **kwargs)
        with transaction.atomic(), pytest.raises(IntegrityError):
            PesticideUseRollup.objects.create(applications=2, **kwargs)

    def test_nullable_dimensions(self):
        row = PesticideUseRollup.objects.create(
            year=2023, month=0, county_id=9001, mtrs=None, chemical=None, product=None, commodity=None,
            lbs_chemical=0, lbs_product=0, acres_treated=0, applications=1,
        )
        assert row.pk


from django.core.cache import cache
from django.core.management import call_command
from io import StringIO

from camp.apps.pesticides import rollup, stats
from camp.apps.pesticides.models import PesticideUse
from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin


class RebuildTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        # test_command primes stats.latest_year()'s cache while the rollup is
        # empty and asserts it comes back None -- that only holds if nothing
        # else populated LATEST_YEAR_KEY first. Every other pesticides test
        # class that touches the stats cache clears it in setUp for the same
        # reason; this one just hadn't needed to until another test file
        # sorting before this one started calling stats.resolve_year().
        cache.clear()

    def test_rebuild_year_sums_by_key(self):
        written = rollup.rebuild_year(2023)
        # 2023 fixture rows are all distinct keys (different month or entity), so 6 rows.
        assert written == 6
        row = PesticideUseRollup.objects.get(year=2023, chemical_id=1, commodity_id=1, county_id=9001)
        assert (row.month, row.mtrs_id, row.product_id) == (3, 9101, 1)
        assert (row.lbs_chemical, row.lbs_product, row.acres_treated, row.applications) == (100.0, 250.0, 10.0, 1)

    def test_rebuild_collapses_same_key(self):
        use = PesticideUse.objects.get(pk=1)
        use.pk = None
        use.use_no = 99
        use.lbs_chemical = 5
        use.lbs_product = 7
        use.acres_treated = 1
        use.save()   # same year, month, county, section, chemical, product, commodity as pk 1
        rollup.rebuild_year(2023)
        row = PesticideUseRollup.objects.get(year=2023, chemical_id=1, commodity_id=1, county_id=9001, month=3)
        assert (row.lbs_chemical, row.lbs_product, row.acres_treated, row.applications) == (105.0, 257.0, 11.0, 2)

    def test_rebuild_is_idempotent_and_replaces_the_year(self):
        assert rollup.rebuild_year(2023) == 6
        assert rollup.rebuild_year(2023) == 6
        assert PesticideUseRollup.objects.filter(year=2023).count() == 6
        PesticideUse.objects.filter(pk=6).delete()
        assert rollup.rebuild_year(2023) == 5

    def test_null_date_goes_to_month_zero(self):
        PesticideUse.objects.filter(pk=6).update(application_date=None)
        rollup.rebuild_year(2023)
        assert PesticideUseRollup.objects.get(year=2023, chemical_id=3).month == 0

    def test_null_section_is_kept(self):
        PesticideUse.objects.filter(pk=6).update(mtrs=None)
        rollup.rebuild_year(2023)
        row = PesticideUseRollup.objects.get(year=2023, chemical_id=3)
        assert row.mtrs_id is None
        assert row.county_id == 9001

    def test_rebuild_all_and_loaded_years(self):
        assert rollup.loaded_years() == [2022, 2023]
        assert rollup.rebuild_all() == {2022: 3, 2023: 6}

    def test_command(self):
        PesticideUseRollup.objects.all().delete()
        assert stats.latest_year() is None  # primes the cache while the rollup is empty

        out = StringIO()
        call_command('rebuild_pesticide_rollup', '--all', stdout=out)
        assert PesticideUseRollup.objects.count() == 9
        assert '2023' in out.getvalue()
        assert 'Refreshed cached year facts and landing stats.' in out.getvalue()
        assert stats.latest_year() == 2023  # refreshed by the command, not by clearing the cache here

        call_command('rebuild_pesticide_rollup', '--year', '2022', stdout=out)
        assert PesticideUseRollup.objects.filter(year=2022).count() == 3


class TotalsTests(TestCase):
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()
        rollup.rebuild_all()

    def test_chemical_totals_per_county(self):
        # Fresno 2023 glyphosate: uses 1 (100 lbs) + 2 (50 lbs).
        row = PesticideUseTotal.objects.get(year=2023, county_id=9001, chemical_id=1)
        assert (row.lbs_chemical, row.applications) == (150.0, 2)
        assert (row.product_id, row.commodity_id) == (None, None)
        # Kern 2023 glyphosate: use 3 only.
        assert PesticideUseTotal.objects.get(year=2023, county_id=9002, chemical_id=1).lbs_chemical == 30.0

    def test_commodity_totals(self):
        # Fresno 2023 almond: uses 1 (100 lbs) + 4 (20 lbs).
        row = PesticideUseTotal.objects.get(year=2023, county_id=9001, commodity_id=1)
        assert row.lbs_chemical == 120.0
        assert (row.chemical_id, row.product_id) == (None, None)

    def test_product_totals(self):
        # Kern 2023 LORSBAN 4E: use 5, 90 lbs of product.
        row = PesticideUseTotal.objects.get(year=2023, county_id=9002, product_id=2)
        assert row.lbs_product == 90.0
        assert (row.chemical_id, row.commodity_id) == (None, None)

    def test_rebuild_year_replaces_only_that_year(self):
        before = PesticideUseTotal.objects.filter(year=2022).count()
        rollup.rebuild_year(2023)
        assert PesticideUseTotal.objects.filter(year=2022).count() == before
        assert PesticideUseTotal.objects.filter(year=2023).exists()

    def test_totals_only_rebuilds_without_touching_the_rollup(self):
        rollup_rows = PesticideUseRollup.objects.count()
        PesticideUseTotal.objects.all().delete()

        out = StringIO()
        call_command('rebuild_pesticide_rollup', '--all', '--totals-only', stdout=out)
        assert PesticideUseRollup.objects.count() == rollup_rows
        assert PesticideUseTotal.objects.filter(year=2023, county_id=9001, chemical_id=1).get().lbs_chemical == 150.0
        assert 'total rows' in out.getvalue()

    def test_rebuild_totals_year_is_idempotent(self):
        written = rollup.rebuild_totals_year(2023)
        assert written == PesticideUseTotal.objects.filter(year=2023).count()
        assert rollup.rebuild_totals_year(2023) == written


class MixinTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def test_mixin_builds_rows_before_tests(self):
        assert PesticideUseRollup.objects.count() == 9

    def test_mixin_builds_totals_before_tests(self):
        assert PesticideUseTotal.objects.filter(year=2023, county_id=9001, chemical_id=1).get().lbs_chemical == 150.0
