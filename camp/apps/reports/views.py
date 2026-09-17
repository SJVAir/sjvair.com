from datetime import timedelta

from django.contrib.gis.db.models.functions import Centroid
from django.contrib.gis.geos import Polygon
from django.contrib.gis.measure import D
from django.db.models import Count, Exists, OuterRef, Q, Sum
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from camp.apps.alerts.models import Subscription
from camp.apps.ces.models import CES4, CES5
from camp.apps.monitors.models import Monitor
from camp.apps.regions.models import Boundary, Region
from camp.apps.reports.base import BaseReport, register
from camp.utils import leaflet
from camp.utils.counties import County


OUTSIDE_SJV = 'Outside SJV'


# The ops reports (fleet health, degraded monitors) show every monitor subclass,
# including types that aren't on the public API. The ED-facing reports (network
# overview, coverage) count only enabled types -- see settings.MONITOR_ENABLED_TYPES.
# Fallback box around the San Joaquin Valley, used only when no county
# Regions are loaded. Map markers outside the map bounds are dropped: a
# device reporting a bogus fix (e.g. 0, 0) would otherwise force the map
# to fit the whole planet, and out-of-valley monitors would zoom it out.
DEFAULT_MAP_BOUNDS = Polygon.from_bbox((-122.0, 34.7, -117.5, 38.5))


def county_boundaries(county=''):
    """Current boundary geometries of the SJV county Regions, or just one county's."""
    regions = Region.objects.counties()
    if county:
        regions = regions.filter(name=f'{county} County')
    return list(Boundary.objects.filter(current_for__in=regions).values_list('geometry', flat=True))


def map_bounds(boundaries):
    """Bounding box of the drawn counties (slightly padded), or the valley fallback."""
    if not boundaries:
        return DEFAULT_MAP_BOUNDS
    xmin, ymin, xmax, ymax = boundaries[0].extent
    for geometry in boundaries[1:]:
        x0, y0, x1, y1 = geometry.extent
        xmin, ymin, xmax, ymax = min(xmin, x0), min(ymin, y0), max(xmax, x1), max(ymax, y1)
    pad = 0.05
    return Polygon.from_bbox((xmin - pad, ymin - pad, xmax + pad, ymax + pad))


def county_outlines(boundaries):
    """Unfilled county outlines to draw under map markers."""
    return [
        leaflet.Area(
            geometry=geometry.simplify(0.002, preserve_topology=True),
            fill_opacity=0,
            border_color='#2c3e50',
            border_width=1.5,
        )
        for geometry in boundaries
    ]


def monitor_types():
    """Concrete Monitor subclasses, sorted by class name."""
    return Monitor.get_subclasses()


def enabled_only(queryset):
    """Restrict a base-Monitor queryset to enabled types, as get_public() does."""
    enabled = Monitor.get_enabled_subclasses()
    if len(enabled) >= len(Monitor.get_subclasses()):
        return queryset

    lookup = Q()
    for subclass in enabled:
        lookup |= Q(**subclass.type_queryset_filter())
    return queryset.filter(lookup) if enabled else queryset.none()


def county_column(county):
    """Bucket a monitor's county field into a table column."""
    return county if county in County.names else OUTSIDE_SJV


def type_label(cls):
    return cls.__name__


