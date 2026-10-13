"""
data/carbon-mapper-sources.csv is the header and the first eight data rows
of the real sources CSV for the Valley bbox, fetched 2026-09-29 (Task 2
Step 2). It pins the column names and value shapes; the match tests build
their own rows near the fixture's facilities and dairies with `row()`.

data/carbon-mapper-plumes.json is a trimmed real page (4 items) of
/catalog/plumes/annotated for the same bbox, fetched the same day; its
image URLs are scrubbed to a placeholder (they're signed and expire in
~a day, so the real values are worthless -- and never worth committing).
data/sample-plume.png is one real plume PNG (115x115, ~2KB) saved from
that page, used to stand in for every downloaded image. The match/image
tests build their own items near the fixture's facilities and dairies
with `plume_item()`.
"""
import csv
import io
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from camp.apps.emissions import methane
from camp.apps.emissions.importers import carbonmapper
from camp.apps.emissions.models import Facility, MethanePlume, MethaneSource, SourceImport
from camp.apps.emissions.tests.test_dairies import make_dairies
from camp.apps.regions.models import Region

SAMPLE = Path(__file__).parent / 'data' / 'carbon-mapper-sources.csv'
SAMPLE_PLUMES = Path(__file__).parent / 'data' / 'carbon-mapper-plumes.json'
SAMPLE_PNG = (Path(__file__).parent / 'data' / 'sample-plume.png').read_bytes()

# TEST PLANT is at (-119.787, 36.737), BIG DAIRY at (-119.785, 36.735).
NEAR_BOTH = (-119.786, 36.736)          # ~130 m from each
JUST_INSIDE = (-119.785, 36.7435)       # 0.0085° north of BIG DAIRY: ~945 m
AT_GAS_STATION = (-119.018, 35.373)     # by TEST GAS STATION and SMALL DAIRY, in Kern
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


def plume_item(plume_id='tan-test-A', lnglat=NEAR_BOTH, gas='CH4', status='published', hidden=False,
                sector='4B', platform='Tanager', instrument='tan', scene_timestamp='2026-08-23T20:09:09.630Z',
                rate=120.5, unc=40.2, wind_speed=2.5, wind_dir=38.6, bounds=None, image_url=None, **overrides):
    """A plumes/annotated item shaped like the real API's PlumeAnnotatedOut, near a `row()` source by default."""
    lng, lat = lnglat
    if bounds is None:
        bounds = [lng - 0.01, lat - 0.01, lng + 0.01, lat + 0.01]
    if image_url is None:
        image_url = f'https://catalog.carbonmapper.org/sample/{plume_id}/plume.png?Expires=0&Signature=test'
    item = {
        'id': f'uuid-{plume_id}', 'plume_id': plume_id, 'gas': gas,
        'geometry_json': {'type': 'Point', 'coordinates': [lng, lat]},
        'scene_id': f'scene-{plume_id}', 'scene_timestamp': scene_timestamp,
        'instrument': instrument, 'platform': platform,
        'emission_auto': rate, 'emission_uncertainty_auto': unc,
        'plume_png': image_url,
        'plume_bounds': bounds,
        'wind_speed_avg_auto': wind_speed, 'wind_direction_avg_auto': wind_dir,
        'sector': sector, 'status': status, 'hide_emission': hidden,
        'published_at': '2026-09-22T20:19:17.504Z',
    }
    item.update(overrides)
    return item


class ParseTests(TestCase):
    def test_the_real_file(self):
        rows = carbonmapper.read_rows(SAMPLE.read_text())
        assert len(rows) == 8
        parsed = [carbonmapper.parse_row(r) for r in rows]
        assert all(p is not None for p in parsed)
        first = parsed[0]
        assert set(first) == {'source_name', 'gas', 'point', 'ipcc_sector', 'persistence',
                              'emission_kg_h', 'uncertainty_kg_h', 'observations', 'detections'}
        assert first['point'].srid == 4326 and -122 < first['point'].x < -118 and 34 < first['point'].y < 39
        assert {p['gas'] for p in parsed} <= {'CH4', 'CO2'}
        assert all(isinstance(p['observations'], int) and p['observations'] >= p['detections'] for p in parsed)

    def test_parse_row_shapes(self):
        parsed = carbonmapper.parse_row(row())
        assert parsed['emission_kg_h'] == 120.5 and parsed['uncertainty_kg_h'] == 40.2
        assert parsed['ipcc_sector'] == '4B' and MethaneSource(ipcc_sector='4B').sector_label == 'Dairies & livestock'
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
        assert parsed['ipcc_sector'] == '6A' and MethaneSource(ipcc_sector='6A').sector_label == 'Waste, water & recycling'

    def test_uncoded_sectors_read_plainly(self):
        # Carbon Mapper also sends a bare 'Other' and 'NA' (not attributed), with no code.
        assert carbonmapper.parse_row(row(sector='Other'))['ipcc_sector'] == 'OTHER'
        assert carbonmapper.parse_row(row(sector='NA'))['ipcc_sector'] == 'NA' and MethaneSource(ipcc_sector='NA').sector_label == 'Other'


