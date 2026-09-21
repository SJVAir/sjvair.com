"""
Type-specific detail panels for the Region admin change page.

A panel declares which region types it applies to and renders a template.
Other apps register their own (see camp.apps.reports.panels); the admin
renders every panel that applies, in `order`, then registration order.
"""

from datetime import timedelta

from django.template.loader import render_to_string
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.functional import cached_property

from camp.apps.monitors.models import Monitor
from camp.apps.regions.models import Region

PANELS = []


def register(cls):
    PANELS.append(cls)
    return cls


def panels_for(region, request):
    """Every registered panel that applies to `region`, sorted by order then registration."""
    chosen = [(cls.order, index, cls) for index, cls in enumerate(PANELS) if cls.applies(region)]
    return [cls(region, request) for _order, _index, cls in sorted(chosen, key=lambda item: item[:2])]


class Panel:
    types = ()
    title = ''
    template_name = None
    order = 100

    def __init__(self, region, request):
        self.region = region
        self.request = request

    @classmethod
    def applies(cls, region):
        return region.type in cls.types and region.boundary_id is not None

    @property
    def geometry(self):
        return self.region.boundary.geometry

    def get_context(self):
        return {}

    @cached_property
    def context(self):
        """get_context() computed once per request; tiles() and render() both read it."""
        return self.get_context()

    def tiles(self):
        """(label, value) pairs for the dashboard header row. Values are preformatted strings."""
        return []

    def controls(self):
        """
        Query-param selectors for the page's shared control bar, as
        `(label, kind, links)` where kind is 'choice' (one of) or 'toggle'
        (on/off) and links are `(label, url, active)`. The change form
        renders each label once, so panels sharing a param agree.
        """
        return []

    def param_links(self, name, choices, current=None):
        """
        (label, url, active) for a query-param selector: each link sets `name`
        to that choice and keeps every other param. Pass `current` when the
        panel resolves the value itself, so the default reads as active when
        the param isn't in the URL at all.
        """
        if current is None:
            current = self.request.GET.get(name)
        links = []
        for value, label in choices:
            query = self.request.GET.copy()
            query[name] = value
            links.append((label, '?' + query.urlencode(), value == current))
        return links

    def render(self):
        return render_to_string(self.template_name, {
            'panel': self,
            'region': self.region,
            **self.context,
        })


def admin_change_url(cls, monitor):
    try:
        return reverse(f'admin:{cls._meta.app_label}_{cls._meta.model_name}_change', args=[monitor.pk])
    except NoReverseMatch:
        return ''


def monitors_inside(geometry):
    """
    Every positioned outdoor monitor of an enabled type inside `geometry`,
    as row dicts with a status (Active / Inactive / Hidden), sorted active
    first. Indoor monitors are left out: these pages are about outdoor air.
    One query per monitor type.
    """
    cutoff = timezone.now() - timedelta(seconds=Monitor.LAST_ACTIVE_LIMIT)
    rows = []
    for cls in Monitor.get_enabled_subclasses():
        queryset = (cls.objects.get_queryset()
            .with_last_entry_timestamp()
            .filter(position__within=geometry)
            .exclude(location=Monitor.LOCATION.inside)
            .select_related('host'))
        for monitor in queryset:
            if monitor.is_hidden:
                status = 'Hidden'
            elif monitor.last_entry_timestamp and monitor.last_entry_timestamp >= cutoff:
                status = 'Active'
            else:
                status = 'Inactive'
            rows.append({
                'name': monitor.name,
                'type': cls.__name__,
                'status': status,
                'last_seen': monitor.last_entry_timestamp,
                'host': monitor.host.name if monitor.host_id else '',
                'is_sjvair': monitor.is_sjvair,
                'position': monitor.position,
                'admin_url': admin_change_url(cls, monitor),
            })
    rows.sort(key=lambda row: (row['status'] != 'Active', row['status'], row['name']))
    return rows


def type_rows(rows, county=''):
    """Per monitor type: totals, actives, and a link to that type's admin changelist (filtered by county)."""
    out = []
    for cls in Monitor.get_enabled_subclasses():
        mine = [row for row in rows if row['type'] == cls.__name__]
        if not mine:
            continue
        try:
            url = reverse(f'admin:{cls._meta.app_label}_{cls._meta.model_name}_changelist')
            if county:
                url += f'?county={county}'
        except NoReverseMatch:
            url = ''
        out.append({
            'label': cls.__name__,
            'total': len(mine),
            'active': sum(1 for row in mine if row['status'] == 'Active'),
            'changelist_url': url,
        })
    return out


def status_counts(rows):
    return {
        'total': len(rows),
        'active': sum(1 for row in rows if row['status'] == 'Active'),
        'inactive': sum(1 for row in rows if row['status'] == 'Inactive'),
        'hidden': sum(1 for row in rows if row['status'] == 'Hidden'),
        'sjvair': sum(1 for row in rows if row['is_sjvair']),
    }