@register
class NetworkOverview(BaseReport):
    slug = 'network-overview'
    title = 'Network Overview'
    description = 'Monitor counts by type and county. Hidden monitors are excluded unless requested.'
    template_name = 'admin/reports/network_overview.html'

    @property
    def include_hidden(self):
        return self.request.GET.get('include_hidden') == '1'

    def base_queryset(self):
        queryset = enabled_only(Monitor.objects.all())
        if not self.include_hidden:
            queryset = queryset.filter(is_hidden=False)
        return queryset

    def get_rows(self):
        columns = [*County.names, OUTSIDE_SJV]
        counts = {}
        for cls in Monitor.get_enabled_subclasses():
            queryset = cls.objects.all()
            if not self.include_hidden:
                queryset = queryset.filter(is_hidden=False)
            for item in queryset.values('county').annotate(n=Count('pk')):
                key = (type_label(cls), county_column(item['county']))
                counts[key] = counts.get(key, 0) + item['n']

        rows = []
        totals = {county: 0 for county in columns}
        for cls in Monitor.get_enabled_subclasses():
            label = type_label(cls)
            row = {'type': label}
            for county in columns:
                row[county] = counts.get((label, county), 0)
                totals[county] += row[county]
            row['total'] = sum(row[county] for county in columns)
            rows.append(row)

        rows.append({'type': 'All types', **totals, 'total': sum(totals.values())})
        return rows

    def get_tiles(self):
        cutoff = timezone.now() - timedelta(seconds=Monitor.LAST_ACTIVE_LIMIT)
        queryset = self.base_queryset()
        total = queryset.count()
        sjvair = queryset.filter(is_sjvair=True).count()
        active = queryset.with_last_entry_timestamp().filter(last_entry_timestamp__gte=cutoff).count()
        return {'total': total, 'active': active, 'sjvair': sjvair}

    def get_context_data(self, **kwargs):
        return {
            **super().get_context_data(**kwargs),
            'counties': County.names,
            'include_hidden': self.include_hidden,
            'tiles': self.get_tiles(),
        }


def per_10k(monitors, population):
    if not population:
        return None
    return round(monitors / population * 10000, 2)


