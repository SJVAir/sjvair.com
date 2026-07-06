from datetime import datetime

from django.test import TestCase
from django.utils import timezone

from camp.api.v2.monitors.forms import MonitorAtForm


class MonitorAtFormTests(TestCase):
    def test_requires_timestamp(self):
        form = MonitorAtForm(data={})
        assert not form.is_valid()
        assert 'timestamp' in form.errors

    def test_naive_timestamp_assumed_local(self):
        form = MonitorAtForm(data={'timestamp': '2026-07-04 21:00:00'})
        assert form.is_valid(), form.errors
        assert timezone.is_aware(form.cleaned_data['timestamp'])

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
