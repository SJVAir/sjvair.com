"""
Coverage panels for the Region admin: what the Coverage by Community report
knows about one city, CDP or urban area, and the communities inside a county.
"""

from django.contrib.humanize.templatetags.humanize import intcomma
from django.urls import reverse

from camp.apps.ces import stats as ces_stats
from camp.apps.regions.models import Region
from camp.apps.regions.panels import Panel, monitors_inside, register, status_counts, type_rows
from camp.apps.reports.scope import MonitorScope
from camp.apps.reports.views import Centroid, CoverageCommunity, county_column, per_10k, sphere_km, to_radians
from camp.utils.gis import fill_holes, has_holes


def tract_stats(geometry):
    """
    CES tracts the geometry covers (ces.stats.tract_summary: centroid inside,
    or a tenth of the tract's area), as the panel templates read them. A
    geometry too small to cover a tract reports the population of the tract
    it sits in. -999 "no score" tracts count but aren't averaged.
    """
    empty = {'tracts': 0, 'dac_tracts': 0, 'population': 0, 'dac_population': 0,
             'avg_percentile': None, 'max_percentile': None}
    summary = ces_stats.tract_summary(geometry)
    if summary is None:
        return empty
    population = summary['population']
    if not summary['count'] and summary['containing']:
        population = summary['containing']['population']
    return {
        'tracts': summary['count'],
        'dac_tracts': summary['dac_tracts'],
        'population': population,
        'dac_population': summary['dac_population'],
        'avg_percentile': round(summary['mean_p'], 1) if summary['mean_p'] is not None else None,
        'max_percentile': round(summary['max_p'], 1) if summary['max_p'] is not None else None,
    }


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

    def controls(self):
        return [('Counted monitors', 'toggle', self.scope_links())]


@register
class CommunityCoveragePanel(ScopedPanel):
    """Coverage numbers for a city, CDP or urban area, with holes filled for containment."""

    types = (Region.Type.CITY, Region.Type.CDP, Region.Type.URBAN_AREA)
    title = 'Coverage'
    template_name = 'admin/regions/panels/community.html'
    order = 20

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

    def tiles(self):
        context = self.context
        per_10k = context['per_10k']
        return [
            ('Population', intcomma(context['tracts']['population'])),
            ('Counted monitors', intcomma(context['monitors'])),
            ('Per 10k', '—' if per_10k is None else str(per_10k)),
        ]


@register
class CountyCoveragePanel(ScopedPanel):
    """The communities inside a county and their coverage, plus the county's monitors."""

    types = (Region.Type.COUNTY,)
    title = 'Communities and coverage'
    template_name = 'admin/regions/panels/county.html'
    order = 20

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

    def tiles(self):
        tiles = self.context['tiles']
        return [
            ('Communities without a monitor', str(tiles['uncovered'])),
            ('Population without a monitor', intcomma(tiles['uncovered_population'])),
        ]


@register
class OverlapPanel(ScopedPanel):
    """Cities and CDPs whose centroid falls inside a district or zip code, with their coverage."""

    types = (Region.Type.SCHOOL_DISTRICT, Region.Type.ZIPCODE, Region.Type.CONGRESSIONAL_DISTRICT,
             Region.Type.STATE_ASSEMBLY, Region.Type.STATE_SENATE)
    title = 'Communities inside'
    template_name = 'admin/regions/panels/overlap.html'
    order = 30

    def get_context(self):
        inside = set(CoverageCommunity.place_queryset()
            .annotate(c=Centroid('boundary__geometry'))
            .filter(c__within=self.geometry)
            .values_list('pk', flat=True))
        rows = [row for row in CoverageCommunity.build_rows(self.scope) if row['pk'] in inside]
        rows.sort(key=lambda row: (-row['population'], row['name']))
        return {'communities': rows, 'scope': self.scope, 'scope_links': self.scope_links()}

    def tiles(self):
        return [('Communities inside', str(len(self.context['communities'])))]