@register
class Coverage(BaseReport):
    slug = 'coverage'
    title = 'Coverage and Equity'
    description = 'Monitors relative to population and disadvantaged-community (SB535 DAC) census tracts, from the newest CalEnviroScreen data loaded.'
    template_name = 'admin/reports/coverage.html'

    DEFAULT_RADIUS = 1000
    BANDS = [('0–25', 0, 25), ('25–50', 25, 50), ('50–75', 50, 75), ('75–100', 75, 100.0001)]

    @property
    def include_hidden(self):
        return self.request.GET.get('include_hidden') == '1'

    @property
    def radius(self):
        try:
            return max(0, int(self.request.GET.get('radius', self.DEFAULT_RADIUS)))
        except (TypeError, ValueError):
            return self.DEFAULT_RADIUS

    def monitors(self):
        queryset = enabled_only(Monitor.objects.filter(position__isnull=False))
        if not self.include_hidden:
            queryset = queryset.filter(is_hidden=False)
        return queryset

    def ces(self):
        """(model, version) for the newest CES data present, or (None, None)."""
        if not hasattr(self, '_ces'):
            self._ces = (None, None)
            for model in (CES5, CES4):
                version = (model._base_manager
                    .order_by('-boundary__version')
                    .values_list('boundary__version', flat=True)
                    .first())
                if version:
                    self._ces = (model, version)
                    break
        return self._ces

    def tracts(self):
        model, version = self.ces()
        if model is None:
            return None
        return model._base_manager.filter(boundary__version=version)

    def county_boundaries_by_name(self):
        """County name (as in County.names) -> current boundary geometry, from the county Regions."""
        return {
            region.name.removesuffix(' County'): region.boundary.geometry
            for region in Region.objects.counties().select_related('boundary')
            if region.boundary_id
        }

    def covered(self, tracts):
        """Annotate tracts with whether any monitor is within `radius` meters."""
        nearby = self.monitors().filter(
            # ST_DWithin in degrees uses the spatial index; ~88 km per degree at SJV
            # latitudes, so this is a generous superset of the exact meters filter below.
            position__dwithin=(OuterRef('boundary__geometry'), self.radius / 88000),
            position__distance_lte=(OuterRef('boundary__geometry'), D(m=self.radius)),
        )
        return tracts.annotate(covered=Exists(nearby))

    def get_rows(self):
        tracts = self.tracts()
        monitor_counts = {
            item['county']: item
            for item in (self.monitors()
                .annotate(in_dac=Exists(
                    tracts.filter(dac_sb535=True, boundary__geometry__contains=OuterRef('position'))
                ) if tracts is not None else Exists(Monitor.objects.none()))
                .values('county')
                .annotate(monitors=Count('pk'), dac_monitors=Count('pk', filter=Q(in_dac=True))))
        }

        rows = []
        county_boundaries = self.county_boundaries_by_name()
        for county in County.names:
            counts = monitor_counts.get(county, {'monitors': 0, 'dac_monitors': 0})
            stats = {'population': 0, 'dac_tracts': 0, 'dac_population': 0, 'dac_population_covered': 0}
            if tracts is not None and county in county_boundaries:
                county_tracts = (self.covered(tracts)
                    .annotate(centroid=Centroid('boundary__geometry'))
                    .filter(centroid__within=county_boundaries[county]))
                # The total is aliased to avoid shadowing the `population` field
                # for the DAC aggregates resolved alongside it.
                stats = county_tracts.aggregate(
                    total_population=Sum('population', default=0),
                    dac_tracts=Count('pk', filter=Q(dac_sb535=True)),
                    dac_population=Sum('population', filter=Q(dac_sb535=True), default=0),
                    dac_population_covered=Sum('population', filter=Q(dac_sb535=True, covered=True), default=0),
                )
                stats['population'] = stats.pop('total_population')
            rows.append(self.build_row(county, counts['monitors'], counts['dac_monitors'], stats))

        outside = [
            item for county, item in monitor_counts.items()
            if county not in County.names
        ]
        rows.append(self.build_row(
            OUTSIDE_SJV,
            sum(item['monitors'] for item in outside),
            sum(item['dac_monitors'] for item in outside),
            {'population': 0, 'dac_tracts': 0, 'dac_population': 0, 'dac_population_covered': 0},
        ))

        rows.append(self.build_row(
            'All counties',
            sum(row['monitors'] for row in rows),
            sum(row['dac_monitors'] for row in rows),
            {key: sum(row[key] for row in rows) for key in ('population', 'dac_tracts', 'dac_population', 'dac_population_covered')},
        ))
        return rows

    def build_row(self, county, monitors, dac_monitors, stats):
        dac_population = stats['dac_population']
        covered = stats['dac_population_covered']
        return {
            'county': county,
            'monitors': monitors,
            'population': stats['population'],
            'per_10k': per_10k(monitors, stats['population']),
            'dac_tracts': stats['dac_tracts'],
            'dac_monitors': dac_monitors,
            'dac_population': dac_population,
            'dac_population_covered': covered,
            'dac_covered_pct': round(covered / dac_population * 100, 1) if dac_population else None,
        }

    def get_percentile_bands(self):
        tracts = self.tracts()
        if tracts is None:
            return []
        rows = []
        for label, low, high in self.BANDS:
            band = tracts.filter(ci_score_p__gte=low, ci_score_p__lt=high)
            stats = band.aggregate(tracts=Count('pk'), total_population=Sum('population', default=0))
            monitors = self.monitors().filter(
                Exists(band.filter(boundary__geometry__contains=OuterRef('position')))
            ).count()
            rows.append({
                'band': label,
                'tracts': stats['tracts'],
                'population': stats['total_population'],
                'monitors': monitors,
                'per_10k': per_10k(monitors, stats['total_population']),
            })
        return rows

    MAP_TRACT_TOLERANCE = 0.0005  # degrees (~50 m); keeps ~1k polygons to a few hundred KB

    def get_map(self):
        """Valley-wide map: DAC tracts shaded, other tracts light, monitors as dots."""
        lmap = leaflet.LeafletMap(width=900, height=700, padding=10)
        boundaries = county_boundaries()
        bounds = map_bounds(boundaries)
        lmap.add(*county_outlines(boundaries))
        tracts = self.tracts()
        if tracts is not None:
            for dac, geometry in tracts.values_list('dac_sb535', 'boundary__geometry').iterator(chunk_size=500):
                lmap.add(leaflet.Area(
                    geometry=geometry.simplify(self.MAP_TRACT_TOLERANCE, preserve_topology=True),
                    fill_color='#c0392b' if dac else '#bdc3c7',
                    fill_opacity=0.35 if dac else 0.15,
                    border_color='#7f8c8d',
                    border_width=0.5,
                ))
        for position in self.monitors().filter(position__within=bounds).values_list('position', flat=True):
            lmap.add(leaflet.Marker(geometry=position, size=7, fill_color='#1f4e79', border_width=1))
        return lmap.render()

    def get_context_data(self, **kwargs):
        model, version = self.ces()
        return {
            **super().get_context_data(**kwargs),
            'ces_version': f'{model.__name__} ({version})' if model else None,
            'radius': self.radius,
            'include_hidden': self.include_hidden,
            'percentile_bands': self.get_percentile_bands(),
            'map': self.get_map(),
        }


