import pytest
from django.db import IntegrityError, transaction
from django.test import TestCase

from camp.apps.pesticides.models import PesticideUseRollup


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


from django.core.management import call_command
from io import StringIO

from camp.apps.pesticides import rollup, stats
from camp.apps.pesticides.models import PesticideUse
from camp.apps.pesticides.tests.rollup_mixin import RollupTestMixin


class RebuildTests(TestCase):
    fixtures = ['pesticides-explorer']

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


class MixinTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def test_mixin_builds_rows_before_tests(self):
        assert PesticideUseRollup.objects.count() == 9
