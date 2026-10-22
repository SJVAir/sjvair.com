from datetime import date, datetime

from django.conf import settings
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.cache import cache
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from camp.api.v2.ces.filters import CES4Filter, CES5Filter
from camp.api.v2.hms.filters import FireFilter, SmokeFilter
from camp.api.v2.pesticides import sections
from camp.api.v2.pesticides.endpoints import PesticideRegionNotice
from camp.api.v2.pesticides.filters import PesticideNoticeFilter, PesticideUseFilter
from camp.api.v2.summaries.endpoints import BulkRegionSummaryList, RegionSummaryList
from camp.api.v2.summaries.tests import make_region_summary
from camp.api.v2.tempo.endpoints import TempoRegion
from camp.apps.accounts.models import User
from camp.apps.ces.models import CES4, CES5
from camp.apps.emissions.importers import mrr, nei
from camp.apps.emissions.views import AREA_PAGE_TYPES, get_filter_region, get_page_region
from camp.apps.hms.models import Fire, Smoke
from camp.apps.monitors.models import Monitor
from camp.apps.pesticides import views as pesticide_views
from camp.apps.pesticides.models import PesticideNotice, PesticideUse
from camp.apps.pesticides.views import resolve_related
from camp.apps.regions.models import Boundary, Region
from camp.apps.summaries.tasks import summarize_region_hour
from camp.apps.tempo.models import Granule
from camp.utils.test import get_response_data


class RegionRetirementTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        self.region = Region.objects.filter(type='county').first()

    def test_retired_hidden_from_objects_but_in_all_objects(self):
        self.region.retire(date(2026, 10, 1))
        assert not Region.objects.filter(pk=self.region.pk).exists()
        assert Region.all_objects.filter(pk=self.region.pk).exists()

    def test_default_and_base_managers_include_retired(self):
        self.region.retire(date(2026, 10, 1))
        assert Region._default_manager.filter(pk=self.region.pk).exists()
        assert Region._base_manager.filter(pk=self.region.pk).exists()

    def test_unretire(self):
        self.region.retire(date(2026, 10, 1))
        self.region.unretire()
        assert Region.objects.filter(pk=self.region.pk).exists()
        assert self.region.replaced_by is None

    def test_retire_records_replacement(self):
        other = Region.objects.filter(type='county').exclude(pk=self.region.pk).first()
        self.region.retire(date(2026, 10, 1), replaced_by=other)
        self.region.refresh_from_db()
        assert self.region.is_retired
        assert self.region.replaced_by == other
        assert list(other.replaces.all()) == [self.region]

    def test_import_updates_a_retired_row_without_duplicating(self):
        self.region.retire(date(2026, 10, 1))
        region, created = Region.objects.import_or_update(
            name='Renamed', slug='renamed', type=self.region.type, external_id=self.region.external_id,
            geometry=self.region.boundary.geometry, version=self.region.boundary.version)
        assert not created and region.pk == self.region.pk
        assert region.retired_at == date(2026, 10, 1)

    def test_import_never_changes_a_code(self):
        before = set(Region.all_objects.values_list('type', 'external_id'))
        r = self.region
        Region.objects.import_or_update(name=r.name, slug=r.slug, type=r.type, external_id=r.external_id,
            geometry=r.boundary.geometry, version=r.boundary.version)
        assert set(Region.all_objects.values_list('type', 'external_id')) == before


def make_region(name, type, external_id, bbox=(-119.8, 36.7, -119.7, 36.8)):
    region = Region.objects.create(name=name, slug=slugify(name), type=type, external_id=external_id)
    region.boundary = Boundary.objects.create(
        region=region, version='2020', geometry=MultiPolygon(Polygon.from_bbox(bbox), srid=4326))
    region.save(update_fields=['boundary'])
    return region


