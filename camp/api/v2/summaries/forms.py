from datetime import timedelta

from django import forms

from camp.api.v2.forms import BboxField
from camp.apps.regions.models import Region
from camp.apps.summaries.models import BaseSummary


class BulkSummaryDateRangeForm(forms.Form):
    """`start`/`end` are inclusive dates. The span is capped per resolution so a
    single request can't page through an unbounded number of rows (hourly and
    daily are the only resolutions dense enough to need it)."""

    MAX_RANGE = {
        BaseSummary.Resolution.HOURLY: timedelta(days=31),
        BaseSummary.Resolution.DAILY: timedelta(days=366),
    }

    start = forms.DateField(required=True)
    end = forms.DateField(required=True)

    def __init__(self, *args, resolution=None, **kwargs):
        self.resolution = resolution
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('start')
        end = cleaned_data.get('end')

        if not start or not end:
            return cleaned_data  # Field-specific errors will already be raised

        if start > end:
            raise forms.ValidationError('start must be on or before end.')

        try:
            cleaned_data['end_exclusive'] = end + timedelta(days=1)
        except OverflowError:
            raise forms.ValidationError('end is out of range.')

        max_range = self.MAX_RANGE.get(self.resolution)
        if max_range is not None and end - start > max_range:
            raise forms.ValidationError(
                f'Maximum date range for {self.resolution} resolution is {max_range.days} days.'
            )

        return cleaned_data


class BulkMonitorSummaryForm(BulkSummaryDateRangeForm):
    bbox = BboxField()


class RegionListField(forms.Field):
    """Repeatable `region=<sqid>` parameter, cleaned to a list of Region
    instances. Blank values are dropped; unknown ids are an error rather than
    being silently ignored, since a bulk request that quietly returns nothing
    for a mistyped id is hard to debug from the client side."""

    widget = forms.SelectMultiple  # pulls every value via QueryDict.getlist()
    default_error_messages = {
        'required': 'At least one region is required.',
        'unknown': 'Unknown region id(s): %(ids)s',
    }

    def to_python(self, value):
        ids = [v.strip() for v in (value or []) if v and v.strip()]
        if not ids:
            return []
        regions = list(Region.objects.filter(sqid__in=ids))
        unknown = sorted(set(ids) - {region.sqid for region in regions})
        if unknown:
            raise forms.ValidationError(
                self.error_messages['unknown'], code='unknown', params={'ids': ', '.join(unknown)},
            )
        return regions


class BulkRegionSummaryForm(BulkSummaryDateRangeForm):
    region = RegionListField(required=True)