@register
class SubscriptionCountyStats(BaseReport):
    slug = 'subscription-county-stats'
    title = 'Subscription Stats by County'
    description = 'Monitors, monitors with at least one subscriber, and total subscriptions, per county.'
    template_name = 'admin/reports/subscription_county_stats.html'

    def get_rows(self):
        monitor_lookup = {}
        subscription_lookup = {}
        for key, county in County.keys.items():
            monitor_lookup[f'{key}_total_monitors'] = Count('pk', filter=Q(county=county))
            monitor_lookup[f'{key}_subscription_monitors'] = Count('pk',
                filter=Q(county=county, subscriptions__isnull=False), distinct=True)
            subscription_lookup[f'{key}_total_subscriptions'] = Count('pk', filter=Q(monitor__county=county))

        monitor_stats = Monitor.objects.aggregate(**monitor_lookup)
        subscription_stats = Subscription.objects.aggregate(**subscription_lookup)

        return [{
            'county': county,
            'total_monitors': monitor_stats[f'{key}_total_monitors'],
            'subscription_monitors': monitor_stats[f'{key}_subscription_monitors'],
            'total_subscriptions': subscription_stats[f'{key}_total_subscriptions'],
        } for key, county in County.keys.items()]


@register
class FleetHealth(BaseReport):
    slug = 'fleet-health'
    title = 'Fleet Health'
    description = 'How recently each monitor type reported, and the current health grade distribution for dual-channel monitors.'
    template_name = 'admin/reports/fleet_health.html'

    @property
    def county(self):
        county = self.request.GET.get('county', '')
        return county if county in County.names else ''

    def scoped(self, queryset):
        if self.county:
            queryset = queryset.filter(county=self.county)
        return queryset

    def get_rows(self):
        now = timezone.now()
        hour = now - timedelta(hours=1)
        day = now - timedelta(days=1)
        week = now - timedelta(days=7)
        visible = Q(is_hidden=False)

        rows = []
        for cls in monitor_types():
            stats = self.scoped(cls.objects.get_queryset().with_last_entry_timestamp()).aggregate(
                active=Count('pk', filter=visible & Q(last_entry_timestamp__gte=hour)),
                silent_1d=Count('pk', filter=visible & Q(last_entry_timestamp__lt=hour, last_entry_timestamp__gte=day)),
                silent_7d=Count('pk', filter=visible & Q(last_entry_timestamp__lt=day, last_entry_timestamp__gte=week)),
                silent_long=Count('pk', filter=visible & Q(last_entry_timestamp__lt=week)),
                never=Count('pk', filter=visible & Q(last_entry_timestamp__isnull=True)),
                hidden=Count('pk', filter=Q(is_hidden=True)),
                total=Count('pk'),
            )
            rows.append({'type': type_label(cls), **stats})
        return rows

    def get_grades(self):
        eligible = Monitor.objects.get_for_health_checks()
        rows = []
        for cls in monitor_types():
            queryset = self.scoped(eligible.filter(**cls.health_check_queryset_filter()))
            if not queryset.exists():
                continue
            stats = queryset.aggregate(
                A=Count('pk', filter=Q(health__score=3)),
                B=Count('pk', filter=Q(health__score=2)),
                C=Count('pk', filter=Q(health__score=1)),
                F=Count('pk', filter=Q(health__score=0)),
                none=Count('pk', filter=Q(health__isnull=True)),
            )
            rows.append({'type': type_label(cls), **stats})
        return rows

    def get_context_data(self, **kwargs):
        return {
            **super().get_context_data(**kwargs),
            'counties': County.names,
            'county': self.county,
            'grades': self.get_grades(),
        }


