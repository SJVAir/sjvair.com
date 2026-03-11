from django.test import TestCase

from camp.apps.ces.models import CES4, DACCategory


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
