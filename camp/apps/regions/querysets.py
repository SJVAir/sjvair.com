from django.contrib.gis.db import models
from django.contrib.gis.db.models import Count, FloatField, Func, F, OuterRef, Subquery, Union
from django.contrib.gis.db.models.functions import Intersection
from django.contrib.gis.geos import GEOSGeometry
from django.contrib.postgres.search import TrigramWordSimilarity
from django.db.models import Case, Q, Value, When
from django.db.models.functions import Coalesce, Greatest, Lower, NullIf, Trim
from django.db.models.lookups import GreaterThanOrEqual
from django.db.models.query import ModelIterable

import geopandas as gpd
from shapely.wkt import loads as load_wkt

from camp.utils import maps

# The census tract vintage every current feature uses (the ACS and
# CalEnviroScreen 5 are on 2020 tracts). Tracts whose current boundary is an
# older vintage are retired: kept for CalEnviroScreen 4, never shown.
TRACT_VINTAGE = '2020'


def overlap_area(geometry: GEOSGeometry):
    """Expression: the area of a region's boundary that falls inside `geometry`."""
    return Func(
        Intersection('boundary__geometry', geometry),
        function='ST_Area', output_field=FloatField(),
    )


class RegionQuerySet(models.QuerySet):
    def current_vintage(self):
        """Leave out retired census tracts (see TRACT_VINTAGE); other types pass through.
        Tracts with no boundary at all are left out too."""
        from camp.apps.regions.models import Region

        return self.exclude(Q(type=Region.Type.TRACT) & ~Q(boundary__version=TRACT_VINTAGE))

    def with_monitor_count(self):
        from camp.apps.monitors.models import Monitor

        # Subquery returns a single count of monitors intersecting the region geometry
        monitor_count_query = (Monitor.objects
            .filter(position__intersects=OuterRef('boundary__geometry'))
            .order_by()  # Required to use Subquery safely
            .annotate(count=Func(F('id'), function='Count'))
            .values('count')
        )

        return self.annotate(
            monitor_count=Subquery(monitor_count_query, output_field=models.IntegerField())
        )

    def render_map(self, **kwargs):
        geometries = [region.boundary.geometry for region in self.select_related('boundary')]
        return maps.from_geometries(*geometries, **kwargs)

    def to_dataframe(self, fields=None, crs='EPSG:4326'):
        fields = fields or [
            'sqid', 'name', 'slug', 'type',
            'boundary__geometry', 'boundary__metadata'
        ]

        records = []
        for row in self.values(*fields):
            record = {k: row[k] for k in fields if not k.startswith('boundary__')}
            record['geometry'] = load_wkt(row['boundary__geometry'].wkt)
            record['metadata'] = row['boundary__metadata']
            records.append(record)

        return gpd.GeoDataFrame(records, geometry='geometry', crs=crs)

    def intersects(self, geometry: GEOSGeometry):
        """
        Filters regions that intersect the given geometry.
        """
        return self.filter(boundary__geometry__intersects=geometry)

    def _area_fraction_inside(self, geometry: GEOSGeometry, min_fraction: float):
        """Regions with at least `min_fraction` of their own area inside `geometry`."""
        area = Func('boundary__geometry', function='ST_Area', output_field=FloatField())
        return (self
            # ST_Intersects first so the spatial index prunes candidates
            # before the (expensive) intersection area is computed.
            .filter(boundary__geometry__intersects=geometry)
            .annotate(overlap_fraction=overlap_area(geometry) / NullIf(area, 0.0))
            .filter(overlap_fraction__gte=min_fraction)
        )

    def contained_within(self, geometry: GEOSGeometry, min_fraction: float = 0.99):
        """
        Filters regions that are (essentially) entirely inside the given
        geometry: at least `min_fraction` of the region's own area must fall
        within it. Regions that only touch its border, or that genuinely
        straddle it (e.g. a congressional district spanning two counties),
        are excluded - "within this area" callers want regions inside it,
        not merely overlapping it.

        This is deliberately not a strict ST_Within. Tract/ZIP boundaries
        come from different sources than county boundaries and disagree by
        hairline slivers, so a tract that is unambiguously in Fresno County
        can still poke a few meters into Madera; strict containment drops
        ~15% of Fresno's tracts and a third of its ZIPs on real data. Those
        excursions are all well under 0.1% of area, while the smallest
        genuine straddle is several percent, so 99% separates the two.
        """
        return self._area_fraction_inside(geometry, min_fraction)

    def overlapping(self, geometry: GEOSGeometry, min_fraction: float = 0.01):
        """
        Filters regions with at least `min_fraction` of their own area inside
        the given geometry. The mirror of contained_within: that one asks
        "is the region (essentially) inside?", this one "does the region
        meaningfully reach in?". The small floor drops the hairline slivers
        where neighbouring boundaries from different sources disagree (a ZIP
        that merely touches a county's edge), while keeping real overlaps.
        """
        return self._area_fraction_inside(geometry, min_fraction)

    def combined_geometry(self) -> GEOSGeometry:
        """
        Returns a MultiPolygon representing the union of all geometries in the queryset.
        """
        return self.aggregate(combined=Union('boundary__geometry'))['combined']


