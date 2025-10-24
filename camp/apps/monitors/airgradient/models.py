import html

import requests

from django.contrib.gis.db import models
from django.contrib.gis.geos import Point
from django.utils.functional import cached_property

from django_smalluuid.models import SmallUUIDField, uuid_default
from model_utils.models import TimeStampedModel

from camp.apps.calibrations import processors
from camp.apps.entries import models as entry_models
from camp.apps.monitors.models import Monitor, LCSMixin
from camp.apps.monitors.airgradient.api import AirGradientAPI
from camp.utils.datetime import parse_timestamp
from camp.utils.fields import MACAddressField


class Place(TimeStampedModel):
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )

    name = models.CharField(max_length=100, blank=True)
    url = models.URLField(max_length=100, blank=True)
    token = models.CharField(max_length=255, unique=True)
    is_enabled = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    @cached_property
    def api(self):
        return AirGradientAPI(token=self.token)


class AirGradient(LCSMixin, Monitor):
    DATA_PROVIDERS = [{
        'name': 'AirGradient',
        'url': 'https://www.airgradient.com/'
    }]

    DATA_SOURCE = {
        'name': 'AirGradient',
        'url': 'https://www.airgradient.com/'
    }

    EXPECTED_INTERVAL = '1 min'
    ENTRY_CONFIG = {
        entry_models.PM10: {
            'sensors': ['1', '2'],
            'fields': {'value': 'pm01'},
            'allowed_stages': [entry_models.PM10.Stage.RAW],
            'default_stage': entry_models.PM10.Stage.RAW,
        },
        entry_models.PM25: {
            'sensors': ['1', '2'],
            'fields': {'value': 'pm02'},
            'allowed_stages': [
                entry_models.PM25.Stage.RAW,
                entry_models.PM25.Stage.CORRECTED,
                entry_models.PM25.Stage.CLEANED,
                entry_models.PM25.Stage.CALIBRATED,
            ],
            'default_stage': entry_models.PM25.Stage.CLEANED,
            'processors': {
                entry_models.PM25.Stage.RAW: [processors.PM25_LCS_Correction],
                entry_models.PM25.Stage.CORRECTED: [processors.PM25_LCS_Cleaning],
                entry_models.PM25.Stage.CLEANED: [
                    processors.PM25_UnivariateLinearRegression,
                    processors.PM25_MultivariateLinearRegression,
                    processors.PM25_EPA_Oct2021,
                ],
            },
            'alerts': {
                'stage': entry_models.PM25.Stage.CALIBRATED,
                'processor': processors.PM25_UnivariateLinearRegression,
            }
        },
        entry_models.PM100: {
            'sensors': ['1', '2'],
            'fields': {'value': 'pm10'},
            'allowed_stages': [entry_models.PM100.Stage.RAW],
            'default_stage': entry_models.PM100.Stage.RAW,
        },
        entry_models.Particulates: {
            'sensors': ['1', '2'],
            'fields': {
                'particles_03um': 'pm003Count',
            },
            'allowed_stages': [entry_models.Particulates.Stage.RAW],
            'default_stage': entry_models.Particulates.Stage.RAW,
        },
        entry_models.Temperature: {
            'sensors': ['1', '2'],
            'fields': {'celsius': 'atmp'},
            'allowed_stages': [
                entry_models.Temperature.Stage.RAW,
                entry_models.Temperature.Stage.CALIBRATED
            ],
            'processors': {
                entry_models.Temperature.Stage.RAW: [processors.AirGradientTemperature],
            },
            'default_stage': entry_models.Temperature.Stage.RAW,
        },
        entry_models.Humidity: {
            'sensors': ['1', '2'],
            'fields': {'value': 'rhum'},
            'allowed_stages': [
                entry_models.Humidity.Stage.RAW,
                entry_models.Humidity.Stage.CALIBRATED
            ],
            'processors': {
                entry_models.Humidity.Stage.RAW: [processors.AirGradientHumidity],
            },
            'default_stage': entry_models.Humidity.Stage.RAW,
        },
    }

    place = models.ForeignKey('airgradient.Place',
        related_name='monitors',
        blank=True,
        null=True,
        on_delete=models.SET_NULL
    )

    class Meta:
        verbose_name = 'AirGradient'

    @property
    def is_dual_channel(self):
        return self.device == 'O-1PP'

    @property
    def data_providers(self):
        providers = super().data_providers
        if self.place:
            providers.append({
                'name': self.place.name,
                'url': self.place.url
            })
        return providers

    def get_probable_location(self):
        # If the name says it's inside, it probably is
        name = self.name.lower()
        inside_keywords = (
            'inside', 'indoor', 'in door', 'in-door',
            'classroom', 'lab', 'library', 'office', 'conf room',
            'meeting room', 'admin', 'nurse', 'staff', 'hallway',
            'gym', 'cafeteria', 'kitchen', 'reception', 'main building'
        )
        if any(item in name for item in inside_keywords):
            return self.LOCATION.inside

        # If it's an outdoor device, assume it is.
        if self.device and self.device.startswith('O'):
            return self.LOCATION.outside

        # If we're here, it's an indoor device, so likely inside.
        return self.LOCATION.inside

    def get_current_measure(self):
        try:
            return self.place.api.get_world_current_measures_by_location(self.sensor_id)
        except requests.HTTPError:
            return self.place.api.get_current_measures(self.sensor_id)

    def update_data(self, data=None):
        if data is None:
            if self.sensor_id is None:
                raise ValueError('Cannot fetch AirGradient data if sensor_id is None.')
            data = self.get_current_measure()

        self.name = html.unescape(data['locationName']).strip()
        self.device = data.get('model', self.device)
        self.serial = data.get('serialno', self.serial)
        self.location = self.get_probable_location()

        # Some payloads include lat/lon, some don't...
        if data.get('latitude') and data.get('longitude'):
            self.position = Point(
                float(data['longitude']),
                float(data['latitude'])
            )

    def import_latest(self):
        from .tasks import process_data
        if data := self.get_current_measure():
            process_data.call_local(data, self.place_id)
            return True
        return False

    def select_channels(self, payload):
        has_channels = 'channel1' in payload or 'channel2' in payload
        channels = []

        if self.device == 'O-1PP':
            if not has_channels:
                # O-1PP without channel data is invalid — return nothing
                return channels

            # Add each available channel
            if 'channel1' in payload:
                channels.append(('1', payload['channel1']))

            if 'channel2' in payload:
                channels.append(('2', payload['channel2']))

        else:
            # Single-sensor model: treat top-level as data
            channels.append(('1', payload))

        return channels

    def create_entries(self, payload):
        timestamp = parse_timestamp(payload['timestamp'])
        channels = self.select_channels(payload)
        entries = []

        for EntryModel, spec in self.ENTRY_CONFIG.items():
            fields = spec.get('fields', {})

            for channel, payload in channels:
                data = {
                    field_name: payload.get(source_key)
                    for field_name, source_key in fields.items()
                }

                entry = self.create_entry(
                    EntryModel=EntryModel,
                    timestamp=timestamp,
                    sensor=channel,
                    **data
                )

                if entry is not None:
                    entries.append(entry)

        return entries

    def create_entry(self, EntryModel, **data):
        if not data or any(v is None for v in data.values()):
            return

        return super().create_entry(EntryModel, **data)

    def process_entry_pipeline(self, entry, cutoff_stage=None):
        '''
        Executes the full processing pipeline for a given entry,
        including handling stage-specific behavior for PurpleAir monitors.

        If the entry is at the RAW stage, this method will:
        - Run all processors for RAW entries (e.g., A/B correction)
        - Locate the previous CORRECTED entry, if available
        - Run the processing pipeline on the previous CORRECTED entry
          to perform spike detection and calibration, if applicable

        This ensures that entries are cleaned and calibrated in the correct order,
        accounting for the fact that spike detection depends on future (corrected) values.

        Returns:
            List of newly created entries generated during the processing pipeline.
        '''
        results = super().process_entry_pipeline(entry, cutoff_stage)

        if entry.stage == entry.Stage.RAW:
            corrected_entries = [e for e in results if e.stage == e.Stage.CORRECTED]
            for corrected in corrected_entries:
                if previous := corrected.get_previous_entry():
                    cleaned_entries = self.process_entry_pipeline(previous, cutoff_stage)
                    results.extend(cleaned_entries)

        return results
