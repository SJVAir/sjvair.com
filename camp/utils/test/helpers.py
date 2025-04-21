from datetime import datetime, timedelta
from decimal import Decimal
import random
import pytz


def generate_sensor_value(mean, variance):
    return Decimal(str(round(random.gauss(mean, variance), 2)))


def create_hourly_data_for_monitor(monitor, start_time=None):
    if start_time is None:
        start_time = datetime.now(tz=pytz.UTC) - timedelta(hours=1, minutes=1)

    entry_config = monitor.ENTRY_CONFIG
    for i in range(60):  # One per minute
        timestamp = start_time + timedelta(minutes=i)

        for EntryModel, config in entry_config.items():
            sensors = config.get('sensors', [''])  # Default to empty string sensor
            for sensor in sensors:
                fields = {}
                for field in config.get('fields', {}).keys():
                    if 'pm25' in field:
                        fields[field] = generate_sensor_value(15, 5)
                    elif 'pm10' in field:
                        fields[field] = generate_sensor_value(10, 3)
                    elif 'pm100' in field:
                        fields[field] = generate_sensor_value(20, 7)
                    elif 'temperature' in field:
                        fields[field] = generate_sensor_value(75, 5)
                    elif 'humidity' in field:
                        fields[field] = generate_sensor_value(40, 10)
                    elif 'pressure' in field:
                        fields[field] = generate_sensor_value(1013, 5)
                    elif 'particles' in field:
                        fields[field] = generate_sensor_value(100 * (1 + random.random()), 20)
                    else:
                        fields[field] = generate_sensor_value(5, 2)
                monitor.create_entry(
                    EntryModel,
                    timestamp=timestamp,
                    sensor=sensor,
                    stage=monitor.get_initial_stage(EntryModel),
                    **fields
                )