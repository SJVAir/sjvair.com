import json

from pathlib import Path
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import TestCase

from camp.apps.regions import ab617
from camp.apps.regions.models import Boundary, Region

DATA_DIR = Path(__file__).parent / 'data'
SAMPLE_PATH = DATA_DIR / 'ab617-sample.geojson'


def load_sample_features():
    return json.loads(SAMPLE_PATH.read_text())['features']


def feature(bndryid, shortn, community, county, boundary_type, status='Final'):
    """A minimal synthetic feature, for cases the checked-in sample doesn't cover."""
    return {
        'type': 'Feature',
        'properties': {
            'BNDRYID': bndryid,
            'SHORTN': shortn,
            'BNDRYSTATDESC': status,
            'BNDRYTYPE': boundary_type,
            'COMMUNITY': community,
            'COUNTY': county,
            'AIR_DISTRICT': 'San Joaquin Valley Air Pollution Control District',
            'CERPSLCTDYR': '2020',
            'CAMPSLCTDYR': '2020',
            'DIS_OCAP_WEB': 'https://community.valleyair.org/selected-communities/example',
            'STORYMAPS': None,
        },
        'geometry': {
            'type': 'Polygon',
            'coordinates': [[[-119.5, 36.5], [-119.4, 36.5], [-119.4, 36.6], [-119.5, 36.6], [-119.5, 36.5]]],
        },
    }


def response(features):
    mock = MagicMock()
    mock.json.return_value = {'type': 'FeatureCollection', 'features': features}
    mock.raise_for_status.return_value = None
    return mock


class GroupByCommunityTests(TestCase):
    def test_buckets_rows_by_shortn_and_boundary_type(self):
        grouped = ab617.group_by_community(load_sample_features())

        assert set(grouped) == {'SCFR', 'SHFT', 'STCK', 'AL', 'WOAK'}
        assert set(grouped['SHFT']['boundaries']) == {
            ab617.COMMUNITY_BOUNDARY, ab617.EMISSION_STUDY_BOUNDARY,
        }
        assert set(grouped['SCFR']['boundaries']) == {ab617.COMBINED_BOUNDARY}

    def test_skips_non_final_rows(self):
        features = [feature('DRAFT1', 'DRFT', 'Draft Community', 'Fresno',
            ab617.COMMUNITY_BOUNDARY, status='Proposed')]
        grouped = ab617.group_by_community(features)
        assert grouped == {}


class PrimaryBoundaryTypeTests(TestCase):
    def test_prefers_community_boundary_over_combined(self):
        boundaries = {ab617.COMMUNITY_BOUNDARY: {}, ab617.EMISSION_STUDY_BOUNDARY: {}}
        assert ab617.primary_boundary_type(boundaries) == ab617.COMMUNITY_BOUNDARY

    def test_falls_back_to_combined(self):
        assert ab617.primary_boundary_type({ab617.COMBINED_BOUNDARY: {}}) == ab617.COMBINED_BOUNDARY

    def test_emission_study_alone_has_no_primary(self):
        assert ab617.primary_boundary_type({ab617.EMISSION_STUDY_BOUNDARY: {}}) is None


class ImportAB617CommunitiesTests(TestCase):
    def run_import(self, features=None):
        features = load_sample_features() if features is None else features
        with patch('camp.apps.regions.ab617.requests.get', return_value=response(features)):
            call_command('import_ab617_communities')

    def test_imports_only_communities_in_covered_counties(self):
        self.run_import()
        codes = set(Region.objects.filter(type=Region.Type.AB617_COMMUNITY).values_list('external_id', flat=True))
        assert codes == {'SCFR', 'SHFT', 'STCK', 'AL'}
        assert not Region.objects.filter(external_id='WOAK').exists()

    def test_combined_boundary_community_gets_a_single_boundary(self):
        self.run_import()
        region = Region.objects.get(type=Region.Type.AB617_COMMUNITY, external_id='SCFR')
        assert region.name == 'South Central Fresno'
        assert region.slug == 'south-central-fresno'
        assert region.boundary is not None
        assert region.boundary.version == 'combined'
        assert region.boundaries.count() == 1

    def test_shafter_keeps_both_boundaries_with_community_as_current(self):
        self.run_import()
        region = Region.objects.get(type=Region.Type.AB617_COMMUNITY, external_id='SHFT')

        assert region.boundaries.count() == 2
        assert region.boundary.version == 'community'
        assert region.boundary.metadata['boundary_type'] == ab617.COMMUNITY_BOUNDARY

        emission_study = region.boundaries.get(version='emission_study_area')
        assert emission_study.metadata['boundary_type'] == ab617.EMISSION_STUDY_BOUNDARY
        # The Emission Study Area is the larger of the two.
        assert emission_study.geometry.area > region.boundary.geometry.area

    def test_metadata_carries_community_url_and_selection_years(self):
        self.run_import()
        region = Region.objects.get(type=Region.Type.AB617_COMMUNITY, external_id='AL')
        assert region.name == 'Arvin, Lamont'
        assert region.slug == 'arvin-lamont'
        assert region.metadata['community_url'] == 'https://community.valleyair.org/selected-communities/arvin-lamont'
        assert region.metadata['cerp_selected_year'] == '2020'
        assert region.metadata['camp_selected_year'] == '2020'
        assert region.metadata['boundary_type'] == ab617.COMBINED_BOUNDARY
        assert region.metadata['county'] == 'Kern'

    def test_rerun_is_idempotent(self):
        self.run_import()
        self.run_import()

        assert Region.objects.filter(type=Region.Type.AB617_COMMUNITY).count() == 4
        shafter = Region.objects.get(type=Region.Type.AB617_COMMUNITY, external_id='SHFT')
        assert shafter.boundaries.count() == 2
        assert Boundary.objects.filter(region=shafter).count() == 2

    def test_community_with_only_an_emission_study_row_is_skipped(self):
        features = [feature('EMONLY1', 'EMON', 'Emission Only', 'Fresno', ab617.EMISSION_STUDY_BOUNDARY)]
        self.run_import(features)
        assert not Region.objects.filter(external_id='EMON').exists()
