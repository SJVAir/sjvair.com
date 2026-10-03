import importlib
from unittest import mock

import pytest
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.test import TestCase

from camp.apps.pesticides.models import (
    Chemical, PesticideSectionTotal, PesticideUseRollup, PesticideUseTotal,
)


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
from camp.apps.pesticides.models import PesticideUse, Product
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

    def test_rebuild_all_classifies_fumigants(self):
        from camp.apps.pesticides.tests.test_fumigants import add_use, make_telone_products
        telone, flagged, reregistered = make_telone_products()
        add_use(reregistered, telone, 1000, 'F')
        assert not reregistered.is_fumigant
        rollup.rebuild_all()
        reregistered.refresh_from_db()
        assert reregistered.is_fumigant

    def test_rebuild_all_classifies_before_the_first_year_and_goes_newest_first(self):
        calls = []
        with mock.patch.object(rollup.fumigants, 'classify_fumigants', side_effect=lambda: calls.append('classify')), \
                mock.patch.object(rollup, 'rebuild_year', side_effect=lambda year: calls.append(year) or 0):
            written = rollup.rebuild_all()
        assert calls == ['classify', 2023, 2022]
        assert written == {2022: 0, 2023: 0}

    def test_all_command_classifies_first_and_rebuilds_newest_first(self):
        calls = []
        with mock.patch('camp.apps.pesticides.fumigants.classify_fumigants',
                side_effect=lambda: calls.append('classify') or {'chemicals': 1, 'products': 1234, 'added': 0}), \
                mock.patch.object(rollup, 'rebuild_year', side_effect=lambda year: calls.append(year) or 0):
            out = StringIO()
            call_command('rebuild_pesticide_rollup', '--all', stdout=out)
        assert calls == ['classify', 2023, 2022]
        assert 'Fumigants: 1 chemicals, 1,234 products (0 not flagged by CDPR)' in out.getvalue()
        assert out.getvalue().index('Fumigants:') < out.getvalue().index('2023:')

    def test_migration_backfills_is_fumigant_from_the_cdpr_flag(self):
        migration = importlib.import_module('camp.apps.pesticides.migrations.0013_product_is_fumigant').Migration
        sql = [op.sql for op in migration.operations if op.__class__.__name__ == 'RunSQL']
        assert sql == ['UPDATE pesticides_product SET is_fumigant = fumigant']
        assert Product._meta.db_table == 'pesticides_product'

    def test_fumigants_only_command_skips_the_rollup(self):
        from camp.apps.pesticides.tests.test_fumigants import add_use, make_telone_products
        telone, flagged, reregistered = make_telone_products()
        add_use(reregistered, telone, 1000, 'F')
        before = PesticideUseRollup.objects.count()
        out = StringIO()
        call_command('rebuild_pesticide_rollup', '--fumigants-only', stdout=out)
        assert PesticideUseRollup.objects.count() == before
        assert Product.objects.get(pk=reregistered.pk).is_fumigant
        assert 'fumigant' in out.getvalue().lower()
        assert 'Fumigants: 2 chemicals, 3 products (1 not flagged by CDPR)' in out.getvalue()

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

    def test_totals_only_rebuilds_the_section_totals_too(self):
        # Everything the rollup feeds is rebuilt by the one command. A table
        # it didn't know about would be left empty and the map would read
        # zeros for every section.
        PesticideSectionTotal.objects.all().delete()

        call_command('rebuild_pesticide_rollup', '--all', '--totals-only', stdout=StringIO())

        assert PesticideSectionTotal.objects.filter(year=2023, mtrs_id=9101).get().lbs_chemical == 670.0

    def test_rebuild_totals_year_is_idempotent(self):
        written = rollup.rebuild_totals_year(2023)
        expected = (PesticideUseTotal.objects.filter(year=2023).count()
            + PesticideSectionTotal.objects.filter(year=2023).count())
        assert written == expected
        assert rollup.rebuild_totals_year(2023) == written


class MixinTests(RollupTestMixin, TestCase):
    fixtures = ['pesticides-explorer']

    def test_mixin_builds_rows_before_tests(self):
        assert PesticideUseRollup.objects.count() == 9

    def test_mixin_builds_totals_before_tests(self):
        assert PesticideUseTotal.objects.filter(year=2023, county_id=9001, chemical_id=1).get().lbs_chemical == 150.0