class ParsePlumeTests(TestCase):
    def test_the_real_page(self):
        items = json.loads(SAMPLE_PLUMES.read_text())['items']
        assert len(items) == 4
        parsed = [carbonmapper.parse_plume(item) for item in items]
        assert all(p is not None for p in parsed)
        first = parsed[0]
        assert set(first) == {'plume_id', 'observed_at', 'platform', 'instrument', 'point', 'bounds',
                              'emission_kg_h', 'uncertainty_kg_h', 'wind_speed', 'wind_direction', '_image_url'}
        assert first['point'].srid == 4326 and -122 < first['point'].x < -118 and 34 < first['point'].y < 39
        assert first['bounds'].srid == 4326
        assert first['_image_url'].startswith('https://')

    def test_parse_plume_shapes(self):
        parsed = carbonmapper.parse_plume(plume_item())
        assert parsed['plume_id'] == 'tan-test-A'
        assert (parsed['emission_kg_h'], parsed['uncertainty_kg_h']) == (120.5, 40.2)
        assert (parsed['wind_speed'], parsed['wind_direction']) == (2.5, 38.6)
        assert parsed['point'].x == NEAR_BOTH[0] and parsed['point'].y == NEAR_BOTH[1]
        west, south, east, north = parsed['bounds'].extent
        expected = plume_item()['plume_bounds']
        assert [west, south, east, north] == pytest.approx(expected)
        assert parsed['observed_at'].year == 2026

    def test_skips_a_non_published_or_hidden_plume(self):
        assert carbonmapper.parse_plume(plume_item(status='valid')) is None
        assert carbonmapper.parse_plume(plume_item(status='publish_ready')) is None
        assert carbonmapper.parse_plume(plume_item(hidden=True)) is None

    def test_skips_wrong_gas_and_missing_fields(self):
        assert carbonmapper.parse_plume(plume_item(gas='CO2')) is None
        assert carbonmapper.parse_plume(plume_item(plume_id='')) is None
        assert carbonmapper.parse_plume(plume_item(bounds=[1, 2, 3])) is None
        assert carbonmapper.parse_plume(plume_item(scene_timestamp='')) is None
        item = plume_item()
        item['geometry_json'] = {'type': 'Point', 'coordinates': []}
        assert carbonmapper.parse_plume(item) is None


class ApplyTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.big, self.small, self.closed = make_dairies()
        self.plant = Facility.objects.get(name='TEST PLANT')
        self.plant.point_source = Facility.PointSource.CENSUS
        self.plant.save()

    def test_import_records_the_licence_and_links_nothing(self):
        report = carbonmapper.apply([row()])
        source = MethaneSource.objects.get(source_name='CH4-test-1')
        assert source.county.slug == 'fresno' and report.created == 1
        # Beside BIG DAIRY and TEST PLANT, but tied to neither: attributing a
        # source to an operator is for researchers, not a proximity guess.
        assert not hasattr(source, 'dairy') and not hasattr(source, 'facility')
        stamp = SourceImport.latest('carbon-mapper')
        assert stamp.notes['license'] == MethaneSource.LICENSE
        assert stamp.notes['attribution'] == MethaneSource.ATTRIBUTION
        assert stamp.notes['sources'] == 1 and 'dairy_matches' not in stamp.notes

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

    def test_import_bumps_the_methane_generation(self):
        before = methane.generation()
        carbonmapper.apply([row()])
        assert methane.generation() == before + 1


class CommandTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        make_dairies()

    def test_fetches_and_reports(self):
        with patch('camp.apps.emissions.importers.carbonmapper.fetch_csv', return_value=csv_text([row(), row(name='co2', gas='CO2')])):
            call_command('import_carbon_mapper', no_plumes=True)
        assert MethaneSource.objects.count() == 1

    def test_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'sources.csv')
            Path(path).write_text(csv_text([row(name='p')]))
            call_command('import_carbon_mapper', path=path, no_plumes=True)
        assert MethaneSource.objects.filter(source_name='p').exists()

    def test_an_empty_plume_feed_changes_nothing(self):
        with patch('camp.apps.emissions.importers.carbonmapper.fetch_csv', return_value=csv_text([row()])), \
                patch('camp.apps.emissions.importers.carbonmapper.fetch_all_plumes', return_value=[]), \
                patch('camp.apps.emissions.importers.carbonmapper.apply_plumes') as apply_plumes:
            with pytest.raises(CommandError, match='no plumes'):
                call_command('import_carbon_mapper')
        assert not apply_plumes.called

    def test_an_empty_feed_changes_nothing(self):
        carbonmapper.apply([row()])
        with patch('camp.apps.emissions.importers.carbonmapper.fetch_csv', return_value=csv_text([])):
            with pytest.raises(CommandError, match='no sources'):
                call_command('import_carbon_mapper', no_plumes=True)
        assert MethaneSource.objects.count() == 1

    def test_no_plumes_skips_the_plume_step(self):
        with patch('camp.apps.emissions.importers.carbonmapper.fetch_csv', return_value=csv_text([row()])), \
                patch('camp.apps.emissions.importers.carbonmapper.fetch_all_plumes') as fetch_plumes:
            call_command('import_carbon_mapper', no_plumes=True)
        fetch_plumes.assert_not_called()
        assert MethanePlume.objects.count() == 0

    def test_plumes_are_imported_after_sources(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root), \
                patch('camp.apps.emissions.importers.carbonmapper.fetch_csv', return_value=csv_text([row()])), \
                patch('camp.apps.emissions.importers.carbonmapper.fetch_all_plumes', return_value=[plume_item()]), \
                patch('camp.apps.emissions.importers.carbonmapper.fetch_plume_image', return_value=SAMPLE_PNG):
            call_command('import_carbon_mapper')
        assert MethaneSource.objects.count() == 1
        plume = MethanePlume.objects.get(plume_id='tan-test-A')
        assert plume.source == MethaneSource.objects.get()
        assert plume.image.name


class ApplyPlumesTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.tmp = tempfile.mkdtemp()
        self._media_root = override_settings(MEDIA_ROOT=self.tmp)
        self._media_root.enable()
        self.addCleanup(self._media_root.disable)
        fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        # Beside TEST PLANT (-119.787, 36.737); NEAR_BOTH is ~130m away.
        self.source = MethaneSource.objects.create(
            source_name='CH4_4B_1000m_-119.787_36.737', gas=MethaneSource.Gas.CH4,
            point=Point(-119.787, 36.737, srid=4326), ipcc_sector='4B', county=fresno,
        )

    def test_import_creates_links_and_fetches_the_image(self):
        with patch('camp.apps.emissions.importers.carbonmapper.fetch_plume_image', return_value=SAMPLE_PNG) as fetch_image:
            report = carbonmapper.apply_plumes([plume_item()])
        fetch_image.assert_called_once()
        plume = MethanePlume.objects.get(plume_id='tan-test-A')
        assert plume.source == self.source
        assert plume.image.name and plume.image.storage.exists(plume.image.name)
        assert plume.image.read() == SAMPLE_PNG
        assert (report.created, report.matched, report.images_fetched, report.images_failed) == (1, 1, 1, 0)

    def test_a_far_plume_is_unmatched(self):
        with patch('camp.apps.emissions.importers.carbonmapper.fetch_plume_image', return_value=SAMPLE_PNG):
            report = carbonmapper.apply_plumes([plume_item(plume_id='far', lnglat=OFFSHORE)])
        plume = MethanePlume.objects.get(plume_id='far')
        assert plume.source is None
        assert report.matched == 0

    def test_a_failed_image_download_is_counted_not_fatal(self):
        with patch('camp.apps.emissions.importers.carbonmapper.fetch_plume_image', return_value=None):
            report = carbonmapper.apply_plumes([plume_item()])
        plume = MethanePlume.objects.get(plume_id='tan-test-A')
        assert not plume.image
        assert (report.created, report.images_fetched, report.images_failed) == (1, 0, 1)

    def test_an_image_already_on_file_is_never_refetched(self):
        with patch('camp.apps.emissions.importers.carbonmapper.fetch_plume_image', return_value=SAMPLE_PNG) as fetch_image:
            carbonmapper.apply_plumes([plume_item()])
            assert fetch_image.call_count == 1
            report = carbonmapper.apply_plumes([plume_item(rate=999)])
            assert fetch_image.call_count == 1  # not called again
        plume = MethanePlume.objects.get(plume_id='tan-test-A')
        assert plume.emission_kg_h == 999
        assert report.updated == 1 and report.images_fetched == 0

    def test_hidden_and_unpublished_plumes_are_skipped(self):
        report = carbonmapper.apply_plumes([
            plume_item(plume_id='hidden', hidden=True), plume_item(plume_id='not-published', status='valid'),
        ])
        assert MethanePlume.objects.count() == 0
        assert (report.fetched, report.skipped) == (2, 2)

    def test_duplicate_plume_id_in_a_page_keeps_the_first(self):
        with patch('camp.apps.emissions.importers.carbonmapper.fetch_plume_image', return_value=SAMPLE_PNG):
            report = carbonmapper.apply_plumes([plume_item(rate=100), plume_item(rate=999)])
        assert MethanePlume.objects.count() == 1
        assert MethanePlume.objects.get().emission_kg_h == 100
        assert report.skipped == 1

    def test_removed_plumes_are_deleted_with_their_files(self):
        with patch('camp.apps.emissions.importers.carbonmapper.fetch_plume_image', return_value=SAMPLE_PNG):
            carbonmapper.apply_plumes([plume_item(plume_id='a'), plume_item(plume_id='b')])
        b = MethanePlume.objects.get(plume_id='b')
        image_name, storage = b.image.name, b.image.storage
        assert storage.exists(image_name)
        with patch('camp.apps.emissions.importers.carbonmapper.fetch_plume_image', return_value=SAMPLE_PNG):
            report = carbonmapper.apply_plumes([plume_item(plume_id='a')])
        assert report.deleted == 1
        assert not MethanePlume.objects.filter(plume_id='b').exists()
        assert not storage.exists(image_name)

    def test_a_partial_response_keeps_the_stored_plumes(self):
        with patch('camp.apps.emissions.importers.carbonmapper.fetch_plume_image', return_value=SAMPLE_PNG):
            carbonmapper.apply_plumes([plume_item(plume_id=p) for p in 'abcd'])
            report = carbonmapper.apply_plumes([plume_item(plume_id='a')])  # 1 of 4 back: not 3 withdrawals
        assert report.deleted == 0 and report.kept_stale == 3
        assert MethanePlume.objects.count() == 4
        assert 'Kept 3 stored plumes' in report.lines()[-1]


