import html
import time

from datetime import timedelta

from django.contrib.gis.db import models
from django.contrib.gis.geos import Point

from camp.apps.calibrations import processors
from camp.apps.entries import models as entry_models
from camp.apps.monitors.models import Monitor, Entry
from camp.apps.monitors.purpleair.api import purpleair_api
from camp.utils.datetime import parse_timestamp


class PurpleAir(Monitor):
    DATA_PROVIDERS = [{
        'name': 'PurpleAir',
        'url': 'https://www2.purpleair.com/'
    }]

    DATA_SOURCE = {
        'name': 'PurpleAir',
        'url': 'https://www2.purpleair.com/'
    }

    EXPECTED_INTERVAL = '2min'
    ENTRY_CONFIG = {
        entry_models.PM10: {
            'sensors': ['a', 'b'],
            'fields': {'value': 'pm1.0_atm'},
            'allowed_stages': [entry_models.PM10.Stage.RAW],
            'default_stage': entry_models.PM10.Stage.RAW,
        },
        entry_models.PM25: {
            'sensors': ['a', 'b'],
            'fields': {'value': 'pm2.5_atm'},
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
            }
        },
        entry_models.PM100: {
            'sensors': ['a', 'b'],
            'fields': {'value': 'pm10.0_atm'},
            'allowed_stages': [entry_models.PM25.Stage.RAW],
            'default_stage': entry_models.PM25.Stage.RAW,
        },
        entry_models.Particulates: {
            'sensors': ['a', 'b'],
            'fields': {
                'particles_03um': '0.3_um_count',
                'particles_05um': '0.5_um_count',
                'particles_10um': '1.0_um_count',
                'particles_25um': '2.5_um_count',
                'particles_50um': '5.0_um_count',
                'particles_100um': '10.0_um_count',
            },
            'allowed_stages': [entry_models.Particulates.Stage.RAW],
            'default_stage': entry_models.Particulates.Stage.RAW,
        },
        entry_models.Temperature: {
            'fields': {'fahrenheit': 'temperature'},
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
            'fields': {'value': 'humidity'},
            'allowed_stages': [
                entry_models.Humidity.Stage.RAW,
                entry_models.Humidity.Stage.CALIBRATED
            ],
            'processors': {
                entry_models.Humidity.Stage.RAW: [processors.AirGradientHumidity],
            },
            'default_stage': entry_models.Humidity.Stage.RAW,
        },
        entry_models.Pressure: {
            'fields': {'hpa': 'pressure'},
            'allowed_stages': [entry_models.Pressure.Stage.RAW],
            'default_stage': entry_models.Pressure.Stage.RAW,
        },
    }

    # Legacy
    CALIBRATE = True
    SENSORS = ['a', 'b']
    CHANNEL_FIELDS_LEGACY = {
        'pm10': 'pm1.0_atm',
        'pm25': 'pm2.5_atm',
        'pm25_reported': 'pm2.5_atm',
        'pm100': 'pm10.0_atm',
        'particles_03um': '0.3_um_count',
        'particles_05um': '0.5_um_count',
        'particles_10um': '1.0_um_count',
        'particles_25um': '2.5_um_count',
        'particles_50um': '5.0_um_count',
        'particles_100um': '10.0_um_count',
    }

    SENSOR_ATTRS = ['fahrenheit', 'humidity', 'pressure']
    SENSOR_ATTRS.extend(CHANNEL_FIELDS_LEGACY.keys())

    # Legacy - end

    purple_id = models.IntegerField(unique=True)

    class Meta:
        verbose_name = 'PurpleAir'

    def update_data(self, data=None):
        if data is None:
            if self.purple_id is None:
                raise ValueError(f'Cannot fetch Purple Air data if purple_id is None.')
            data = purpleair_api.get_sensor(self.purple_id)

        self.name = html.unescape(data['name'])
        self.position = Point(
            float(data['longitude']),
            float(data['latitude'])
        )
        self.location = self.get_probable_location(data)
        self.device = data.get('model', '')

        if not self.default_sensor:
            self.default_sensor = 'a'

    def get_probable_location(self, data):
        # Check for an explicit flag
        if data['location_type'] == 1:
            return self.LOCATION.inside

        # If the name says it's inside, it probably is
        name = data['name'].lower()
        inside_list = ('inside', 'indoor', 'in door', 'in-door')
        if any(item in name for item in inside_list):
            return self.LOCATION.inside

        # If we're here, it's probably outside.
        return self.LOCATION.outside

    def create_entries(self, payload):
        timestamp = parse_timestamp(payload.get('last_seen', payload.get('time_stamp')))
        entries = []

        for EntryModel, spec in self.ENTRY_CONFIG.items():
            sensors = spec.get('sensors') or ['']
            fields = spec.get('fields') or {}

            for sensor in sensors:
                data = {
                    field_name: payload.get(f"{source_key}_{sensor}" if sensor else source_key)
                    for field_name, source_key in fields.items()
                }

                if sensor:
                    data['sensor'] = sensor

                entry = self.create_entry(
                    EntryModel=EntryModel,
                    timestamp=timestamp,
                    **data
                )
                if entry is not None:
                    entries.append(entry)
        return entries

    def create_entry(self, EntryModel, **data):
        if not data or any(v is None for v in data.values()):
            return

        return super().create_entry(EntryModel, **data)

    def process_entry_pipeline(self, entry):
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
        results = super().process_entry_pipeline(entry)

        if entry.stage == entry.Stage.RAW:
            corrected_entries = [e for e in results if e.stage == e.Stage.CORRECTED]
            for corrected in corrected_entries:
                if previous := corrected.get_previous_entry():
                    cleaned_entries = self.process_entry_pipeline(previous)
                    results.extend(cleaned_entries)

        return results

    # Legacy
    def create_entries_legacy(self, payload):
        return [self.create_entry_legacy(data, data['sensor'])
            for data in self._split_channels(payload)]

    def create_entry_legacy(self, payload, sensor=None):
        try:
            entry = self.entries.get(
                sensor=sensor,
                timestamp=payload['timestamp'],
            )
            entry = self.process_entry(entry, payload)
            entry.save()
            return entry
        except Entry.DoesNotExist:
            return super().create_entry_legacy(payload, sensor=sensor)

    def _split_channels(self, payload):
        '''
            The Purple Air API returns a single object with data
            from both channels A and B. This method splits that into
            two data structures that can be saved independently.
        '''
        base_data = {
            'timestamp': parse_timestamp(payload.get('last_seen', payload.get('time_stamp'))),
            'fahrenheit': payload['temperature'],
            'humidity': payload['humidity'],
            'pressure': payload['pressure'],
        }

        for sensor in self.SENSORS:
            # If no PM2.5 data on this channel, skip it.
            if payload.get(f'{self.CHANNEL_FIELDS_LEGACY["pm25"]}_{sensor}') is None:
                continue

            data = base_data.copy()
            data.update(sensor=sensor, **{
                target: payload[f'{source}_{sensor}']
                for target, source in self.CHANNEL_FIELDS_LEGACY.items()
            })

            yield data


    def process_entry(self, entry, payload):
        # The fields are already correctly mapped in the _split_channels
        # method, so we just need to copy 'em over.

        for attr in self.SENSOR_ATTRS:
            if payload.get(attr) is not None:
                setattr(entry, attr, payload[attr])

        entry.timestamp = payload['timestamp']
        return super().process_entry(entry, payload)
