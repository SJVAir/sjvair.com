from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.gis.geos import Point
from django.test import TestCase
from django.utils import timezone

from decimal import Decimal
from unittest.mock import patch

from camp.apps.entries import models as entry_models
from camp.apps.monitors.models import LatestEntry, Monitor
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.regions.counties import county_name
from camp.utils.datetime import make_aware


class MonitorTests(TestCase):
    fixtures = ['purple-air.yaml']

    def get_purpleair(self):
        return PurpleAir.objects.get(sensor_id=8892)

    def test_get_initial_stage_falls_back_to_raw_when_allowed_stages_missing(self):
        # ENTRY_CONFIG exists for PM25 but has no 'allowed_stages' key
        monitor = self.get_purpleair()
        config_without_stages = {entry_models.PM25: {}}
        with patch.object(type(monitor), 'ENTRY_CONFIG', config_without_stages):
            stage = monitor.get_initial_stage(entry_models.PM25)
        assert stage == entry_models.PM25.Stage.RAW

    def test_get_initial_stage_falls_back_to_raw_when_entry_not_in_config(self):
        # EntryModel is not in ENTRY_CONFIG at all
        monitor = self.get_purpleair()
        with patch.object(type(monitor), 'ENTRY_CONFIG', {}):
            stage = monitor.get_initial_stage(entry_models.PM25)
        assert stage == entry_models.PM25.Stage.RAW

    def test_get_latest_data_returns_entry_data(self):
        monitor = self.get_purpleair()

        entry = entry_models.PM25.objects.create(
            monitor_id=monitor.pk,
            timestamp='2025-04-27T00:00:00Z',
            sensor='a',
            location='outside',
            stage=entry_models.PM25.Stage.CLEANED,
            value=Decimal('12.34'),
        )
        monitor.update_latest_entry(entry)

        data = monitor.get_latest_data()

        assert 'pm25' in data
        assert data['pm25']['value'] == entry.value
        assert data['pm25']['sensor'] == entry.sensor
        assert data['pm25']['stage'] == entry.stage
        assert data['pm25']['processor'] == entry.processor

    def test_latest_entry_entry_property_and_setter(self):
        monitor = self.get_purpleair()

        # Create a fake PM2.5 entry
        entry = entry_models.PM25.objects.create(
            monitor_id=monitor.pk,
            timestamp='2025-04-27T00:00:00Z',
            sensor='a',
            location='outside',
            stage=entry_models.PM25.Stage.CLEANED,
            processor='PM25_Cleaner',
            value=12.34,
        )

        # Create a LatestEntry and assign the entry
        latest = LatestEntry(monitor_id=entry.monitor_id)
        latest.entry = entry  # triggers the setter

        # Check that fields synced properly
        assert latest.entry_type == entry.entry_type
        assert latest.entry_id == entry.pk
        assert latest.stage == entry.stage
        assert latest.processor == entry.processor
        assert latest.timestamp == entry.timestamp

        # Check that the getter returns the same object without re-query
        assert latest.entry.pk == entry.pk
        assert latest.entry is latest._entry  # cached!

    def test_filter_healthy_as_of_excludes_future_health_checks(self):
        from camp.apps.qaqc.models import HealthCheck

        monitor = self.get_purpleair()
        as_of = make_aware(datetime(2026, 1, 1, 12, 0))

        # A passing HealthCheck *before* as_of should count...
        HealthCheck.objects.create(monitor=monitor, hour=as_of - timedelta(hours=1), score=3)
        # ...but one *after* as_of must not count toward the as_of query.
        HealthCheck.objects.create(monitor=monitor, hour=as_of + timedelta(hours=1), score=3)

        # threshold=1.0 over 1 hour requires exactly 1 passing check in-window.
        # (filter_healthy/select_health live on MonitorQuerySet, not the manager,
        # so go through get_queryset() the same way MonitorManager.get_active does.)
        healthy_ids = set(Monitor.objects.get_queryset().filter_healthy(
            hours=1, min_score=1, threshold=1.0, as_of=as_of,
        ).values_list('pk', flat=True))

        assert monitor.pk in healthy_ids

        # Now push as_of back before either HealthCheck exists — should be excluded.
        earlier = as_of - timedelta(hours=3)
        healthy_ids = set(Monitor.objects.get_queryset().filter_healthy(
            hours=1, min_score=1, threshold=1.0, as_of=earlier,
        ).values_list('pk', flat=True))

        assert monitor.pk not in healthy_ids

    def _make_region_with_boundary(self, bbox, name='Test Region'):
        from django.contrib.gis.geos import MultiPolygon, Polygon
        from camp.apps.regions.models import Boundary, Region

        region = Region.objects.create(name=name, slug=name.lower().replace(' ', '-'), type=Region.Type.CUSTOM)
        boundary = Boundary.objects.create(
            region=region,
            version='test',
            geometry=MultiPolygon(Polygon.from_bbox(bbox)),
        )
        region.boundary = boundary
        region.save()
        return region

    def test_in_regions_filters_by_covering_boundary(self):
        monitor = self.get_purpleair()
        lon, lat = monitor.position.x, monitor.position.y

        containing = self._make_region_with_boundary(
            (lon - 0.01, lat - 0.01, lon + 0.01, lat + 0.01), name='Containing'
        )
        excluding = self._make_region_with_boundary(
            (lon + 10, lat + 10, lon + 11, lat + 11), name='Excluding'
        )

        assert monitor.pk in set(Monitor.objects.in_regions([containing]).values_list('pk', flat=True))
        assert monitor.pk not in set(Monitor.objects.in_regions([excluding]).values_list('pk', flat=True))
        # Union: covered by *any* of the given regions.
        assert monitor.pk in set(Monitor.objects.in_regions([excluding, containing]).values_list('pk', flat=True))

    def test_in_bbox_filters_by_bounding_box(self):
        monitor = self.get_purpleair()
        lon, lat = monitor.position.x, monitor.position.y

        assert monitor.pk in set(Monitor.objects.in_bbox(lon - 0.01, lat - 0.01, lon + 0.01, lat + 0.01).values_list('pk', flat=True))
        assert monitor.pk not in set(Monitor.objects.in_bbox(lon + 10, lat + 10, lon + 11, lat + 11).values_list('pk', flat=True))

    def test_with_entry_as_of_returns_the_entry_current_at_that_time(self):
        monitor = self.get_purpleair()
        as_of = make_aware(datetime(2026, 1, 1, 12, 0))
        stage = monitor.get_default_stage(entry_models.PM25)

        entry_models.PM25.objects.create(
            monitor_id=monitor.pk, timestamp=as_of - timedelta(minutes=20),
            sensor='a', stage=stage, value=Decimal('9.0'),
        )
        current = entry_models.PM25.objects.create(
            monitor_id=monitor.pk, timestamp=as_of - timedelta(minutes=5),
            sensor='a', stage=stage, value=Decimal('11.0'),
        )
        # An entry *after* as_of must not be picked.
        entry_models.PM25.objects.create(
            monitor_id=monitor.pk, timestamp=as_of + timedelta(minutes=5),
            sensor='a', stage=stage, value=Decimal('99.0'),
        )

        results = Monitor.objects.filter(pk=monitor.pk).with_entry_as_of(entry_models.PM25, as_of)

        assert len(results) == 1
        assert results[0].latest_pm25.pk == current.pk
        assert results[0].latest_entry.pk == current.pk

    def test_with_entry_as_of_drops_monitors_with_no_qualifying_entry(self):
        monitor = self.get_purpleair()
        as_of = make_aware(datetime(2026, 1, 1, 12, 0))

        # Only an entry far outside the active window before as_of.
        stage = monitor.get_default_stage(entry_models.PM25)
        entry_models.PM25.objects.create(
            monitor_id=monitor.pk, timestamp=as_of - timedelta(days=10),
            sensor='a', stage=stage, value=Decimal('9.0'),
        )

        results = Monitor.objects.filter(pk=monitor.pk).with_entry_as_of(
            entry_models.PM25, as_of, seconds=3600,
        )
        assert results == []


