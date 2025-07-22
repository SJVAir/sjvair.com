import pytz
import random

from datetime import datetime, timedelta
from decimal import Decimal
from functools import wraps

from django_huey import get_queue


def generate_sensor_value(mean, variance):
    return Decimal(str(round(random.gauss(mean, variance), 2)))


def create_hourly_data_for_monitor(monitor, start_time=None):
    if start_time is None:
        start_time = datetime.now(tz=pytz.UTC) - timedelta(hours=1, minutes=1)

    entries = []
    for i in range(60):  # One per minute
        entries = []
        timestamp = start_time + timedelta(minutes=i)

        for EntryModel, config in monitor.ENTRY_CONFIG.items():
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

                entry = EntryModel.objects.create(
                    monitor=monitor,
                    location=monitor.location,
                    position=monitor.position,
                    timestamp=timestamp,
                    sensor=sensor,
                    stage=config['allowed_stages'][0],
                    **fields
                )
                monitor.process_entry_pipeline(entry)
                entries.append(entry)


def queue_immediate_mode(enabled: bool, queue_name='primary'):
    """
    Decorator to temporarily set immediate mode on a Huey queue during a test.
    """
    def decorator(test_func):
        @wraps(test_func)
        def wrapper(*args, **kwargs):
            queue = get_queue(queue_name)
            original_immediate = queue.immediate
            queue.immediate = enabled
            try:
                return test_func(*args, **kwargs)
            finally:
                queue.immediate = original_immediate
        return wrapper
    return decorator