@register
class DegradedMonitors(BaseReport):
    slug = 'degraded-monitors'
    title = 'Degraded Monitors'
    description = 'Monitors graded C or F, flatlined on a channel, or silent for more than 24 hours. Worst first.'
    template_name = 'admin/reports/degraded_monitors.html'

    @property
    def include_hidden(self):
        return self.request.GET.get('include_hidden') == '1'

    @property
    def county(self):
        county = self.request.GET.get('county', '')
        return county if county in County.names else ''

    @property
    def monitor_type(self):
        wanted = self.request.GET.get('type', '')
        return wanted if wanted in {cls.monitor_type for cls in monitor_types()} else ''

    def get_rows(self):
        now = timezone.now()
        day = now - timedelta(days=1)
        degraded = (
            Q(health__score__lte=1)
            | Q(health__sanity_flatline_a=False)
            | Q(health__sanity_flatline_b=False)
            | Q(last_entry_timestamp__lt=day)
            | Q(last_entry_timestamp__isnull=True)
        )

        rows = []
        for cls in monitor_types():
            if self.monitor_type and cls.monitor_type != self.monitor_type:
                continue
            queryset = (cls.objects
                .get_queryset()
                .with_last_entry_timestamp()
                .select_related('health', 'host')
                .filter(degraded)
            )
            if not self.include_hidden:
                queryset = queryset.filter(is_hidden=False)
            if self.county:
                queryset = queryset.filter(county=self.county)

            for monitor in queryset:
                rows.append(self.build_row(cls, monitor, now))

        rows.sort(key=lambda row: row['sort_key'])
        return rows

    def build_row(self, cls, monitor, now):
        health = monitor.health
        last_seen = monitor.last_entry_timestamp
        conditions = []
        # sort_key: lower sorts first. (0, -silence) silent, (1,) grade F, (2,) grade C, (3,) flatline only
        sort_key = (4, 0)

        if last_seen is None:
            conditions.append('Never reported')
            sort_key = (0, -float('inf'))
        elif last_seen < now - timedelta(days=1):
            silence = now - last_seen
            conditions.append(f'Silent {silence.days}d')
            sort_key = (0, -silence.total_seconds())

        if health is not None:
            if health.score == 0:
                conditions.append('Grade F')
                sort_key = min(sort_key, (1, 0))
            elif health.score == 1:
                conditions.append('Grade C')
                sort_key = min(sort_key, (2, 0))
            if health.sanity_flatline_a is False:
                conditions.append('Flatline A')
                sort_key = min(sort_key, (3, 0))
            if health.sanity_flatline_b is False:
                conditions.append('Flatline B')
                sort_key = min(sort_key, (3, 0))

        return {
            'name': monitor.name,
            'type': type_label(cls),
            'county': monitor.county,
            'host': monitor.host.name if monitor.host_id else '',
            'grade': health.grade if health is not None else '',
            'last_seen': last_seen,
            'condition': ', '.join(conditions),
            'admin_url': self.admin_url(cls, monitor),
            'sort_key': sort_key,
            'position': monitor.position,
            'map_color': self.MAP_COLORS[sort_key[0]],
        }

    # Keyed by the first element of sort_key: silent, grade F, grade C, flatline.
    MAP_COLORS = {0: '#7f8c8d', 1: '#c0392b', 2: '#e67e22', 3: '#8e44ad'}
    MAP_LEGEND = [('Silent / never reported', '#7f8c8d'), ('Grade F', '#c0392b'), ('Grade C', '#e67e22'), ('Flatline', '#8e44ad')]

    def get_map(self, rows):
        lmap = leaflet.LeafletMap(width=900, height=700, padding=10)
        boundaries = county_boundaries(self.county)
        bounds = map_bounds(boundaries)
        for row in rows:
            if row['position'] and bounds.contains(row['position']):
                lmap.add(leaflet.Marker(geometry=row['position'], size=9, fill_color=row['map_color']))
        if not lmap.elements:
            return None
        lmap.add(*county_outlines(boundaries))
        return lmap.render()

    def admin_url(self, cls, monitor):
        """Change-page URL, or '' when the subclass isn't registered in the admin."""
        try:
            return reverse(f'admin:{cls._meta.app_label}_{cls._meta.model_name}_change', args=[monitor.pk])
        except NoReverseMatch:
            return ''

    def get_context_data(self, **kwargs):
        context = {
            **super().get_context_data(**kwargs),
            'counties': County.names,
            'county': self.county,
            'monitor_type': self.monitor_type,
            'types': [(cls.monitor_type, type_label(cls)) for cls in monitor_types()],
            'include_hidden': self.include_hidden,
            'legend': self.MAP_LEGEND,
        }
        context['map'] = self.get_map(context['rows'])
        return context
