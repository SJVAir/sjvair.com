"""
Coverage panels for the Region admin: what the Coverage by Community report
knows about one city, CDP or urban area, and the communities inside a county.
"""

from django.db.models import Avg, Count, Max, Q, Sum
from django.urls import reverse

from camp.apps.regions.models import Region
from camp.apps.regions.panels import Panel, monitors_inside, register, status_counts, type_rows
from camp.apps.reports.scope import MonitorScope
from camp.apps.reports.views import (
    Centroid, CoverageCommunity, ces_tracts, county_column, per_10k, sphere_km, to_radians,
)
from camp.utils.gis import fill_holes, has_holes


def tract_stats(geometry):
    """CES tracts whose centroid is inside `geometry`: counts, populations, percentiles."""
    _model, _version, tracts = ces_tracts()
    empty = {'tracts': 0, 'dac_tracts': 0, 'population': 0, 'dac_population': 0,
             'avg_percentile': None, 'max_percentile': None}
    if tracts is None:
        return empty
    inside = tracts.annotate(c=Centroid('boundary__geometry')).filter(c__within=geometry)
    stats = inside.aggregate(
        tracts=Count('pk'),
        dac_tracts=Count('pk', filter=Q(dac_sb535=True)),
        total_population=Sum('population', default=0),
        dac_population=Sum('population', filter=Q(dac_sb535=True), default=0),
        avg_percentile=Avg('ci_score_p'),
        max_percentile=Max('ci_score_p'),
    )
    stats['population'] = stats.pop('total_population')
    if stats['tracts'] == 0:
        # No tract centroid inside: use the tract the region's centroid sits in.
        containing = tracts.filter(boundary__geometry__contains=geometry.centroid).first()
        if containing is not None:
            stats['population'] = containing.population or 0
    for key in ('avg_percentile', 'max_percentile'):
        stats[key] = round(stats[key], 1) if stats[key] is not None else None
    return stats


def nearest_counted(scope, geometry):
    """(name, km) of the counted monitor nearest the geometry's centroid, or None."""
    here = to_radians(geometry.centroid)
    candidates = [
        (sphere_km(here, to_radians(position)), name)
        for name, position in scope.monitors().values_list('name', 'position')
    ]
    if not candidates:
        return None
    km, name = min(candidates)
    return {'name': name, 'km': round(km, 1)}


class ScopedPanel(Panel):
    @property
    def scope(self):
        return MonitorScope(self.request.GET)

    def scope_links(self):
        return self.scope.toggle_links(reverse('admin:regions_region_change', args=[self.region.pk]))


@register
class CommunityCoveragePanel(ScopedPanel):
    """Coverage numbers for a city, CDP or urban area, with holes filled for containment."""

    types = (Region.Type.CITY, Region.Type.CDP, Region.Type.URBAN_AREA)
    title = 'Coverage'
    template_name = 'admin/regions/panels/community.html'

    @property
    def coverage_geometry(self):
        return fill_holes(self.geometry)

    def get_context(self):
        geometry = self.coverage_geometry
        rows = monitors_inside(geometry)
        tracts = tract_stats(geometry)
        counted = self.scope.monitors().filter(position__within=geometry).count()
        county = (Region.objects.counties()
            .filter(boundary__geometry__contains=self.geometry.centroid)
            .values_list('name', flat=True).first())
        return {
            'has_holes': has_holes(self.geometry),
            'county': county_column((county or '').removesuffix(' County')),
            'type_label': CoverageCommunity.TYPE_LABELS.get(self.region.type, self.region.get_type_display()),
            'tracts': tracts,
            'counts': status_counts(rows),
            'rows': rows,
            'monitors': counted,
            'per_10k': per_10k(counted, tracts['population']),
            'nearest': None if counted else nearest_counted(self.scope, geometry),
            'scope': self.scope,
            'scope_links': self.scope_links(),
        }


@register
class CountyCoveragePanel(ScopedPanel):
    """The communities inside a county and their coverage, plus the county's monitors."""

    types = (Region.Type.COUNTY,)
    title = 'Communities and coverage'
    template_name = 'admin/regions/panels/county.html'

    def get_context(self):
        county = self.region.name.removesuffix(' County')
        communities = CoverageCommunity.build_rows(self.scope, county=county)
        communities.sort(key=lambda row: (-row['population'], row['name']))
        rows = monitors_inside(self.geometry)
        covered = sum(1 for row in communities if row['monitors'])
        uncovered_population = sum(row['population'] for row in communities if not row['monitors'])
        total_population = sum(row['population'] for row in communities)
        return {
            'communities': communities,
            'tiles': {
                'covered': covered,
                'uncovered': len(communities) - covered,
                'uncovered_population': uncovered_population,
                'uncovered_pct': round(uncovered_population / total_population * 100, 1) if total_population else None,
            },
            'counts': status_counts(rows),
            'rows': rows,
            'type_rows': type_rows(rows, county=county),
            'scope': self.scope,
            'scope_links': self.scope_links(),
        }
