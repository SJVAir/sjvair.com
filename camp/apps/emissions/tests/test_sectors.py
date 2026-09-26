from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from camp.apps.emissions import sectors
from camp.apps.emissions.models import Facility

S = Facility.Sector


class SectorForSicTests(TestCase):
    def test_every_sector_but_other_has_codes_and_a_description(self):
        listed = [sector for sector, codes, description in sectors.SECTORS]
        assert set(listed) == set(S) - {S.OTHER}
        for sector, codes, description in sectors.SECTORS:
            assert codes
            assert description
        assert sectors.sector_description(S.OTHER)

    def test_specific_sectors_win_over_the_ranges_that_contain_them(self):
        expected = {
            3221: S.GLASS, 3211: S.GLASS,
            3241: S.CEMENT_MINERALS, 3273: S.CEMENT_MINERALS, 3296: S.CEMENT_MINERALS,
            2084: S.WINERIES_BEVERAGES,
            2034: S.FOOD_PROCESSING, 2048: S.FOOD_PROCESSING,
            2911: S.REFINING_FUELS, 2951: S.REFINING_FUELS, 4612: S.REFINING_FUELS, 5171: S.REFINING_FUELS,
            723: S.CROP_PROCESSING, 724: S.CROP_PROCESSING,
            241: S.DAIRIES_LIVESTOCK, 211: S.DAIRIES_LIVESTOCK,
            173: S.FARMS,
            1311: S.OIL_GAS, 1389: S.OIL_GAS,
            1474: S.MINING, 1442: S.MINING,
            2875: S.CHEMICALS,
            4911: S.POWER_PLANTS, 4931: S.POWER_PLANTS,
            4953: S.WASTE_WATER, 4941: S.WASTE_WATER, 9511: S.WASTE_WATER,
            4812: S.TELECOM,
            4225: S.TRANSPORTATION,
            5541: S.GAS_STATIONS, 7532: S.AUTO_REPAIR, 7538: S.AUTO_REPAIR, 7216: S.DRY_CLEANERS,
            2711: S.MANUFACTURING, 3479: S.MANUFACTURING,
            8062: S.HOSPITALS_SCHOOLS, 8211: S.HOSPITALS_SCHOOLS,
            9711: S.GOVERNMENT_MILITARY, 9199: S.GOVERNMENT_MILITARY,
            5812: S.COMMERCIAL, 5411: S.COMMERCIAL,
            1521: S.OTHER,
            None: S.OTHER,
        }
        for sic, sector in expected.items():
            assert sectors.sector_for_sic(sic) == sector, sic


class SicTitleTests(TestCase):
    def test_titles(self):
        assert sectors.sic_title(3221) == 'Glass Containers'
        assert sectors.sic_title(723) == 'Crop Preparation Services for Market, Except Cotton Ginning'
        assert sectors.sic_title(1) is None
        assert sectors.sic_title(None) is None


class AssignSectorsTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def test_fixes_only_mismatched_rows(self):
        Facility.objects.filter(name='TEST PLANT').update(sector=S.OTHER)
        out = StringIO()
        call_command('assign_sectors', stdout=out)
        assert Facility.objects.get(name='TEST PLANT').sector == S.GLASS
        assert Facility.objects.get(name='TEST CEMENT').sector == S.CEMENT_MINERALS
        assert '1 facilities updated' in out.getvalue()