class CreateEntryUpsertTests(TestCase):
    """
    create_entry() upserts unconditionally on a duplicate key -- no
    opt-in flag. A no-op case costs one extra lookup query; there's no
    integration where silently discarding a changed value is desired
    (see the survey behind this decision: forward-only-cursor
    integrations rarely hit duplicates at all, and CIMIS/VOZBox actively
    need corrections applied).
    """
    fixtures = ['purple-air.yaml']

    def get_purpleair(self):
        return PurpleAir.objects.get(sensor_id=8892)

    def test_creates_when_missing(self):
        monitor = self.get_purpleair()
        entry = monitor.create_entry(
            entry_models.PM25, timestamp='2025-04-27T00:00:00Z',
            sensor='a', stage=entry_models.PM25.Stage.RAW,
            value=Decimal('12.0'),
        )
        assert entry is not None
        assert entry.value == Decimal('12.0')

    def test_updates_changed_value_on_existing_entry(self):
        monitor = self.get_purpleair()
        original = monitor.create_entry(
            entry_models.PM25, timestamp='2025-04-27T00:00:00Z',
            sensor='a', stage=entry_models.PM25.Stage.RAW,
            value=Decimal('12.0'),
        )

        updated = monitor.create_entry(
            entry_models.PM25, timestamp='2025-04-27T00:00:00Z',
            sensor='a', stage=entry_models.PM25.Stage.RAW,
            value=Decimal('99.0'),
        )

        assert updated is not None
        assert updated.pk == original.pk
        assert entry_models.PM25.objects.filter(monitor=monitor).count() == 1
        original.refresh_from_db()
        assert original.value == Decimal('99.0')

    def test_returns_none_when_existing_value_unchanged(self):
        monitor = self.get_purpleair()
        monitor.create_entry(
            entry_models.PM25, timestamp='2025-04-27T00:00:00Z',
            sensor='a', stage=entry_models.PM25.Stage.RAW,
            value=Decimal('12.0'),
        )

        result = monitor.create_entry(
            entry_models.PM25, timestamp='2025-04-27T00:00:00Z',
            sensor='a', stage=entry_models.PM25.Stage.RAW,
            value=Decimal('12.0'),
        )

        assert result is None
        assert entry_models.PM25.objects.filter(monitor=monitor).count() == 1


