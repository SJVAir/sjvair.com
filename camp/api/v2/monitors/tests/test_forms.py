from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from camp.api.v2.monitors.forms import MonitorAtForm
from camp.utils.datetime import make_aware


class MonitorAtFormTests(TestCase):
    def test_requires_timestamp(self):
        form = MonitorAtForm(data={})
        assert not form.is_valid()
        assert 'timestamp' in form.errors

    def test_naive_timestamp_assumed_local(self):
        form = MonitorAtForm(data={'timestamp': '2026-07-04 21:00:00'})
        assert form.is_valid(), form.errors
        expected = make_aware(datetime(2026, 7, 4, 21, 0, 0), tz=settings.DEFAULT_TIMEZONE)
        assert timezone.is_aware(form.cleaned_data['timestamp'])
        assert form.cleaned_data['timestamp'] == expected

    def test_aware_timestamp_passed_through_unchanged(self):
        form = MonitorAtForm(data={'timestamp': '2026-07-04T21:00:00Z'})
        assert form.is_valid(), form.errors
        expected = datetime(2026, 7, 4, 21, 0, 0, tzinfo=dt_timezone.utc)
        assert timezone.is_aware(form.cleaned_data['timestamp'])
        assert form.cleaned_data['timestamp'] == expected
        assert form.cleaned_data['timestamp'].timestamp() == expected.timestamp()

    def test_bbox_parses_four_floats(self):
        form = MonitorAtForm(data={
            'timestamp': '2026-07-04T21:00:00Z',
            'bbox': '-120.5,36.0,-119.5,37.0',
        })
        assert form.is_valid(), form.errors
        assert form.cleaned_data['bbox'] == (-120.5, 36.0, -119.5, 37.0)

    def test_bbox_rejects_wrong_number_of_parts(self):
        form = MonitorAtForm(data={
            'timestamp': '2026-07-04T21:00:00Z',
            'bbox': '-120.5,36.0,-119.5',
        })
        assert not form.is_valid()
        assert 'bbox' in form.errors

    def test_bbox_rejects_non_numeric_parts(self):
        form = MonitorAtForm(data={
            'timestamp': '2026-07-04T21:00:00Z',
            'bbox': 'a,b,c,d',
        })
        assert not form.is_valid()
        assert 'bbox' in form.errors

    def test_bbox_optional(self):
        form = MonitorAtForm(data={'timestamp': '2026-07-04T21:00:00Z'})
        assert form.is_valid(), form.errors
        assert form.cleaned_data['bbox'] is None
