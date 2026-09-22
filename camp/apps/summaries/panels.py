"""
Air quality trend panel for the Region admin: daily region summaries as a
line chart with level bands, a comparison line, and headline tiles.
"""

from datetime import datetime, timedelta

from django.utils import timezone
from django.utils.functional import cached_property

from camp.apps.entries.fields import EntryTypeField
from camp.apps.regions.models import Region
from camp.apps.regions.panels import Panel, register
from camp.utils.charts import line_chart

RANGES = [('30d', '30 days', 30), ('90d', '90 days', 90), ('ytd', 'Year to date', None), ('12m', '12 months', 365)]
DEFAULT_RANGE = '30d'
DEFAULT_POLLUTANT = 'pm25'
REGION_COLOR = '#1f4e79'
COMPARISON_COLOR = '#7f8c8d'


def range_window(key):
    """(start_date, end_date_exclusive) in local calendar days ending yesterday."""
    end = timezone.localdate()
    for value, _label, days in RANGES:
        if value == key:
            if days is None:
                start = end.replace(month=1, day=1)
                # On January 1 the year-to-date window is empty; show 12 months.
                return (start, end) if start != end else (end - timedelta(days=365), end)
            return end - timedelta(days=days), end
    raise KeyError(key)


def daily_means(region_ids, entry_type, start, end):
    """{region_id: {date: (mean, station_count)}} for daily summaries in [start, end)."""
    from camp.apps.summaries.models import RegionSummary
    start_dt = timezone.make_aware(datetime.combine(start, datetime.min.time()))
    end_dt = timezone.make_aware(datetime.combine(end, datetime.min.time()))
    rows = (RegionSummary.objects
        .filter(region_id__in=region_ids, entry_type=entry_type, resolution=RegionSummary.Resolution.DAILY,
                timestamp__gte=start_dt, timestamp__lt=end_dt)
        .values_list('region_id', 'timestamp', 'mean', 'station_count')
        .order_by('timestamp'))
    out = {}
    for region_id, timestamp, mean, stations in rows:
        out.setdefault(region_id, {})[timezone.localtime(timestamp).date()] = (mean, stations)
    return out


@register
class TrendPanel(Panel):
    """Daily mean of a pollutant over a range, against the parent county (or all counties)."""

    types = tuple(Region.Type.values)
    title = 'Air quality trend'
    template_name = 'admin/regions/panels/trend.html'
    order = 10

    @property
    def range(self):
        wanted = self.request.GET.get('range', DEFAULT_RANGE)
        return wanted if wanted in {value for value, _label, _days in RANGES} else DEFAULT_RANGE

    @cached_property
    def available_pollutants(self):
        """Entry types with any daily row for this region, default pollutant first."""
        from camp.apps.summaries.models import RegionSummary
        present = set(RegionSummary.objects
            .filter(region=self.region, resolution=RegionSummary.Resolution.DAILY)
            .values_list('entry_type', flat=True).distinct())
        model_map = EntryTypeField.get_model_map()
        ordered = [DEFAULT_POLLUTANT] + sorted(key for key in model_map if key != DEFAULT_POLLUTANT)
        return [(key, str(model_map[key].label)) for key in ordered if key in present and key in model_map]

    @property
    def pollutant(self):
        available = [key for key, _label in self.available_pollutants]
        wanted = self.request.GET.get('pollutant', DEFAULT_POLLUTANT)
        if wanted in available:
            return wanted
        if DEFAULT_POLLUTANT in available:
            return DEFAULT_POLLUTANT
        return available[0] if available else DEFAULT_POLLUTANT

    def comparison(self):
        """(label, [region ids]) for the comparison line, or (None, [])."""
        if self.region.type == Region.Type.COUNTY:
            return 'All SJV counties', list(Region.objects.counties().values_list('pk', flat=True))
        county = (Region.objects.counties()
            .filter(boundary__geometry__contains=self.geometry.centroid)
            .first())
        return (county.name, [county.pk]) if county else (None, [])

    def get_context(self):
        start, end = range_window(self.range)
        pollutant = self.pollutant
        model = EntryTypeField.get_model_map().get(pollutant)
        levels = list(getattr(model, 'Levels', None) or []) if model else []
        usg = next((level for level in levels if level.key == 'unhealthy_sensitive'), None)
        unit = (getattr(model, 'units', '') or '') if model else ''

        comparison_label, comparison_ids = self.comparison()
        means = daily_means([self.region.pk, *comparison_ids], pollutant, start, end)
        own = means.get(self.region.pk, {})

        # The whole calendar window, always: a 30-day range spans 30 days even if
        # only a few of them have rows. Days with no data are None and line_chart
        # breaks the line there.
        days = [start + timedelta(days=offset) for offset in range((end - start).days)]

        region_points = [(day, own[day][0] if day in own else None) for day in days]
        comparison_points = []
        if comparison_ids:
            for day in days:
                values = [means[pk][day][0] for pk in comparison_ids if pk in means and day in means[pk]]
                comparison_points.append((day, sum(values) / len(values) if values else None))

        has_data = bool(own)
        stats = {}
        if has_data:
            values = [value for value, _stations in own.values()]
            worst_day = max(own, key=lambda day: own[day][0])
            latest = max(own)
            stats = {
                'mean': round(sum(values) / len(values), 1),
                'worst_day': worst_day,
                'worst_mean': round(own[worst_day][0], 1),
                'days_over': sum(1 for value in values if value >= usg.value) if usg else None,
                'over_label': str(usg.label) if usg else '',
                'stations': own[latest][1],
            }

        series = [{'label': self.region.name, 'points': region_points, 'color': REGION_COLOR, 'dashed': False}]
        if comparison_label and any(value is not None for _day, value in comparison_points):
            series.append({'label': comparison_label, 'points': comparison_points, 'color': COMPARISON_COLOR, 'dashed': True})
        bands = [(level.value, level.color) for level in levels]
        comparison = comparison_label if len(series) > 1 else None

        return {
            'has_data': has_data,
            'chart': line_chart(series, bands=bands, y_label=unit) if has_data else '',
            'range': self.range,
            'range_links': self.param_links('range', [(value, label) for value, label, _days in RANGES], self.range),
            'pollutant': pollutant,
            'pollutant_links': (
                self.param_links('pollutant', self.available_pollutants, pollutant)
                if len(self.available_pollutants) > 1 else []
            ),
            'pollutant_label': str(model.label) if model else pollutant,
            'unit': unit,
            'stats': stats,
            'comparison_label': comparison,
            'comparison_points': comparison_points if comparison else [],
            'start': start,
            'end': end - timedelta(days=1),
        }

    def controls(self):
        context = self.context
        controls = [('Range', 'choice', context['range_links'])]
        if context['pollutant_links']:
            controls.append(('Pollutant', 'choice', context['pollutant_links']))
        return controls

    def tiles(self):
        context = self.context
        if not context['has_data']:
            return []
        stats = context['stats']
        tiles = [
            (f"Mean {context['pollutant_label']}", f"{stats['mean']:g}"),
            ('Worst day', f"{stats['worst_mean']:g} on {stats['worst_day']:%b %-d}"),
        ]
        if stats['days_over'] is not None:
            tiles.append(('Days unhealthy for sensitive groups', str(stats['days_over'])))
        return tiles
