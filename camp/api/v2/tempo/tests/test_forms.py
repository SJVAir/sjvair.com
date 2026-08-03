from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from camp.api.v2.tempo.forms import TempoPointForm, TempoSeriesForm


class TempoSeriesFormTests(TestCase):
    def test_both_omitted_is_valid_with_none_bounds(self):
        form = TempoSeriesForm(data={})

        assert form.is_valid()
        assert form.cleaned_data['start'] is None
        assert form.cleaned_data['end'] is None

    def test_only_start_given_mirrors_to_end(self):
        now = timezone.now().replace(microsecond=0)
        form = TempoSeriesForm(data={'start': now.isoformat()})

        assert form.is_valid()
        assert form.cleaned_data['start'] == form.cleaned_data['end']

    def test_only_end_given_mirrors_to_start(self):
        now = timezone.now().replace(microsecond=0)
        form = TempoSeriesForm(data={'end': now.isoformat()})

        assert form.is_valid()
        assert form.cleaned_data['start'] == form.cleaned_data['end']

    def test_start_after_end_is_invalid(self):
        now = timezone.now().replace(microsecond=0)
        form = TempoSeriesForm(data={'start': now.isoformat(), 'end': (now - timedelta(days=1)).isoformat()})

        assert not form.is_valid()

    def test_range_over_ninety_days_is_invalid(self):
        now = timezone.now().replace(microsecond=0)
        form = TempoSeriesForm(data={'start': (now - timedelta(days=91)).isoformat(), 'end': now.isoformat()})

        assert not form.is_valid()

    def test_range_of_exactly_ninety_days_is_valid(self):
        now = timezone.now().replace(microsecond=0)
        form = TempoSeriesForm(data={'start': (now - timedelta(days=90)).isoformat(), 'end': now.isoformat()})

        assert form.is_valid()


class TempoPointFormTests(TestCase):
    def test_requires_latitude_and_longitude(self):
        form = TempoPointForm(data={})

        assert not form.is_valid()
        assert 'latitude' in form.errors
        assert 'longitude' in form.errors

    def test_valid_with_lat_lon_only(self):
        form = TempoPointForm(data={'latitude': '36.7', 'longitude': '-119.8'})

        assert form.is_valid()
        assert form.point.x == -119.8
        assert form.point.y == 36.7
