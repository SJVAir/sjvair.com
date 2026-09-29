"""
data/carbon-mapper-sources.csv is the header and the first eight data rows
of the real sources CSV for the Valley bbox, fetched 2026-09-29 (Task 2
Step 2). It pins the column names and value shapes; the match tests build
their own rows near the fixture's facilities and dairies with `row()`.
"""
import csv
import io
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from camp.apps.emissions import carbonmapper, dairies, methane
from camp.apps.emissions.models import Facility, MethaneSource, SourceImport
from camp.apps.emissions.tests.test_dairies import make_dairies
from camp.apps.regions.models import Region

SAMPLE = Path(__file__).parent / 'data' / 'carbon-mapper-sources.csv'

# TEST PLANT is at (-119.787, 36.737), BIG DAIRY at (-119.785, 36.735).
NEAR_BOTH = (-119.786, 36.736)          # ~130 m from each
JUST_INSIDE = (-119.785, 36.7435)       # 0.0085° north of BIG DAIRY: ~945 m
JUST_OUTSIDE = (-119.785, 36.7445)      # 0.0095° north: ~1,056 m
AT_GAS_STATION = (-119.018, 35.373)     # TEST GAS STATION (untrusted point); SMALL DAIRY is ~380 m away
OFFSHORE = (-121.0, 34.9)               # inside the bbox, outside every covered county


def row(name='CH4-test-1', lnglat=NEAR_BOTH, gas='CH4', sector='4B', rate='120.5', unc='40.2', **overrides):
    values = {
        'source_name': name, 'source_latitude': str(lnglat[1]), 'source_longitude': str(lnglat[0]), 'gas': gas,
        'observation_date_count': '12', 'detection_date_count': '5', 'source_persistence': '0.4167',
        'source_emission': rate, 'source_emission_uncertainty': unc, 'ipcc_sector': sector,
    }
    values.update(overrides)
    return values


def csv_text(rows):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(carbonmapper.COLUMNS))
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


class ParseTests(TestCase):
    def test_the_real_file(self):
        rows = carbonmapper.read_rows(SAMPLE.read_text())
        assert len(rows) == 8
        parsed = [carbonmapper.parse_row(r) for r in rows]
        assert all(p is not None for p in parsed)
        first = parsed[0]
        assert set(first) == {'source_name', 'gas', 'point', 'ipcc_sector', 'sector_label', 'persistence',
                              'emission_kg_h', 'uncertainty_kg_h', 'observations', 'detections'}
        assert first['point'].srid == 4326 and -122 < first['point'].x < -118 and 34 < first['point'].y < 39
        assert {p['gas'] for p in parsed} <= {'CH4', 'CO2'}
        assert all(isinstance(p['observations'], int) and p['observations'] >= p['detections'] for p in parsed)

    def test_parse_row_shapes(self):
        parsed = carbonmapper.parse_row(row())
        assert parsed['emission_kg_h'] == 120.5 and parsed['uncertainty_kg_h'] == 40.2
        assert (parsed['ipcc_sector'], parsed['sector_label']) == ('4B', 'Livestock')
        assert (parsed['observations'], parsed['detections']) == (12, 5)
        assert carbonmapper.parse_row(row(rate='', unc=''))['emission_kg_h'] is None
        assert carbonmapper.parse_row(row(name='')) is None
        assert carbonmapper.parse_row(row(source_latitude='x')) is None
        assert carbonmapper.parse_row(row(lnglat=(0, 0))) is None

    def test_a_wrong_header_is_an_error(self):
        with pytest.raises(carbonmapper.CarbonMapperError, match='source_emission'):
            carbonmapper.read_rows('source_name,gas\nCH4-1,CH4\n')

    def test_real_sector_label_format_extracts_the_code(self):
        # Carbon Mapper's ipcc_sector column reads "Livestock (4B)", not the bare code.
        parsed = carbonmapper.parse_row(row(sector='Solid Waste (6A)'))
        assert (parsed['ipcc_sector'], parsed['sector_label']) == ('6A', 'Solid waste')

    def test_uncoded_sectors_read_plainly(self):
        # Carbon Mapper also sends a bare 'Other' and 'NA' (not attributed), with no code.
        assert carbonmapper.parse_row(row(sector='Other'))['sector_label'] == 'Other'
        assert carbonmapper.parse_row(row(sector='NA'))['sector_label'] == 'Not attributed'


class ApplyTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.big, self.small, self.closed = make_dairies()
        self.plant = Facility.objects.get(name='TEST PLANT')
        self.plant.point_source = Facility.PointSource.CENSUS
        self.plant.save()

    def test_import_creates_links_and_records_the_licence(self):
        report = carbonmapper.apply([row()])
        source = MethaneSource.objects.get(source_name='CH4-test-1')
        assert source.county.slug == 'fresno'
        assert source.dairy == self.big and source.facility == self.plant
        assert 100 < source.distance_m < 200
        assert (report.created, report.dairy_matches, report.facility_matches) == (1, 1, 1)
        stamp = SourceImport.latest('carbon-mapper')
        assert stamp.notes['license'] == MethaneSource.LICENSE
        assert stamp.notes['attribution'] == MethaneSource.ATTRIBUTION
        assert stamp.notes['sources'] == 1

    def test_nearest_within_a_kilometre(self):
        # TEST PLANT (a trusted point) is ~744 m from JUST_INSIDE; untrust it so the dairy's distance is the one tested.
        Facility.objects.filter(name='TEST PLANT').update(point_source='')
        carbonmapper.apply([row(name='in', lnglat=JUST_INSIDE), row(name='out', lnglat=JUST_OUTSIDE)])
        inside, outside = MethaneSource.objects.get(source_name='in'), MethaneSource.objects.get(source_name='out')
        assert inside.dairy == self.big and 900 < inside.distance_m < 1000
        assert outside.dairy is None and outside.facility is None and outside.distance_m is None

    def test_an_untrusted_point_never_matches(self):
        # TEST GAS STATION has a point but point_source '' (untrusted): the source keeps the dairy only.
        carbonmapper.apply([row(name='gs', lnglat=AT_GAS_STATION, sector='1B2')])
        source = MethaneSource.objects.get(source_name='gs')
        assert source.facility is None and source.dairy == self.small and source.county.slug == 'kern'
        Facility.objects.filter(name='TEST GAS STATION').update(point_source=Facility.PointSource.CARB)
        carbonmapper.apply([row(name='gs', lnglat=AT_GAS_STATION, sector='1B2')])
        assert MethaneSource.objects.get(source_name='gs').facility.name == 'TEST GAS STATION'

    def test_clip_co2_and_duplicates(self):
        report = carbonmapper.apply([
            row(), row(name='co2', gas='CO2'), row(name='off', lnglat=OFFSHORE), row(name='CH4-test-1', rate='1'),
        ])
        assert MethaneSource.objects.count() == 1
        assert (report.fetched, report.co2, report.outside, report.skipped) == (4, 1, 1, 1)
        assert MethaneSource.objects.get().emission_kg_h == 120.5  # the first of a duplicated name wins

    def test_removed_sources_are_deleted_and_updates_land(self):
        carbonmapper.apply([row(name='a'), row(name='b', lnglat=JUST_INSIDE)])
        assert MethaneSource.objects.count() == 2
        report = carbonmapper.apply([row(name='a', rate='200', detection_date_count='7')])
        assert (report.updated, report.deleted) == (1, 1)
        a = MethaneSource.objects.get()
        assert a.source_name == 'a' and a.emission_kg_h == 200 and a.detections == 7

    def test_import_bumps_both_generations(self):
        before = (methane.generation(), dairies.generation())
        carbonmapper.apply([row()])
        assert methane.generation() == before[0] + 1 and dairies.generation() == before[1] + 1


class CommandTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        make_dairies()

    def test_fetches_and_reports(self):
        with patch('camp.apps.emissions.carbonmapper.fetch_csv', return_value=csv_text([row(), row(name='co2', gas='CO2')])):
            call_command('import_carbon_mapper')
        assert MethaneSource.objects.count() == 1

    def test_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'sources.csv')
            Path(path).write_text(csv_text([row(name='p')]))
            call_command('import_carbon_mapper', path=path)
        assert MethaneSource.objects.filter(source_name='p').exists()

    def test_an_empty_feed_changes_nothing(self):
        carbonmapper.apply([row()])
        with patch('camp.apps.emissions.carbonmapper.fetch_csv', return_value=csv_text([])):
            with pytest.raises(CommandError, match='no sources'):
                call_command('import_carbon_mapper')
        assert MethaneSource.objects.count() == 1
