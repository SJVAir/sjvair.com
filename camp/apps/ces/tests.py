from django.test import TestCase

from camp.apps.ces.models import CES4, CES5, DACCategory


class CES4ModelTests(TestCase):
    fixtures = ['calenviroscreen']

    def get_tract(self, geoid, year):
        return CES4.objects.get(
            boundary__region__external_id=geoid,
            boundary__version=year,
        )

    def test_tract_property(self):
        record = self.get_tract('06019000101', '2020')
        assert record.tract == '06019000101'

    def test_census_year_property(self):
        record = self.get_tract('06019000101', '2020')
        assert record.census_year == '2020'

    def test_region_property(self):
        record = self.get_tract('06019000101', '2020')
        assert record.region.name == 'Census Tract 1.01'

    def test_str(self):
        record = self.get_tract('06019000101', '2020')
        assert 'CES4' in str(record)
        assert '06019000101' in str(record)
        assert '2020' in str(record)

    def test_dac_category_choices(self):
        record = self.get_tract('06019000101', '2020')
        assert record.dac_sb535 is True
        assert record.dac_category == DACCategory.TOP_CES_SCORE

    def test_non_dac_record(self):
        record = self.get_tract('06019000102', '2020')
        assert record.dac_sb535 is False
        assert record.dac_category is None

    def test_queryset_for_version(self):
        qs = CES4.objects.for_version('2020')
        assert qs.count() == 2
        assert all(r.census_year == '2020' for r in qs)

    def test_queryset_for_tract(self):
        qs = CES4.objects.for_tract('06019000101')
        assert qs.count() == 2  # one per vintage
        assert all(r.tract == '06019000101' for r in qs)

    def test_both_vintages_exist(self):
        for geoid in ('06019000101', '06019000102'):
            for year in ('2010', '2020'):
                assert CES4.objects.filter(
                    boundary__region__external_id=geoid,
                    boundary__version=year,
                ).exists()

    def test_sqid_is_a_nonempty_string(self):
        record = self.get_tract('06019000101', '2020')
        assert isinstance(record.sqid, str)
        assert record.sqid


class CES5ModelTests(TestCase):
    fixtures = ['calenviroscreen']

    def get_tract(self, geoid):
        return CES5.objects.get(boundary__region__external_id=geoid)

    def test_tract_property(self):
        record = self.get_tract('06019000101')
        assert record.tract == '06019000101'

    def test_census_year_property(self):
        record = self.get_tract('06019000101')
        assert record.census_year == '2020'

    def test_region_property(self):
        record = self.get_tract('06019000101')
        assert record.region.name == 'Census Tract 1.01'

    def test_region_name_field(self):
        record = self.get_tract('06019000101')
        assert record.region_name == 'San Joaquin Valley'

    def test_str(self):
        record = self.get_tract('06019000101')
        assert 'CES5' in str(record)
        assert '06019000101' in str(record)
        assert '2020' in str(record)

    def test_dac_category_choices(self):
        record = self.get_tract('06019000101')
        assert record.dac_sb535 is True
        assert record.dac_category == DACCategory.TOP_CES_SCORE

    def test_non_dac_record(self):
        record = self.get_tract('06019000102')
        assert record.dac_sb535 is False
        assert record.dac_category is None

    def test_only_one_vintage_exists(self):
        assert CES5.objects.for_tract('06019000101').count() == 1

    def test_new_indicators_present(self):
        record = self.get_tract('06019000101')
        assert record.pol_small_ats_p == 68.0
        assert record.char_diabetes_p == 77.0

    def test_demographic_percentages(self):
        record = self.get_tract('06019000101')
        assert record.pop_hispanic_pct == 60.2
        assert record.pop_asian_pct == 5.8
        assert record.pop_pacisl_pct == 0.4

    def test_sqid_is_a_nonempty_string(self):
        record = self.get_tract('06019000101')
        assert isinstance(record.sqid, str)
        assert record.sqid
