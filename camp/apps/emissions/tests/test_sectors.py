from io import StringIO

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

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


class OilGasMethaneListTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        from camp.apps.emissions.importers import carbonmapper
        from camp.apps.emissions.tests.test_carbonmapper import AT_GAS_STATION, row
        from camp.apps.emissions.tests.test_dairies import make_dairies
        cache.clear()
        make_dairies()
        Facility.objects.filter(name='TEST GAS STATION').update(point_source=Facility.PointSource.CARB, sector=Facility.Sector.OIL_GAS)
        carbonmapper.apply([row(name='og', lnglat=AT_GAS_STATION, sector='1B2', rate='500', unc='150')])

    def test_the_oil_gas_tab_lists_sources(self):
        # The list moved from the sector page to the top-level Oil & gas tab.
        from camp.apps.emissions.tests.test_wells import make_well
        from camp.apps.regions.models import Region
        make_well('0402900001', (-119.02, 35.37), Region.objects.get(type=Region.Type.COUNTY, slug='kern'))
        content = self.client.get(reverse('emissions:oil-gas')).content.decode()
        assert 'Methane sources observed at oil &amp; gas sites' in content
        listing = content[content.index('id="methane"'):]
        listing = listing[:listing.index('</table>')]
        assert '500 ± 150 kg/h' in listing and 'Kern' in listing
        # Shown by its own location, not tied to the station beside it.
        assert '35.3730, -119.0180' in listing and 'TEST GAS STATION' not in listing
        assert 'Methane sources observed' not in self.client.get(reverse('emissions:sector-detail', args=['oil-gas'])).content.decode()
