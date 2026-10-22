from datetime import date

from django.test import TestCase

from camp.apps.regions.models import Region


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