@register
class MonitorsPanel(Panel):
    """Monitors inside the boundary, for region types with no richer panel."""

    types = (
        Region.Type.ZIPCODE, Region.Type.SCHOOL_DISTRICT, Region.Type.CONGRESSIONAL_DISTRICT,
        Region.Type.STATE_ASSEMBLY, Region.Type.STATE_SENATE, Region.Type.PROTECTED,
        Region.Type.LAND_USE, Region.Type.PLACE, Region.Type.CUSTOM, Region.Type.MTRS,
    )
    title = 'Monitors inside'
    template_name = 'admin/regions/panels/monitors.html'
    order = 40

    def get_context(self):
        rows = monitors_inside(self.geometry)
        return {'rows': rows, 'counts': status_counts(rows)}

    def tiles(self):
        counts = self.context['counts']
        return [('Active monitors', f"{counts['active']} / {counts['total']}")]


@register
class TractPanel(Panel):
    """Every CalEnviroScreen record for a census tract, newest first, plus the monitors inside."""

    types = (Region.Type.TRACT,)
    title = 'CalEnviroScreen'
    template_name = 'admin/regions/panels/tract.html'
    order = 20

    SKIP_FIELDS = {'id', 'boundary'}
    HEADLINE = ('population', 'ci_score', 'ci_score_p', 'dac_sb535', 'dac_category')
    GROUPS = (('Pollution burden', 'pollution', 'pol_'), ('Population characteristics', 'popchar', 'char_'))

    @staticmethod
    def field_value(record, field):
        if field.choices:
            return getattr(record, f'get_{field.name}_display')()
        return getattr(record, field.name)

    def records(self):
        records = []
        for boundary in self.region.boundaries.order_by('-version'):
            for attr, label in (('ces5', 'CalEnviroScreen 5.0'), ('ces4', 'CalEnviroScreen 4.0')):
                record = getattr(boundary, attr, None)
                if record is None:
                    continue
                fields = [
                    (field.verbose_name, self.field_value(record, field))
                    for field in record._meta.fields
                    if field.name not in self.SKIP_FIELDS
                ]
                records.append({'label': f'{label} ({boundary.version} tracts)', 'fields': fields})
        return records

    @cached_property
    def newest_records(self):
        """{'CES5': record, 'CES4': record} using the newest boundary that has each."""
        found = {}
        for boundary in self.region.boundaries.order_by('-version'):
            for attr, key in (('ces5', 'CES5'), ('ces4', 'CES4')):
                if key not in found:
                    record = getattr(boundary, attr, None)
                    if record is not None:
                        found[key] = record
        return found

    @staticmethod
    def display(record, name):
        """
        One grid cell, rendered for display: booleans as Yes/No, choice fields
        as their label, floats rounded. Rounding happens here rather than in the
        template because `floatformat` renders anything non-numeric -- including
        'Yes' and the em-dash placeholder -- as an empty string.
        """
        if record is None:
            return None
        field = record._meta.get_field(name)
        value = TractPanel.field_value(record, field)
        if isinstance(value, bool):
            return 'Yes' if value else 'No'
        if isinstance(value, float):
            # CES4 uses -999 for indicators with no data.
            return None if value <= -999 else round(value, 2)
        return value

    def indicators(self):
        """
        The CES5/CES4 comparison grid: a headline block plus one group per
        score, each row carrying (label, value, percentile) for every version.
        CES4 and CES5 do not share every indicator, so membership is checked
        per record rather than once.
        """
        records = self.newest_records
        versions = [key for key in ('CES5', 'CES4') if key in records]
        if not versions:
            return {'versions': [], 'headline': [], 'groups': []}

        names_by_version = {key: {field.name for field in record._meta.fields}
                            for key, record in records.items()}

        def label_of(name):
            for record in records.values():
                try:
                    return record._meta.get_field(name).verbose_name
                except Exception:
                    continue
            return name

        def cell(key, name):
            if name not in names_by_version[key]:
                return None
            return self.display(records[key], name)

        def values(name):
            return [cell(key, name) for key in versions]

        def pairs(name):
            cells = []
            for key in versions:
                cells.append(cell(key, name))
                cells.append(cell(key, f'{name}_p'))
            return cells

        headline = [(label_of(name), *values(name)) for name in self.HEADLINE]
        groups = []
        for label, score_name, prefix in self.GROUPS:
            names = sorted({
                field.name for record in records.values() for field in record._meta.fields
                if field.name.startswith(prefix) and not field.name.endswith('_p')
            })
            rows = [(label_of(name), *pairs(name)) for name in names]
            groups.append({
                'label': label,
                'score': (label_of(score_name), *pairs(score_name)),
                'rows': rows,
            })
        return {'versions': versions, 'headline': headline, 'groups': groups}

    def tiles(self):
        records = self.newest_records
        record = records.get('CES5') or records.get('CES4')
        if record is None:
            return []
        return [
            ('CES percentile', '—' if record.ci_score_p is None else f'{round(record.ci_score_p, 1):g}'),
            ('SB535 DAC', '—' if record.dac_sb535 is None else ('Yes' if record.dac_sb535 else 'No')),
        ]

    def get_context(self):
        rows = monitors_inside(self.geometry)
        return {
            'records': self.records(),
            'indicators': self.indicators(),
            'rows': rows,
            'counts': status_counts(rows),
        }