class BoundaryQuerySet(models.QuerySet):
    def render_map(self, **kwargs):
        geometries = [boundary.geometry for boundary in self]
        return maps.from_geometries(*geometries, **kwargs)

    def to_dataframe(self, fields=None, crs='EPSG:4326') -> gpd.GeoDataFrame:
        """
        Convert the queryset to a GeoDataFrame.
        Assumes 'geometry' is a GEOSGeometry field and uses WGS84 (EPSG:4326) by default.
        """
        fields = fields or [
            'id', 'region_id', 'region__external_id', 'region__name',
            'version', 'created', 'metadata', 'geometry'
        ]

        records = []
        for row in self.values(*fields):
            row['geometry'] = load_wkt(row['geometry'].wkt)
            records.append(row)

        return gpd.GeoDataFrame(records, geometry='geometry', crs=crs)


class SearchResultIterable(ModelIterable):
    """Model instances from LocationQuerySet.search(), with `search_rank` and
    `search_similarity` split out of the row's `search_key` (rank * 10 + similarity)
    in Python rather than SQL, where each would repeat the whole key expression."""

    def __iter__(self):
        for obj in super().__iter__():
            obj.search_rank = int(obj.search_key // 10)
            obj.search_similarity = obj.search_key - obj.search_rank * 10
            yield obj


class LocationQuerySet(models.QuerySet):
    """Schools and child-care centers (regions.Location)."""

    # The state licenses a day care center and a school-age center (or an
    # infant room and a preschool) separately, at one address under one name.
    # Child-care licenses of the same name about this close (in degrees, the
    # point field's own units: ~150 m north-south, a little less east-west in
    # the Valley) are one place.
    SAME_PLACE_DEGREES = 0.00135

    def _same_place(self):
        """The current child-care licenses at the outer row's place (its own included): same name, case and spacing aside, within SAME_PLACE_DEGREES."""
        from camp.apps.regions.models import Location
        return (
            Location.objects.annotate(name_key=Lower(Trim('name')))
            .filter(type=Location.Type.CHILD_CARE, name_key=OuterRef('name_key'), point__dwithin=(OuterRef('point'), self.SAME_PLACE_DEGREES))
        )

    def one_per_place(self):
        """
        One row per place: a child-care center's several licenses (_same_place)
        stand as the one with the lowest code, the rest left out, every row
        annotated `licenses` -- how many it stands for (1 for schools and a
        single license). A school and a child-care center on one site stay two.

        The lowest code rather than the lowest pk, so the representative is
        the same in every environment. Facility numbers are fixed-width
        digit strings, so string order is numeric order.
        """
        from camp.apps.regions.models import Location
        same = self._same_place()
        child_care = Q(type=Location.Type.CHILD_CARE)
        count = Subquery(same.order_by().values('type').annotate(n=Count('pk')).values('n')[:1], output_field=models.IntegerField())
        return (
            self.annotate(name_key=Lower(Trim('name')))
            .exclude(child_care & models.Exists(same.filter(external_id__lt=OuterRef('external_id'))))
            .annotate(licenses=models.Case(models.When(child_care, then=count), default=models.Value(1), output_field=models.IntegerField()))
        )

    # Trigram word similarity at or above this is a (typo-tolerant) match,
    # as in Region.objects.search_regions.
    SEARCH_SIMILARITY = 0.3
    # The most words a town part can have ("san luis obispo").
    SEARCH_TOWN_WORDS = 3

    @classmethod
    def _search_splits(cls, q):
        """(name text, town text or None) pairs to try for `q`: the whole of it, then each
        name + town split, the town being the last or the first 1-3 words."""
        text = ' '.join(q.split())
        words = text.lower().split(' ')
        splits = [(text, None)]
        for k in range(1, min(cls.SEARCH_TOWN_WORDS, len(words) - 1) + 1):
            splits.append((' '.join(words[:-k]), ' '.join(words[-k:])))
            splits.append((' '.join(words[k:]), ' '.join(words[:k])))
        return splits

    def search(self, q):
        """
        Name search: current rows (one per place) whose name contains `q` or is
        trigram-similar to it, or -- for a query of two or more words -- whose
        name matches a name part and whose city starts with the rest (the town).

        `search_rank`, best first:
          6  the name starts with q
          5  a word in the name starts with q (after a space, /, - or ()
          4, 3, 2  a town split matched: its name part matched at tier 3
                   (prefix), 2 (word start) or 1 (substring or similarity)
          1  q is only in the name somewhere, or trigram-similar to it
        so a query word that happens to start a town name ("fresno high",
        "lincoln elementary" by Lincoln Village) doesn't outrank the name
        itself. `search_similarity` is the trigram word similarity of the best
        split's name text. Rows are ordered by both, then city, name, source
        and code (city: the linked city/CDP region's name, else `city_name`).
        Doesn't check `q`'s length; a blank `q` matches nothing.

        Each split scores rank * 10 + similarity in one CASE, and the row's
        `search_key` annotation is the greatest of them: one expression for the
        filter and the sort, rather than one per split per use. `search_rank`
        and `search_similarity` are split out of it in Python as rows are read
        (SearchResultIterable), so they're attributes, not SQL annotations:
        filter and order on `search_key`. The result chains like any queryset
        (filter, select_related, slicing); `.values()` drops the two attributes.
        """
        if not q.strip():
            return self.none()

        qs = self.one_per_place().alias(
            city_key=Lower(Coalesce(NullIf('city__name', Value('')), 'city_name')),
        )
        keys = [self._search_key(name, town) for name, town in self._search_splits(q)]
        qs = qs.annotate(search_key=keys[0] if len(keys) == 1 else Greatest(*keys))
        qs = qs.filter(search_key__gte=10).order_by('-search_key', 'city_key', Lower('name'), 'source', 'external_id')
        qs._iterable_class = SearchResultIterable
        return qs

    # search_rank for each tier of a whole-query match, and of a town split's name part.
    _WHOLE_RANKS = {3: 6, 2: 5, 1: 1}
    _TOWN_RANKS = {3: 4, 2: 3, 1: 2}

    def _search_key(self, name, town=None):
        """
        One split's score, rank * 10 + similarity (0 when it doesn't match).
        Cheapest test first, since most rows match nothing: a town split checks
        the town, then the name's containment gates the prefix and word-start
        tests, and only a name that doesn't contain the text pays for the
        similarity threshold.
        """
        similarity = TrigramWordSimilarity(Value(name), 'name')
        word_start = Q()
        for sep in ' /-(':
            word_start |= Q(name__icontains=sep + name)
        ranks = self._TOWN_RANKS if town else self._WHOLE_RANKS
        tier_rank = Case(
            When(name__istartswith=name, then=ranks[3] * 10),
            When(word_start, then=ranks[2] * 10),
            default=ranks[1] * 10,
        )
        whens = [
            When(name__icontains=name, then=tier_rank + similarity),
            When(GreaterThanOrEqual(similarity, self.SEARCH_SIMILARITY), then=ranks[1] * 10 + similarity),
        ]
        if town:
            whens.insert(0, When(~self._in_town(town), then=Value(0.0)))
        return Case(*whens, default=Value(0.0), output_field=FloatField())

    def _in_town(self, town):
        """Rows whose city starts with `town`: the linked city/CDP region's name, or the
        row's own `city_name` when none is linked. An uncorrelated subquery of city ids
        rather than the join, so the whole search filter applies at the location scan,
        ahead of one_per_place()'s per-row subquery. all_objects, like the join: a row's
        linked city counts even if retired, and it skips the retired_at scan."""
        from camp.apps.regions.models import Region
        cities = Region.all_objects.filter(type__in=[Region.Type.CITY, Region.Type.CDP], name__istartswith=town)
        return Q(city__in=cities.values('pk')) | Q(city__isnull=True, city_name__istartswith=town)