class OncePerRecordTests(TestCase):
    """
    A use record with two active ingredients is two PesticideUse rows (same
    year and use_no). The rollup designates one row per record so cross-chemical
    sums can count it once, while per-row measures stay right per chemical.
    """
    fixtures = ['pesticides-explorer']

    def setUp(self):
        self.product = Product.objects.create(prodno=95001, reg_number='95001-1', name='MULTI PRODUCT')
        self.low = Chemical.objects.create(chem_code=8001, name='LOW CHEM')
        self.high = Chemical.objects.create(chem_code=8002, name='HIGH CHEM')
        # Created high-first, so the designated row is chosen by chemical_id, not insertion order.
        self.multi = [
            self.use(use_no=7001, chemical=self.high),
            self.use(use_no=7001, chemical=self.low),
        ]
        self.single = self.use(use_no=7002, chemical=self.low)
        rollup.rebuild_year(2023)

    def use(self, use_no, chemical, **kwargs):
        kwargs.setdefault('lbs_product', 100)
        return PesticideUse.objects.create(
            year=2023, use_no=use_no, county_id=9001, mtrs_id=9101, product=self.product,
            chemical=chemical, application_date='2023-07-05', **kwargs,
        )

    def rows(self):
        return PesticideUseRollup.objects.filter(year=2023, month=7, product=self.product)

    def test_records_counts_each_use_record_once(self):
        totals = self.rows().aggregate(records=Sum('records'), applications=Sum('applications'))
        assert totals == {'records': 2, 'applications': 3}

    def test_product_pounds_once_per_record(self):
        totals = self.rows().aggregate(once=Sum('lbs_product_once'), per_row=Sum('lbs_product'))
        assert totals == {'once': 200.0, 'per_row': 300.0}

    def test_acres_once_per_record(self):
        for use in self.multi + [self.single]:
            PesticideUse.objects.filter(pk=use.pk).update(acres_treated=10)
        rollup.rebuild_year(2023)
        totals = self.rows().aggregate(once=Sum('acres_once'), per_row=Sum('acres_treated'))
        assert totals == {'once': 20.0, 'per_row': 30.0}
        row = PesticideUseTotal.objects.get(year=2023, county_id=9001, product=self.product)
        assert row.acres_once == 20.0
        assert PesticideSectionTotal.objects.get(year=2023, mtrs_id=9101).acres_once >= 20.0

    def test_each_chemical_keeps_its_own_application(self):
        assert self.rows().get(chemical=self.low).applications == 2
        assert self.rows().get(chemical=self.high).applications == 1

    def test_designated_row_is_the_lower_chemical_id_among_unflagged(self):
        assert self.rows().get(chemical=self.low).records == 2   # the multi record and the single one
        assert self.rows().get(chemical=self.high).records == 0
        assert self.rows().get(chemical=self.high).lbs_product_once == 0

    def test_flagged_ingredient_beats_a_lower_chemical_id(self):
        plain = Chemical.objects.create(chem_code=8003, name='PLAIN CHEM')
        flagged = Chemical.objects.create(
            chem_code=8004, name='FLAGGED CHEM', categories=[Chemical.Category.TOXIC_AIR_CONTAMINANT])
        restricted = Chemical.objects.create(
            chem_code=8005, name='RESTRICTED CHEM', categories=[Chemical.Category.CALIFORNIA_RESTRICTED])
        for chemical in (restricted, flagged, plain):
            self.use(use_no=7005, chemical=chemical)
        rollup.rebuild_year(2023)
        # Restricted first, then other chemicals of concern, then the rest.
        assert self.rows().get(chemical=restricted).records == 1
        assert self.rows().get(chemical=flagged).records == 0
        assert self.rows().get(chemical=plain).records == 0
        # Without the restricted one, the flagged one beats the lower id.
        self.use(use_no=7006, chemical=flagged)
        self.use(use_no=7006, chemical=plain)
        rollup.rebuild_year(2023)
        assert self.rows().get(chemical=flagged).records == 1
        assert self.rows().get(chemical=plain).records == 0

    def test_null_chemical_row_is_designated_last(self):
        self.use(use_no=7003, chemical=None)
        self.use(use_no=7003, chemical=self.high)
        rollup.rebuild_year(2023)
        assert self.rows().get(chemical=self.high).records == 1
        assert self.rows().get(chemical=None).records == 0

    def test_null_chemical_only_record_still_counts(self):
        self.use(use_no=7004, chemical=None)
        rollup.rebuild_year(2023)
        assert self.rows().get(chemical=None).records == 1

    def test_product_totals_carry_the_once_measures(self):
        row = PesticideUseTotal.objects.get(year=2023, county_id=9001, product=self.product)
        assert (row.records, row.lbs_product_once, row.lbs_product) == (2, 200.0, 300.0)

    def test_chemical_totals_sum_designated_rows(self):
        row = PesticideUseTotal.objects.get(year=2023, county_id=9001, chemical=self.low)
        assert (row.applications, row.records) == (2, 2)

    def test_section_totals_records_match_the_rollup(self):
        total = PesticideSectionTotal.objects.get(year=2023, mtrs_id=9101)
        expected = PesticideUseRollup.objects.filter(year=2023, mtrs_id=9101).aggregate(
            records=Sum('records'), once=Sum('lbs_product_once'),
        )
        assert (total.records, total.lbs_product_once) == (expected['records'], expected['once'])

    def test_rebuild_year_still_returns_rollup_rows_written(self):
        assert rollup.rebuild_year(2023) == PesticideUseRollup.objects.filter(year=2023).count()
