"""
Type-specific detail panels for the Region admin change page.

A panel declares which region types it applies to and renders a template.
Other apps register their own (see camp.apps.reports.panels); the admin
renders every panel that applies, in registration order.
"""

from datetime import timedelta

from django.template.loader import render_to_string
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from camp.apps.monitors.models import Monitor
from camp.apps.regions.models import Region

PANELS = []


def register(cls):
    PANELS.append(cls)
    return cls


def panels_for(region, request):
    return [cls(region, request) for cls in PANELS if cls.applies(region)]


class Panel:
    types = ()
    title = ''
    template_name = None

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

    def render(self):
        return render_to_string(self.template_name, {
            'panel': self,
            'region': self.region,
            **self.get_context(),
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

    def get_context(self):
        rows = monitors_inside(self.geometry)
        return {'rows': rows, 'counts': status_counts(rows)}


@register
class TractPanel(Panel):
    """Every CalEnviroScreen record for a census tract, newest first, plus the monitors inside."""

    types = (Region.Type.TRACT,)
    title = 'CalEnviroScreen'
    template_name = 'admin/regions/panels/tract.html'

    SKIP_FIELDS = {'id', 'boundary'}
    HEADLINE_FIELDS = ('population', 'ci_score', 'ci_score_p', 'dac_sb535', 'dac_category')

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
                by_name = {field.name: field for field in record._meta.fields}
                fields = [
                    (field.verbose_name, self.field_value(record, field))
                    for field in record._meta.fields
                    if field.name not in self.SKIP_FIELDS
                ]
                headline = [
                    (by_name[name].verbose_name, self.field_value(record, by_name[name]))
                    for name in self.HEADLINE_FIELDS if name in by_name
                ]
                records.append({'label': f'{label} ({boundary.version} tracts)', 'headline': headline, 'fields': fields})
        return records

    def get_context(self):
        rows = monitors_inside(self.geometry)
        return {'records': self.records(), 'rows': rows, 'counts': status_counts(rows)}
