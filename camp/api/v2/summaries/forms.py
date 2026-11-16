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


class BulkMonitorScopeForm(forms.Form):
    """The monitor bulk endpoints' scoping (`region`, `MonitorFilter` and
    `processor` are read straight from the query string)."""
    bbox = BboxField()


class BulkMonitorSummaryForm(BulkMonitorScopeForm, BulkSummaryDateRangeForm):
    pass


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
        regions = list(Region.all_objects.filter(sqid__in=ids))
        unknown = sorted(set(ids) - {region.sqid for region in regions})
        if unknown:
            raise forms.ValidationError(
                self.error_messages['unknown'], code='unknown', params={'ids': ', '.join(unknown)},
            )
        return regions


class BulkRegionScopeForm(forms.Form):
    """Exactly one of `region` (repeatable ids, retired regions included) or
    `type` (every current region of one type, as /regions/geojson/ draws them).
    The scope lands in `cleaned_data['regions']`: a list of Regions, or a
    Region queryset the views use as a sub-select."""

    TYPE_CHOICES = [choice for choice in Region.Type.choices if choice[0] != Region.Type.LAND_USE]

    region = RegionListField(required=False)
    type = forms.ChoiceField(choices=TYPE_CHOICES, required=False)

    def clean(self):
        cleaned_data = super().clean()
        if 'region' in self.errors or 'type' in self.errors:
            return cleaned_data

        regions = cleaned_data.get('region')
        region_type = cleaned_data.get('type')
        if regions and region_type:
            self.add_error(None, forms.ValidationError(
                'Pass either region or type, not both.', code='exclusive',
            ))
        elif region_type:
            cleaned_data['regions'] = Region.objects.current_vintage().filter(type=region_type)
        elif regions:
            cleaned_data['regions'] = regions
        else:
            self.add_error('region', forms.ValidationError(
                'At least one region, or a type, is required.', code='required',
            ))
        return cleaned_data


class BulkRegionSummaryForm(BulkRegionScopeForm, BulkSummaryDateRangeForm):
    pass