class MonitorSaveCountyLookupTests(TestCase):
    """Monitor.county is derived from the position; nothing else writes it."""

    fixtures = ['purple-air.yaml', 'regions.yaml']

    FRESNO = Point(-119.7871, 36.7378, srid=4326)
    KERN = Point(-118.7273, 35.3733, srid=4326)

    def get_purpleair(self):
        return PurpleAir.objects.get(sensor_id=8892)

    def test_county_is_looked_up_on_create(self):
        monitor = PurpleAir.objects.create(name='New', sensor_id=424242, position=self.FRESNO, location='outside')
        assert monitor.county == 'Fresno'

    def test_county_given_on_create_is_replaced_by_the_lookup(self):
        monitor = PurpleAir.objects.create(name='New', sensor_id=424242, position=self.FRESNO, location='outside', county='Kern')
        assert monitor.county == 'Fresno'

    def test_create_with_explicit_pk_still_looks_up(self):
        # update_or_create-style creation passes the pk, which snapshots the
        # tracker at init; the lookup must not depend on it.
        monitor = PurpleAir(id='TZi2R3xSQvOKyqXJqZ4tzw', name='New', sensor_id=424242, position=self.KERN, location='outside', county='Fresno')
        monitor.save()
        assert monitor.county == 'Kern'

    def test_create_without_position_has_no_county(self):
        with patch('camp.apps.monitors.models.county_name', wraps=county_name) as lookup:
            monitor = PurpleAir.objects.create(name='New', sensor_id=424242, location='outside', county='Fresno')
        assert monitor.county == ''
        lookup.assert_called_once_with(None)

    def test_skips_lookup_when_position_unchanged(self):
        monitor = self.get_purpleair()
        monitor.position = self.FRESNO
        monitor.save()

        monitor = self.get_purpleair()
        monitor.county = ''  # even a blank county is left alone
        with patch('camp.apps.monitors.models.county_name') as lookup:
            monitor.name = 'Renamed'
            monitor.save()

        lookup.assert_not_called()

    def test_recomputes_when_position_changes(self):
        monitor = self.get_purpleair()
        monitor.position = self.FRESNO
        monitor.save()
        assert monitor.county == 'Fresno'

        monitor = self.get_purpleair()
        monitor.position = self.KERN
        monitor.save()
        assert monitor.county == 'Kern'

    def test_clears_county_when_position_is_removed(self):
        monitor = self.get_purpleair()
        monitor.position = self.FRESNO
        monitor.save()

        monitor = self.get_purpleair()
        monitor.position = None
        monitor.save()
        assert monitor.county == ''