class RetiredRegionLookupTests(TestCase):
    """Anything that names a region by sqid or code finds it, retired or not."""
    fixtures = ['regions.yaml']

    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        self.region = Region.objects.get(name='Fresno County')
        self.region.retire(date(2026, 10, 1))

    def assert_filter_accepts(self, filter_class, queryset):
        qs = filter_class(data={'region_id': self.region.sqid}, queryset=queryset).qs
        assert not qs.query.is_empty()

    def test_ces_filters_accept_retired_region_id(self):
        self.assert_filter_accepts(CES4Filter, CES4.objects.all())
        self.assert_filter_accepts(CES5Filter, CES5.objects.all())

    def test_hms_filters_accept_retired_region_id(self):
        self.assert_filter_accepts(SmokeFilter, Smoke.objects.all())
        self.assert_filter_accepts(FireFilter, Fire.objects.all())

    def test_pesticides_filters_accept_retired_region_id(self):
        self.assert_filter_accepts(PesticideUseFilter, PesticideUse.objects.all())
        self.assert_filter_accepts(PesticideNoticeFilter, PesticideNotice.objects.all())

    def test_pesticides_region_endpoint_finds_retired_region(self):
        response = PesticideRegionNotice.as_view()(self.factory.get('/'), region_id=self.region.sqid)
        assert response.status_code == 200

    def test_pesticides_section_map_clip_finds_retired_region(self):
        shape, error = sections.clip_shape({'region': self.region.sqid})
        assert error is None and shape is not None

    def test_pesticides_section_detail_finds_retired_section(self):
        section = make_region('M-T14S-R20E-01', Region.Type.MTRS, 'M-T14S-R20E-01')
        section.retire(date(2026, 10, 1))
        response = sections.SectionDetail.as_view()(self.factory.get('/'), section_id=section.sqid)
        assert response.status_code == 200
        assert section in pesticide_views.SectionDetail().get_queryset()
        assert resolve_related({'section': section.sqid}, pesticide_views.RecordsBrowser.RELATED_MODELS)['section'] == section

    def test_pesticides_place_param_finds_retired_region(self):
        related = resolve_related({'region': self.region.sqid}, pesticide_views.NOTICE_RELATED_MODELS)
        assert related['region'] == self.region

    def test_region_summary_list_finds_retired_region(self):
        response = RegionSummaryList.as_view()(
            self.factory.get('/'), region_id=self.region.sqid, entry_type='pm25', resolution='hour')
        assert response.status_code == 200

    def test_bulk_region_summaries_accept_retired_region_id(self):
        make_region_summary(self.region, timezone.make_aware(datetime(2026, 1, 1)), resolution='day')
        response = BulkRegionSummaryList.as_view()(
            self.factory.get('/', {'region': self.region.sqid, 'start': '2026-01-01', 'end': '2026-01-31'}),
            entry_type='pm25', resolution='day')
        assert response.status_code == 200
        assert [r['id'] for r in get_response_data(response)['data']] == [self.region.sqid]

    def test_summary_task_runs_for_retired_region(self):
        summarize_region_hour.call_local(str(self.region.pk), timezone.make_aware(datetime(2026, 1, 1, 10)), 'pm25')

    def test_tempo_region_finds_retired_region(self):
        response = TempoRegion.as_view()(
            self.factory.get('/'), product=Granule.Product.values[0], region_id=self.region.sqid)
        assert response.status_code == 200

    def test_monitor_scope_accepts_retired_region_id(self):
        Monitor.objects.all().scope_to(region_ids=[self.region.sqid])

    def test_emissions_region_pages_find_retired_region(self):
        assert get_page_region(self.region.sqid) == self.region
        assert get_filter_region(self.region.sqid, types=AREA_PAGE_TYPES) == self.region

    def test_imports_find_retired_regions_by_code(self):
        zipcode = Region.objects.filter(type=Region.Type.ZIPCODE).first()
        zipcode.retire(date(2026, 10, 1))
        assert nei.county_fips()[self.region.external_id.zfill(5)] == self.region
        assert mrr.valley_zips()[zipcode.external_id] == zipcode


class RegionAdminRetirementTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        self.user = User.objects.create_superuser(
            email='admin@example.com', password='password', phone='+15595551234', full_name='Admin',
        )
        self.client.force_login(self.user)
        self.region = Region.objects.get(name='Fresno County')
        self.changelist = reverse('admin:regions_region_changelist')

    def test_admin_changelist_shows_retired(self):
        self.region.retire(date(2026, 10, 1))
        response = self.client.get(self.changelist)
        assert response.status_code == 200
        assert self.region in response.context['cl'].result_list

    def test_retired_list_filter(self):
        self.region.retire(date(2026, 10, 1))
        retired = self.client.get(self.changelist, {'retired': 'yes'}).context['cl'].result_list
        current = self.client.get(self.changelist, {'retired': 'no'}).context['cl'].result_list
        assert list(retired) == [self.region]
        assert self.region not in current

    def test_retire_today_and_unretire_actions(self):
        self.client.post(self.changelist, {'action': 'retire_today', '_selected_action': [self.region.pk]})
        self.region.refresh_from_db()
        assert self.region.retired_at == timezone.localdate(timezone=settings.DEFAULT_TIMEZONE)
        self.client.post(self.changelist, {'action': 'unretire', '_selected_action': [self.region.pk]})
        self.region.refresh_from_db()
        assert self.region.retired_at is None

    def test_change_form_edits_only_retirement_fields(self):
        other = Region.objects.get(name='Kern County')
        url = reverse('admin:regions_region_change', args=[self.region.pk])
        response = self.client.post(url, {
            'retired_at': '2026-10-01', 'replaced_by': other.pk, 'name': 'Renamed',
            'boundaries-TOTAL_FORMS': 0, 'boundaries-INITIAL_FORMS': 0,
        })
        assert response.status_code == 302, response.context['adminform'].form.errors
        self.region.refresh_from_db()
        assert self.region.retired_at == date(2026, 10, 1)
        assert self.region.replaced_by == other
        assert self.region.name == 'Fresno County'