class FetchPlumesTests(TestCase):
    def test_pages_until_a_short_page(self):
        page1 = {'bbox_count': 3, 'items': [plume_item(plume_id='a'), plume_item(plume_id='b')]}
        page2 = {'bbox_count': 3, 'items': [plume_item(plume_id='c')]}
        with patch.object(carbonmapper, 'PLUME_PAGE_SIZE', 2), \
                patch('camp.apps.emissions.importers.carbonmapper.fetch_plumes_page', side_effect=[page1, page2]) as fetch_page:
            items = carbonmapper.fetch_all_plumes()
        assert [item['plume_id'] for item in items] == ['a', 'b', 'c']
        assert fetch_page.call_count == 2
        assert fetch_page.call_args_list[1].args == (2, 2)

    def test_a_missing_bbox_count_doesnt_stop_it_early(self):
        page1 = {'items': [plume_item(plume_id='a'), plume_item(plume_id='b')]}
        page2 = {'items': [plume_item(plume_id='c')]}
        with patch.object(carbonmapper, 'PLUME_PAGE_SIZE', 2), \
                patch('camp.apps.emissions.importers.carbonmapper.fetch_plumes_page', side_effect=[page1, page2]):
            items = carbonmapper.fetch_all_plumes()
        assert [item['plume_id'] for item in items] == ['a', 'b', 'c']

    def test_stops_on_an_empty_page(self):
        page1 = {'bbox_count': 10, 'items': [plume_item(plume_id='a')]}
        empty = {'bbox_count': 10, 'items': []}
        with patch.object(carbonmapper, 'PLUME_PAGE_SIZE', 1), \
                patch('camp.apps.emissions.importers.carbonmapper.fetch_plumes_page', side_effect=[page1, empty]):
            items = carbonmapper.fetch_all_plumes()
        assert [item['plume_id'] for item in items] == ['a']

    def test_fetch_plumes_page_sends_the_bearer_key_and_never_the_url_beyond_that(self):
        with patch('camp.apps.emissions.importers.carbonmapper.settings') as mock_settings, \
                patch('camp.apps.emissions.importers.carbonmapper.requests.get') as mock_get:
            mock_settings.CARBON_MAPPER_API_KEY = 'secret-key'
            mock_get.return_value.raise_for_status.return_value = None
            mock_get.return_value.json.return_value = {'items': [], 'bbox_count': 0}
            carbonmapper.fetch_plumes_page(10, 0)
        _args, kwargs = mock_get.call_args
        assert kwargs['headers']['Authorization'] == 'Bearer secret-key'
        assert kwargs['params']['status'] == 'published'


class FetchPlumeImageTests(TestCase):
    def test_returns_the_bytes(self):
        session = type('S', (), {})()
        response = type('R', (), {'content': SAMPLE_PNG, 'raise_for_status': lambda self: None})()
        session.get = lambda *a, **k: response
        assert carbonmapper.fetch_plume_image('https://example.com/x.png', session=session) == SAMPLE_PNG

    def test_a_request_failure_returns_none_not_an_exception(self):
        import requests

        class FailingSession:
            def get(self, *a, **k):
                raise requests.RequestException('boom')

        assert carbonmapper.fetch_plume_image('https://example.com/x.png', session=FailingSession()) is None
