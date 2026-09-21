import calendar
import hashlib
import math
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import unquote, urlencode

from django.conf import settings
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Case, Count, F, FloatField, IntegerField, OuterRef, Q, Subquery, Sum, Value, When
from django.db.models.functions import Coalesce, Lower, TruncMonth
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import cached_property

import vanilla

from camp.api.v2.pesticides.sections import radius_bbox
from camp.apps.pesticides import maps, notes, places, stats
from camp.apps.pesticides.forms import (
    ChemicalFilterForm, CommodityFilterForm, NoticeFilterForm, ProductFilterForm, RecordsFilterForm,
)
from camp.apps.pesticides.models import (
    Chemical, Commodity, PesticideNotice, PesticideUse, PesticideUseRollup, PesticideUseTotal,
    Product, ProductChemical,
)
from camp.apps.regions.models import Region
from camp.utils import leaflet

# Sentinel for "sqid didn't resolve to an object" in ExplorerListMixin.related.
# Not Http404 -- that's an exception class, not a value, and using it as a
# dict value / membership check reads as if it might be raised.
MISSING = object()

def county_options():
    """(slug, name) for the county scope picker, in name order."""
    return list(Region.objects.filter(type=Region.Type.COUNTY).order_by('name').values_list('slug', 'name'))


def year_context(year, all_years=False, county=None, county_scope=True):
    """
    Context every explorer page needs for the scope pickers (year and county)
    and the scope-pinned links. `county_scope=False` hides the county picker
    on pages that are already narrower than a county (a place, a section);
    the county still rides along in their links.
    """
    return {
        'year': year,
        'all_years': all_years,
        # '2023' or '2014-2023' -- what headings say instead of the raw year,
        # and the flag templates test for "is a year in play at all".
        'year_label': stats.year_label(year, all_years),
        'latest_year': stats.latest_year(),
        'year_options': stats.available_years(),
        'county': county,
        'county_options': county_options() if county_scope else [],
        'scope_qs': stats.scope_query(year, all_years, county),
    }


def scope_county(request):
    """The county the explorer is scoped to (`?county=<slug>`), or None."""
    return resolve_county(request.GET.get('county'))


# Public pages link developers to the documentation, never to raw endpoints.
API_DOCS_URL = '/api/2.0/docs/#tag/pesticides'
CLIENT_DOCS_URL = 'https://sjvair.github.io/sjvair-python/client/resources/pesticides.html'


def lbs_subquery(field, year, lbs_field='lbs_chemical', county=None, all_years=False, related=None):
    """
    Sum of pounds in `year` (or every loaded year) and `county`, when given,
    for the outer row, via `PesticideUseTotal.<field>`. With `related`
    ({'chemical': <Chemical>, ...}, a list's active entity filters) the sum
    is the pair's pounds from the rollup instead: a commodity list filtered
    to one chemical shows that chemical's pounds on each commodity, not the
    commodity's total.
    """
    if related:
        rows = PesticideUseRollup.objects.filter(**{field: OuterRef('pk')}, **related)
    else:
        rows = PesticideUseTotal.objects.filter(**{field: OuterRef('pk')})
    if not all_years:
        rows = rows.filter(year=year)
    if county is not None:
        rows = rows.filter(county=county)
    return Subquery(
        rows
        .values(field)
        .annotate(total=Sum(lbs_field))
        .values('total'),
        output_field=FloatField(),
    )


def count_subquery(model, field, count_field):
    """Count of `model` rows whose `field` points at the outer row, independent of outer joins."""
    return Subquery(
        model.objects.filter(**{field: OuterRef('pk')})
        .values(field)
        .annotate(n=Count(count_field))
        .values('n'),
        output_field=IntegerField(),
    )


def related_pks(field, obj, target, year=None, county=None, all_years=False):
    """
    PKs of `target` (a PesticideUseRollup FK name) that share a rollup row
    with obj, in `year` (or any loaded year) and `county` when given, so a
    list filtered to an entity is scoped the way its pounds column is.
    """
    rows = PesticideUseRollup.objects.filter(**{field: obj})
    if year and not all_years:
        rows = rows.filter(year=year)
    if county is not None:
        rows = rows.filter(county=county)
    return rows.values(target)


def resolve_related(get, models):
    """
    Resolve `{param: obj}` from sqid query params for `models`
    ({param: Model or QuerySet}). A queryset constrains what the param may
    resolve to -- e.g. `section` only ever matches an MTRS region, so a
    county's sqid passed as `?section=` is MISSING rather than a silent
    mismatch. An unresolved sqid maps to MISSING rather than being silently
    ignored, so callers can turn that into an empty queryset instead of a 500
    or a filter that quietly matches everything.
    """
    related = {}
    for param, source in models.items():
        value = get.get(param)
        if value:
            queryset = source if hasattr(source, 'filter') else source.objects.all()
            related[param] = queryset.filter(sqid=value).first() or MISSING
    return related


def resolve_county(slug):
    if not slug:
        return None
    return Region.objects.filter(type=Region.Type.COUNTY, slug=slug).select_related('boundary').first()


def resolve_point_and_radius(data):
    """
    lat/lng come off a form's FloatFields, which already reject `nan`/`inf`
    strings during is_valid() -- that's what keeps GEOS from being handed a
    non-finite coordinate below. Range-check the parsed floats the same way
    the sections API does (camp/api/v2/pesticides/sections.py) so an
    out-of-range lat/lng (e.g. lat=200) is treated as "no point" rather than
    reaching Point(). An off-list radius is clamped to 1 mile.
    """
    lat, lng = data.get('lat'), data.get('lng')
    if lat is None or lng is None:
        return None, None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None, None
    try:
        radius = int(data.get('radius') or 1)
    except (TypeError, ValueError):
        radius = 1
    if radius not in places.RADIUS_CHOICES:
        radius = 1
    return Point(lng, lat, srid=4326), radius


def clear_url(request, *params):
    data = request.GET.copy()
    for param in params:
        data.pop(param, None)
    data.pop('page', None)
    encoded = data.urlencode()
    return f'{request.path}?{encoded}' if encoded else request.path


def paginated_count(kwargs):
    paginator = kwargs.get('paginator')
    return paginator.count if paginator else len(kwargs.get('object_list', []))


# Years `datetime()` can safely bracket (and that a notice could plausibly
# carry). Anything outside is treated as "no year filter" rather than raising.
MIN_FILTER_YEAR = 1900
MAX_FILTER_YEAR = 2100


def local_month_bounds(year, month=None):
    """
    None for a year outside MIN/MAX_FILTER_YEAR -- callers treat that as "no
    year filter" instead of letting `datetime(year + 1, ...)` raise.

    Otherwise [start, end) as America/Los_Angeles-aware datetimes for `year` (or
    `year`/`month`), for filtering `scheduled_application` directly. Filtering
    a raw field with these bounds -- rather than comparing a
    TruncMonth(..., tzinfo=...) annotation via `__year`/`__month` -- sidesteps
    a Django/Postgres quirk: TruncMonth's tzinfo shifts the value with
    `AT TIME ZONE`, producing a naive timestamp that a later `__year`/`__month`
    lookup then re-interprets in the DB session's timezone (UTC here), which
    silently shifts the match window by the UTC offset.
    """
    if year is None or not (MIN_FILTER_YEAR <= year <= MAX_FILTER_YEAR):
        return None
    tz = settings.DEFAULT_TIMEZONE
    start = datetime(year, month or 1, 1, tzinfo=tz)
    if month:
        end = datetime(year + 1, 1, 1, tzinfo=tz) if month == 12 else datetime(year, month + 1, 1, tzinfo=tz)
    else:
        end = datetime(year + 1, 1, 1, tzinfo=tz)
    return start, end


def centroid(region):
    """'lat,lng' of a region's boundary, as section_map_config wants it."""
    point = region.boundary.geometry.centroid
    return f'{point.y:.4f},{point.x:.4f}'


def resolve_map_center(*, section=None, region=None, point=None, radius=None, county=None):
    """(center, zoom, radius) for section_map_config, in priority order: an
    explicit section, then region, then point+radius, then county."""
    if section not in (None, MISSING) and section.boundary_id:
        return centroid(section), 13, None
    if region not in (None, MISSING) and region.boundary_id:
        return centroid(region), 10, None
    if point is not None:
        return f'{point.y:.4f},{point.x:.4f}', 12, radius
    if county is not None and county.boundary_id:
        return centroid(county), 9, None
    return None, None, None


class ExplorerListMixin:
    paginate_by = 50
    form_class = None
    section = None
    sort_fields = {}
    default_sort = 'name'
    related_models = {}
    # The PesticideUseTotal/PesticideUseRollup FK that points at this list's model.
    rollup_field = None

    def dispatch(self, request, *args, **kwargs):
        self.year, self.all_years = stats.resolve_year_param(request.GET.get('year'))
        self.county = scope_county(request)
        self.form = self.form_class(request.GET)
        self.form.is_valid()
        self.related = self.get_related_objects()
        return super().dispatch(request, *args, **kwargs)

    def apply_usage(self, queryset):
        """
        Keep only entities with reported use in the selected year -- or in any
        loaded year, with `?year=all` -- and county, when one is chosen, so the
        list matches its pounds column and the landing page's "used" counts
        rather than listing every registered name.
        """
        if not self.rollup_field or not (self.year or self.all_years):
            return queryset
        used = PesticideUseTotal.objects.all()
        if not self.all_years:
            used = used.filter(year=self.year)
        if self.county is not None:
            used = used.filter(county=self.county)
        return queryset.filter(pk__in=used.values(self.rollup_field))

    def get_search_query(self):
        return (self.form.cleaned_data.get('q') or '').strip()

    def get_related_objects(self):
        return resolve_related(self.request.GET, self.related_models)

    def apply_related(self, queryset):
        for param, obj in self.related.items():
            if obj is MISSING:
                return queryset.none()
            queryset = self.filter_related(queryset, param, obj)
        return queryset

    def filter_related(self, queryset, param, obj):
        """Rows sharing a use record with `obj` in the list's year and county (see related_pks)."""
        return queryset.filter(pk__in=related_pks(param, obj, self.rollup_field, self.year, self.county, self.all_years))

    def apply_filters(self, queryset, data):
        return queryset

    def annotate_queryset(self, queryset, year):
        return queryset

    def related_filters(self):
        """The list's resolved entity filters, as rollup lookups."""
        return {param: obj for param, obj in self.related.items() if obj is not MISSING}

    def get_sort(self):
        param = self.request.GET.get('sort') or ''
        key = param.lstrip('-')
        if key not in self.sort_fields:
            if self.get_search_query():
                return None, None, False
            param = self.default_sort
            key = param.lstrip('-')
        return param, self.sort_fields[key], param.startswith('-')

    def get_queryset(self):
        queryset = self.model.objects.all()
        query = self.get_search_query()
        if query:
            queryset = queryset.search(query)
        queryset = self.apply_related(queryset)
        queryset = self.apply_filters(queryset, self.form.cleaned_data)
        queryset = self.apply_usage(queryset)
        queryset = self.annotate_queryset(queryset, self.year)
        self.sort, field, desc = self.get_sort()
        if field:
            expr = F(field).desc(nulls_last=True) if desc else F(field).asc(nulls_last=True)
            queryset = queryset.order_by(expr, 'name', 'pk')
        return queryset

    def get_summary_sentence(self, count):
        noun = self.section if count != 1 else self.section[:-1]
        if self.section == 'commodities' and count == 1:
            noun = 'commodity'
        parts = [f'{count:,} {noun}']
        query = self.get_search_query()
        if query:
            parts.append(f'matching "{query}"')
        parts.extend(self.describe_filters(self.form.cleaned_data))
        where = f' in {self.county.name}' if self.county is not None else ''
        if self.all_years:
            parts.append(f'used{where} {stats.year_label(None, True)}')
        elif self.year:
            parts.append(f'used{where} in {self.year}')
        elif where:
            parts.append(f'used{where}')
        for param, obj in self.related.items():
            if obj is not MISSING:
                parts.append(f'linked to {obj.display_name}')
        return ' '.join(parts)

    def describe_filters(self, data):
        return []

    # Under an entity filter the pounds column is the pair's pounds (see
    # lbs_subquery), and the header says so: "Lbs of Sodium fluoroacetate",
    # "Lbs via Roundup Pro", "Lbs on Almond".
    LBS_LABEL_PREPOSITIONS = {'chemical': 'of', 'product': 'via', 'commodity': 'on'}

    def lbs_label(self):
        parts = ['Lbs']
        related = self.related_filters()
        for param in ('chemical', 'product', 'commodity'):
            if param in related:
                parts.append(f'{self.LBS_LABEL_PREPOSITIONS[param]} {related[param].display_name}')
        return ' '.join(parts) if len(parts) > 1 else 'Lbs applied'

    def get_context_data(self, **kwargs):
        count = paginated_count(kwargs)
        return super().get_context_data(
            form=self.form,
            query=self.get_search_query(),
            sort=self.sort,
            result_count=count,
            **year_context(self.year, self.all_years, self.county),
            summary_sentence=self.get_summary_sentence(count),
            related={k: v for k, v in self.related.items() if v is not MISSING},
            lbs_label=self.lbs_label(),
            section=self.section,
            **kwargs,
        )


class ChemicalList(ExplorerListMixin, vanilla.ListView):
    model = Chemical
    form_class = ChemicalFilterForm
    template_name = 'pesticides/chemical-list.html'
    section = 'chemicals'
    sort_fields = {'name': 'sort_name', 'lbs': 'lbs_applied', 'products': 'product_count', 'iarc': 'iarc_group'}
    default_sort = '-lbs'
    related_models = {'product': Product, 'commodity': Commodity}
    rollup_field = 'chemical'

    def apply_filters(self, queryset, data):
        if data.get('category'):
            queryset = queryset.filter(categories__overlap=data['category'])
        if data.get('iarc_group'):
            queryset = queryset.filter(iarc_group=data['iarc_group'])
        return queryset

    def annotate_queryset(self, queryset, year):
        # "Sort by name" follows the shown name (Chemical.display_name): a
        # CDPR name with no letters sorts under its CompTox name; otherwise
        # CDPR's, case-insensitively, since the shown name differs only in case.
        queryset = queryset.annotate(
            product_count=Coalesce(count_subquery(ProductChemical, 'chemical', 'product'), 0),
            sort_name=Lower(Case(
                When(Q(name__regex=r'^[^A-Za-z]*$') & ~Q(preferred_name=''), then=F('preferred_name')),
                default=F('name'),
            )),
        )
        if year or self.all_years:
            queryset = queryset.annotate(
                lbs_applied=lbs_subquery('chemical', year, county=self.county, all_years=self.all_years, related=self.related_filters())
            )
        else:
            queryset = queryset.annotate(lbs_applied=F('chem_code') * 0.0)
        return queryset

    def describe_filters(self, data):
        parts = []
        if data.get('category'):
            labels = dict(Chemical.Category.choices)
            parts.append('in ' + ' or '.join(str(labels[c]) for c in data['category']))
        if data.get('iarc_group'):
            parts.append(f'in IARC Group {data["iarc_group"]}')
        return parts


class ExplorerRedirect(vanilla.GenericView):
    model = None

    def get(self, request, sqid):
        obj = self.model.objects.filter(sqid=sqid).first()
        if obj is None:
            raise Http404
        # The map's popup links arrive here with the scope (`?year=`,
        # `?county=`); it carries over to the slugged URL.
        query = request.GET.urlencode()
        return redirect(obj.get_absolute_url() + (f'?{query}' if query else ''), permanent=True)


FIND_AREA_PLACES_CACHE_KEY = 'pesticides:find-area-places'
FIND_AREA_PLACES_TTL = 60 * 60 * 24

# Short, human labels for the "Find your area" dropdown. Region.Type's own
# labels read a little long there ("ZIP Code"), and the dropdown shows the
# type as a trailing tag: "93725 · ZIP".
FIND_AREA_TYPE_LABELS = {
    Region.Type.COUNTY: 'County',
    Region.Type.CITY: 'City',
    Region.Type.ZIPCODE: 'ZIP',
    Region.Type.PLACE: 'Place',
    Region.Type.SCHOOL_DISTRICT: 'School district',
}


def find_area_place_list():
    """
    Every place we have a page for, as `{name, type, type_label, short_name,
    url}` sorted by name. Embedded in the landing page as JSON so the search
    box can match our own places in the browser, with no request per
    keystroke. Cached for a day -- regions change on import, not on traffic.
    """
    place_list = cache.get(FIND_AREA_PLACES_CACHE_KEY)
    if place_list is None:
        regions = (Region.objects
            .filter(type__in=places.PLACE_REGION_TYPES, boundary__isnull=False)
            .order_by('name')
            .values_list('sqid', 'slug', 'name', 'type')
        )
        place_list = [{
            'name': name,
            'type': region_type,
            'type_label': FIND_AREA_TYPE_LABELS.get(region_type, region_type),
            # "Fresno County" -> "Fresno" for the county links row.
            'short_name': name[:-len(' County')] if name.endswith(' County') else name,
            'url': reverse('pesticides:region', kwargs={'sqid': sqid, 'slug': slug}),
        } for sqid, slug, name, region_type in regions]
        # Synthetic Place regions carry the same names as the cities they
        # were built from; showing "Selma · City" and "Selma · Place" side by
        # side just confuses people, so keep the city.
        city_names = {p['name'] for p in place_list if p['type'] == Region.Type.CITY}
        place_list = [
            p for p in place_list
            if not (p['type'] == Region.Type.PLACE and p['name'] in city_names)
        ]
        cache.set(FIND_AREA_PLACES_CACHE_KEY, place_list, FIND_AREA_PLACES_TTL)
    return place_list


class Home(vanilla.TemplateView):
    template_name = 'pesticides/home.html'

    def get_context_data(self, **kwargs):
        year, all_years = stats.resolve_year_param(self.request.GET.get('year'))
        county = scope_county(self.request)
        data = stats.landing_stats(year, all_years, county)
        county_map = maps.county_map(data['by_county']) if data['by_county'] else None
        find_area_places = find_area_place_list()
        # landing_stats carries `year`/`latest_year` too; year_context wins on overlap.
        return super().get_context_data(
            section=None,
            county_map=county_map,
            api_docs_url=API_DOCS_URL,
            client_docs_url=CLIENT_DOCS_URL,
            find_area_places=find_area_places,
            find_area_counties=[
                place for place in find_area_places
                if place['type'] == Region.Type.COUNTY
            ],
            maptiler_key=settings.MAPTILER_API_KEY,
            focus_find=self.request.GET.get('find') == '1',
            **{**data, **year_context(year, all_years, county)},
            **kwargs,
        )


class About(vanilla.TemplateView):
    template_name = 'pesticides/about.html'

    def get_context_data(self, **kwargs):
        return super().get_context_data(
            section=None,
            years=stats.years_loaded(),
            latest_year=stats.latest_year(),
            api_docs_url=API_DOCS_URL,
            client_docs_url=CLIENT_DOCS_URL,
            **kwargs,
        )


class ProductList(ExplorerListMixin, vanilla.ListView):
    model = Product
    form_class = ProductFilterForm
    template_name = 'pesticides/product-list.html'
    section = 'products'
    sort_fields = {'name': 'name', 'lbs': 'lbs_applied', 'chemicals': 'chemical_count', 'reg': 'reg_number'}
    default_sort = 'name'
    related_models = {'chemical': Chemical, 'commodity': Commodity}
    rollup_field = 'product'

    def apply_filters(self, queryset, data):
        for name in ('fumigant', 'california_restricted'):
            value = self.form.bool_value(name)
            if value is not None:
                queryset = queryset.filter(**{name: value})
        return queryset

    def annotate_queryset(self, queryset, year):
        queryset = queryset.annotate(
            chemical_count=Coalesce(count_subquery(ProductChemical, 'product', 'chemical'), 0)
        )
        if year or self.all_years:
            queryset = queryset.annotate(
                lbs_applied=lbs_subquery('product', year, lbs_field='lbs_product', county=self.county, all_years=self.all_years, related=self.related_filters())
            )
        else:
            queryset = queryset.annotate(lbs_applied=F('prodno') * 0.0)
        return queryset

    def describe_filters(self, data):
        parts = []
        if self.form.bool_value('fumigant') is True:
            parts.append('that are fumigants')
        if self.form.bool_value('fumigant') is False:
            parts.append('that are not fumigants')
        if self.form.bool_value('california_restricted') is True:
            parts.append('restricted in California')
        if self.form.bool_value('california_restricted') is False:
            parts.append('not restricted in California')
        return parts


class CommodityList(ExplorerListMixin, vanilla.ListView):
    model = Commodity
    rollup_field = 'commodity'
    form_class = CommodityFilterForm
    template_name = 'pesticides/commodity-list.html'
    section = 'commodities'
    sort_fields = {'name': 'name', 'lbs': 'lbs_applied', 'chemicals': 'chemical_count', 'site': 'site_code'}
    default_sort = '-lbs'
    related_models = {'chemical': Chemical, 'product': Product}

    def annotate_queryset(self, queryset, year):
        if not year and not self.all_years:
            return queryset.annotate(lbs_applied=F('pk') * 0.0, chemical_count=F('pk') * 0)
        return queryset.annotate(
            lbs_applied=lbs_subquery('commodity', year, county=self.county, all_years=self.all_years, related=self.related_filters()),
            chemical_count=self.chemical_count(year),
        )

    def chemical_count(self, year):
        """
        Distinct chemicals applied to each commodity, still sortable in SQL.
        For one year that's a correlated subquery on the (year, county,
        commodity, chemical) index. Across every year there's no year to lead
        with, so the counts come from one cached group-by, inlined here as a
        CASE over the ~250 commodities that have any use at all.
        """
        if self.all_years:
            counts = stats.commodity_chemical_counts(self.county)
            if not counts:
                return Value(0, output_field=IntegerField())
            return Case(
                *[When(pk=pk, then=Value(n)) for pk, n in counts.items()],
                default=Value(0),
                output_field=IntegerField(),
            )
        rows = PesticideUseRollup.objects.filter(commodity=OuterRef('pk'), year=year)
        if self.county is not None:
            rows = rows.filter(county=self.county)
        return Coalesce(Subquery(
            rows
            .values('commodity')
            .annotate(n=Count('chemical', distinct=True))
            .values('n'),
        ), 0)


class ExplorerDetailMixin:
    lookup_field = 'sqid'
    lookup_url_kwarg = 'sqid'
    section = None
    lbs_field = 'lbs_chemical'
    use_field = None          # PesticideUse FK name for this entity
    api_param = None          # v2 API query param name, shown as a hint for developers
    has_notices = True

    def get_uses(self):
        uses = PesticideUse.objects.filter(**{self.use_field: self.object})
        if self.county is not None:
            uses = uses.filter(county=self.county)
        return uses

    def get_rollup(self):
        rows = PesticideUseRollup.objects.filter(**{self.use_field: self.object})
        if self.county is not None:
            rows = rows.filter(county=self.county)
        return rows

    def get_notices(self):
        return PesticideNotice.objects.none()

    def get_notes(self):
        return []

    def api_value(self):
        raise NotImplementedError

    def get_related(self):
        """Return (related_a, related_b) dicts. Each: {title, kind, rows, show_all_url}."""
        raise NotImplementedError

    def cached_stat(self, name, build):
        """
        An all-years aggregate reads every loaded year of this entity's rollup
        rows -- hundreds of thousands for a widely-used chemical, and seconds
        per page. They only change on import, so cache them; a single year is
        cheap enough to compute per request.
        """
        if not self.all_years:
            return build()
        scope = self.county.slug if self.county is not None else ''
        return stats.cached(stats.all_years_key('detail', self.use_field, self.object.pk, scope, name), build)

    def top_related(self, field, lbs_field=None, limit=10):
        lbs_field = lbs_field or self.lbs_field
        return self.cached_stat(f'top:{field}:{lbs_field}:{limit}', lambda: stats.top_related(
            self.get_rollup(), self.year, field, lbs_field, limit, all_years=self.all_years,
        ))

    def related_card(self, title, kind, rows, list_url_name, param, show_pct=False, show_lbs=True, complete=False):
        """
        show_pct: rows carry pct_active (only product<->chemical relations do).
        show_lbs: rows carry pounds (a product's ingredient list does not).
        complete: every related object is already listed, so no "Show all".
        """
        scope = stats.scope_param(self.year, self.all_years, self.county)
        return {
            'title': title,
            'kind': kind,
            'rows': rows,
            'show_pct': show_pct,
            'show_lbs': show_lbs,
            'complete': complete,
            'show_all_url': reverse(list_url_name) + f'?{param}={self.object.sqid}' + (
                f'&{scope}' if scope else ''
            ),
        }

    def get_summary_sentence(self, totals, label, top, verb='on'):
        if not totals['applications'] or not label:
            return ''
        if self.county is not None:
            sentence = f'Applied in {self.county.name} in {label}'
        else:
            sentence = f'Applied in {totals["counties"]} of {stats.SJV_COUNTY_COUNT} SJV counties in {label}'
        names = [r.obj.display_name for r in top[:2]]
        if names:
            joined = ' and '.join(names)
            sentence += f', mostly {verb} {joined}' if verb else f', mostly {joined}'
        return sentence + '.'

    def get_context_data(self, **kwargs):
        year, all_years = stats.resolve_year_param(self.request.GET.get('year'))
        self.year, self.all_years = year, all_years
        self.county = scope_county(self.request)
        uses = self.get_uses()
        rows = self.get_rollup()
        notices = self.get_notices()
        scope = stats.scope_param(year, all_years, self.county)
        totals = self.cached_stat('totals', lambda: stats.year_totals(rows, year, self.lbs_field, all_years=all_years))
        related_a, related_b = self.get_related()
        context = super().get_context_data(
            section=self.section,
            years=stats.years_loaded(),
            **year_context(year, all_years, self.county),
            county_total=stats.SJV_COUNTY_COUNT,
            totals=totals,
            by_year=stats.by_year(rows, self.lbs_field),
            by_county=self.cached_stat('by_county', lambda: stats.by_county(rows, year, self.lbs_field, all_years=all_years)),
            by_month=self.cached_stat('by_month', lambda: stats.by_month(rows, year, self.lbs_field, all_years=all_years)) if (year or all_years) else [],
            related_a=related_a,
            related_b=related_b,
            records_url=reverse('pesticides:records') + f'?{self.use_field}={self.object.sqid}' + (
                f'&{scope}' if scope else ''
            ),
            has_notices=self.has_notices,
            notices_url=(
                reverse('pesticides:notice-list') + f'?{self.use_field}={self.object.sqid}'
                + (f'&county={self.county.slug}' if self.county is not None else '')
            ) if self.has_notices else '',
            upcoming=stats.upcoming_notices(notices) if self.has_notices else [],
            upcoming_by_county=stats.upcoming_by_county(notices) if self.has_notices else [],
            upcoming_count=stats.upcoming_count(notices) if self.has_notices else 0,
            notice_window=stats.notice_window(),
            api_docs_url=API_DOCS_URL,
            client_docs_url=CLIENT_DOCS_URL,
            api_filter=f'{self.api_param}={self.api_value()}',
            notes=notes.notes_for(self.get_notes()),
            **kwargs,
        )
        context['summary_sentence'] = self.get_summary_sentence(totals, context['year_label'], self.summary_top(context))
        # The section map, filtered to this entity, shows where it's applied;
        # the county choropleth stays as the map's noscript fallback.
        context['map_config'] = section_map_config(
            year, all_years=all_years, show_notices=False,
            county=self.county.slug if self.county is not None else None,
            **{self.use_field: self.object},
        )
        context['full_map_url'] = reverse('pesticides:map') + f'?{self.use_field}={self.object.sqid}' + (
            f'&{scope}' if scope else ''
        )
        context['county_map'] = maps.county_map(context['by_county']) if context['by_county'] else None
        return context

    def summary_top(self, context):
        return context['related_b']['rows']


def with_pct_active(rows, pct_by_pk):
    for row in rows:
        row.pct_active = pct_by_pk.get(row.obj.pk)
    return rows


class ChemicalDetail(ExplorerDetailMixin, vanilla.DetailView):
    model = Chemical
    template_name = 'pesticides/chemical-detail.html'
    section = 'chemicals'
    use_field = 'chemical'
    api_param = 'chemical'

    def api_value(self):
        return self.object.chem_code

    def get_notices(self):
        return PesticideNotice.objects.filter(chemicals=self.object)

    def get_notes(self):
        return notes.keys_for_chemical(self.object)

    def get_related(self):
        pct = dict(self.object.product_chemicals.values_list('product_id', 'pct_active'))
        products = with_pct_active(self.top_related('product'), pct)
        commodities = self.top_related('commodity')
        return (
            self.related_card('Products containing this chemical', 'products', products, 'pesticides:product-list', 'chemical', show_pct=True),
            self.related_card('Applied to', 'commodities', commodities, 'pesticides:commodity-list', 'chemical'),
        )


class ProductDetail(ExplorerDetailMixin, vanilla.DetailView):
    model = Product
    template_name = 'pesticides/product-detail.html'
    section = 'products'
    use_field = 'product'
    lbs_field = 'lbs_product'
    api_param = 'product'

    def get_queryset(self):
        return Product.objects.prefetch_related('chemicals')

    def api_value(self):
        return self.object.prodno

    def get_notices(self):
        return PesticideNotice.objects.filter(products=self.object)

    def get_notes(self):
        return notes.keys_for_product(self.object)

    def get_related(self):
        pct = dict(self.object.product_chemicals.values_list('chemical_id', 'pct_active'))
        # Active ingredients are a property of the product, not of use records,
        # so list all of them (ranked by pct_active) rather than by pounds.
        chemicals = [
            SimpleNamespace(obj=c, lbs=None, pct_active=pct.get(c.pk))
            for c in sorted(self.object.chemicals.all(), key=lambda c: -(pct.get(c.pk) or 0))
        ]
        commodities = self.top_related('commodity')
        return (
            self.related_card('Active ingredients', 'chemicals', chemicals, 'pesticides:chemical-list', 'product', show_pct=True, show_lbs=False, complete=True),
            self.related_card('Applied to', 'commodities', commodities, 'pesticides:commodity-list', 'product'),
        )


class CommodityDetail(ExplorerDetailMixin, vanilla.DetailView):
    model = Commodity
    template_name = 'pesticides/commodity-detail.html'
    section = 'commodities'
    use_field = 'commodity'
    api_param = 'commodity'
    has_notices = False

    def api_value(self):
        return self.object.site_code

    def get_related(self):
        return (
            self.related_card('Chemicals applied', 'chemicals', self.top_related('chemical'), 'pesticides:chemical-list', 'commodity'),
            self.related_card('Products applied', 'products', self.top_related('product', 'lbs_product'), 'pesticides:product-list', 'commodity'),
        )

    def summary_top(self, context):
        return context['related_a']['rows']

    def get_summary_sentence(self, totals, label, top, verb=None):
        return super().get_summary_sentence(totals, label, top, verb=None)


SJV_CENTER = '36.75,-119.80'
SJV_ZOOM = 8


def page_url_pattern(name):
    """
    A page URL with `{id}` where the sqid goes, for the map JS to fill in
    client-side. `reverse()` percent-encodes the braces, so put them back.
    """
    return unquote(reverse(name, kwargs={'sqid': '{id}'}))


def section_map_config(year, *, center=None, zoom=None, radius=None, chemical=None, product=None, commodity=None, county=None, highlight=None, outline_url=None, all_years=False, show_notices=True):
    year = year or stats.latest_year()
    return {
        # Upcoming-notice markers start on where notices are the subject of
        # the page, off where the reader came for the use data (records, and
        # the entity pages). Either way the map's own checkbox flips it.
        'show_notices': '1' if show_notices else '0',
        'sections_url': '/api/2.0/pesticides/sections/',
        'counties_url': '/api/2.0/pesticides/counties/',
        'townships_url': '/api/2.0/pesticides/townships/',
        'notices_url': '/api/2.0/pesticides/notices/active/',
        'section_url_pattern': '/api/2.0/pesticides/sections/{id}/',
        'section_page_url': page_url_pattern('pesticides:section-detail'),
        # The bare-sqid redirect: it 301s to the slugged detail URL, so the
        # JS doesn't need the slug.
        'chemical_page_url': page_url_pattern('pesticides:chemical-redirect'),
        'product_page_url': page_url_pattern('pesticides:product-redirect'),
        'notice_page_url': page_url_pattern('pesticides:notice-detail'),
        'tile_url': leaflet.TILE_URL.format(key=settings.MAPTILER_API_KEY, z='{z}', x='{x}', y='{y}'),
        'attribution': leaflet.TILE_ATTRIBUTION,
        # What the grid endpoints are asked for ("all" sums every loaded
        # year) and how the popups say it ("in 2023" / "across 2014–2023").
        'year': stats.ALL_YEARS if all_years else (year or ''),
        'year_label': stats.year_label(year, all_years),
        'center': center or SJV_CENTER,
        'zoom': zoom or SJV_ZOOM,
        # With nothing else framing the map (a place's radius or outline, a
        # highlighted section, an explicit centre), it opens fitted to the
        # county outlines once they load, so the whole valley is in view at
        # any aspect ratio; the fixed centre/zoom only covers the wait.
        'fit': '' if any((center, zoom, radius, highlight, outline_url)) else 'valley',
        'radius': radius or '',
        'chemical': str(chemical.chem_code) if chemical else '',
        'product': str(product.prodno) if product else '',
        'commodity': commodity.site_code if commodity else '',
        'county': county or '',
        'highlight': highlight or '',
        # A regions-API URL whose boundary the map draws and fits to (place pages).
        'outline_url': outline_url or '',
    }


class MapPage(vanilla.TemplateView):
    template_name = 'pesticides/map.html'

    RELATED_MODELS = {'chemical': Chemical, 'product': Product, 'commodity': Commodity}

    def get_context_data(self, **kwargs):
        request = self.request
        year, all_years = stats.resolve_year_param(request.GET.get('year'))

        # A filter that doesn't resolve says so on the page: showing the
        # statewide map instead would look like "no use here", not "no such
        # chemical".
        related = resolve_related(request.GET, self.RELATED_MODELS)
        no_matches = any(obj is MISSING for obj in related.values())
        resolved = {param: obj for param, obj in related.items() if obj is not MISSING}

        county = scope_county(request)

        map_config = section_map_config(
            year,
            chemical=resolved.get('chemical'),
            product=resolved.get('product'),
            commodity=resolved.get('commodity'),
            county=county.slug if county else None,
            all_years=all_years,
        )

        filters = []
        for param, obj in list(resolved.items()) + [('county', county)]:
            if obj is None:
                continue
            params = request.GET.copy()
            params.pop(param, None)
            encoded = params.urlencode()
            filters.append({
                'label': getattr(obj, 'display_name', obj.name),
                'clear_url': f'?{encoded}' if encoded else '?',
            })

        county_map = None
        if (year or all_years) and not no_matches:
            county_map = maps.county_map(stats.county_totals(year, all_years))

        return super().get_context_data(
            section='map',
            map_config=map_config,
            filters=filters,
            related=resolved,
            # Products before chemicals; icons match the explorer's tab icons.
            toolbar_kinds=[
                ('product', 'Product', 'fa-spray-can-sparkles', 'is-products'),
                ('chemical', 'Chemical', 'fa-flask', 'is-chemicals'),
                ('commodity', 'Commodity', 'fa-seedling', 'is-commodities'),
            ],
            no_matches=no_matches,
            county_map=county_map,
            **year_context(year, all_years, county),
            **kwargs,
        )


def area_filter(queryset, *, county=None, region=None, section=None, point=None, radius=None, field_prefix=''):
    """
    Restrict `queryset` (PesticideUse or PesticideNotice -- both have
    `county`/`mtrs` FKs) to an area. `county` combines with any of the other
    three, but only one of region/section/point applies (section wins over
    region over point). `field_prefix` lets callers reach these fields
    through a relation (e.g. 'monitor__').
    """
    def field(name):
        return f'{field_prefix}{name}'

    if county is not None:
        queryset = queryset.filter(**{field('county'): county})

    if section is not None:
        queryset = queryset.filter(**{field('mtrs'): section})
    elif region is not None:
        if region.type == Region.Type.COUNTY:
            queryset = queryset.filter(**{field('county'): region})
        else:
            # The cached section pks for the region, rather than a spatial
            # join evaluated per row: places.region_area() computes the
            # intersection once and caches it.
            pks = places.region_area(region).section_pks
            if not pks:
                return queryset.none()
            queryset = queryset.filter(**{field('mtrs_id__in'): pks})
    elif point is not None and radius is not None:
        queryset = queryset.filter(**{
            # Bbox prefilter first -- see radius_bbox's docstring: the planner
            # can use the geometry GiST index on bboverlaps but not on a raw
            # distance_lte, so without it this forces a full table scan.
            field('mtrs__boundary__geometry__bboverlaps'): radius_bbox(point.y, point.x, radius),
            field('mtrs__boundary__geometry__distance_lte'): (point, D(mi=radius)),
        })

    return queryset


# What a `?section=` / `?region=` sqid is allowed to resolve to. Sections are
# always MTRS squares; a "region" is a place (county/city/ZIP/place), never an
# MTRS square -- `?section=` covers those.
SECTION_REGIONS = Region.objects.filter(type=Region.Type.MTRS)
PLACE_REGIONS = Region.objects.filter(type__in=places.PLACE_REGION_TYPES)

RECORDS_SORT_FIELDS = {'date': 'application_date', 'lbs': 'lbs_chemical', 'acres': 'acres_treated'}
RECORDS_DEFAULT_SORT = '-date'
RECORDS_TOTALS_TTL = 60 * 10


class RecordsPaginator(Paginator):
    """
    `Paginator.count` normally runs its own COUNT(*) query. `RecordsBrowser`
    already has the row count from `get_totals()` (cached, computed once per
    filter set), so this takes it as a forced value instead of querying again.
    """
    def __init__(self, *args, count=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._forced_count = count

    @cached_property
    def count(self):
        if self._forced_count is not None:
            return self._forced_count
        return super().count


class RecordsBrowser(vanilla.ListView):
    """
    Filterable, paginated browser of individual PesticideUse records, with
    the interactive section map above the table. Its own class (not
    ExplorerListMixin) because the filter shape -- date range, area, method --
    doesn't fit the search/related-entity pattern the chemical/product/
    commodity lists share.
    """
    model = PesticideUse
    paginate_by = 50
    template_name = 'pesticides/records.html'

    RELATED_MODELS = {
        'chemical': Chemical,
        'product': Product,
        'commodity': Commodity,
        'region': PLACE_REGIONS,
        'section': SECTION_REGIONS,
    }

    def dispatch(self, request, *args, **kwargs):
        self.year, self.all_years = stats.resolve_year_param(request.GET.get('year'))
        self.form = RecordsFilterForm(self._build_form_data(request.GET))
        self.form.is_valid()
        # The year picker follows the dates being browsed: a filter change
        # drops `?year=` from the URL, and a start date is the more specific
        # statement of which year the reader is looking at anyway. Only a
        # start date the reader actually submitted counts -- the ones
        # _build_form_data() fills in are derived from the year, not the
        # other way around.
        start = self.form.cleaned_data.get('start')
        if request.GET.get('start') and start and start.year in stats.available_years():
            self.year, self.all_years = start.year, False
        self.related = self._get_related_objects()
        self.county = self._get_county()
        self.point, self.radius = self._get_point_and_radius()
        return super().dispatch(request, *args, **kwargs)

    def _default_range(self):
        """
        Jan 1 / Dec 31 of the resolved year, or of the whole loaded range with
        `?year=all`. (None, None) only when no data is loaded at all.
        """
        if self.all_years:
            years = stats.years_loaded()
            if years is None:
                return None, None
            return date(years[0], 1, 1), date(years[1], 12, 31)
        if not self.year:
            return None, None
        return date(self.year, 1, 1), date(self.year, 12, 31)

    def _build_form_data(self, get):
        """
        A mutable copy of the querystring with `start`/`end` defaulted to the
        resolved year's range when neither is given, so the page never
        silently lists every year's records by accident. DateField.to_python
        accepts a date object directly, so these round-trip through the form
        (and render back out) exactly like an explicitly-submitted value.
        """
        data = get.copy()
        start, end = self._default_range()
        if not data.get('start') and not data.get('end') and start:
            data['start'] = start
            data['end'] = end
        return data

    def get_date_range(self):
        """
        The (start, end) actually filtered on. Decided from the *validated*
        form, not the raw querystring: a value that fails validation (e.g.
        `?start=garbage`) leaves `cleaned_data` without it, and falling back
        to the year default there keeps the page from quietly scanning every
        year. The form still renders the bad value and its error.
        """
        data = self.form.cleaned_data
        start, end = data.get('start'), data.get('end')
        if start is None and end is None:
            return self._default_range()
        return start, end

    def _get_related_objects(self):
        return resolve_related(self.request.GET, self.RELATED_MODELS)

    def _get_county(self):
        return scope_county(self.request)

    def _get_point_and_radius(self):
        return resolve_point_and_radius(self.form.cleaned_data)

    def get_filtered_queryset(self):
        if any(value is MISSING for value in self.related.values()):
            return PesticideUse.objects.none()

        data = self.form.cleaned_data
        # Deliberately unjoined -- see get_paginator()/paginate_queryset() below:
        # with the county/date filters here, Postgres badly misestimates the
        # matching row count and picks nested-loop joins across all matching
        # rows before the top-N sort/limit, even though only a page's worth
        # ever gets rendered. Ordering/filtering pks first and hydrating just
        # the page's objects afterward avoids that.
        queryset = PesticideUse.objects.all()

        start, end = self.get_date_range()
        if start:
            queryset = queryset.filter(application_date__gte=start)
        if end:
            queryset = queryset.filter(application_date__lte=end)

        queryset = area_filter(
            queryset,
            county=self.county,
            region=self.related.get('region'),
            section=self.related.get('section'),
            point=self.point,
            radius=self.radius,
        )

        if data.get('method'):
            queryset = queryset.filter(aerial_ground=data['method'])

        for param in ('chemical', 'product', 'commodity'):
            obj = self.related.get(param)
            if obj:
                queryset = queryset.filter(**{param: obj})

        return queryset

    def _get_sort(self):
        param = self.request.GET.get('sort') or RECORDS_DEFAULT_SORT
        key = param.lstrip('-')
        if key not in RECORDS_SORT_FIELDS:
            param = RECORDS_DEFAULT_SORT
            key = param.lstrip('-')
        return param, RECORDS_SORT_FIELDS[key], param.startswith('-')

    def get_queryset(self):
        queryset = self.get_filtered_queryset()
        self.sort, sort_field, desc = self._get_sort()
        if desc:
            expr = F(sort_field).desc(nulls_last=True)
            queryset = queryset.order_by(expr, '-pk')
        else:
            expr = F(sort_field).asc(nulls_last=True)
            queryset = queryset.order_by(expr, 'pk')
        return queryset

    def get_paginator(self, queryset, page_size):
        # Reuse the cached totals count instead of a second COUNT(*) query.
        return RecordsPaginator(queryset, page_size, count=self.get_totals()['applications'])

    def paginate_queryset(self, queryset, page_size):
        """
        `queryset` here is unjoined (see get_filtered_queryset()). Evaluating
        the page slice pulls just that page's pks/local columns, then a
        second query hydrates the related objects for those specific rows --
        two cheap queries instead of one that joins across every matching row.
        """
        page = super().paginate_queryset(queryset, page_size)
        page_pks = [obj.pk for obj in page.object_list]
        objects = PesticideUse.objects.select_related(
            'county', 'mtrs', 'chemical', 'product', 'commodity',
        ).in_bulk(page_pks)
        # A row deleted between the pk query above and this hydration query
        # (an import can delete/reimport a year mid-request) is dropped from
        # the page rather than raising a KeyError.
        page.object_list = [objects[pk] for pk in page_pks if pk in objects]
        return page

    def _totals_cache_key(self):
        data = self.form.cleaned_data
        start, end = self.get_date_range()
        params = {
            'start': start,
            'end': end,
            'county': data.get('county'),
            'method': data.get('method'),
            'region': self.request.GET.get('region', ''),
            'section': self.request.GET.get('section', ''),
            'chemical': self.request.GET.get('chemical', ''),
            'product': self.request.GET.get('product', ''),
            'commodity': self.request.GET.get('commodity', ''),
            'lat': data.get('lat'),
            'lng': data.get('lng'),
            'radius': data.get('radius'),
        }
        normalized = sorted((key, str(value)) for key, value in params.items())
        digest = hashlib.sha1(repr(normalized).encode()).hexdigest()
        return f'pesticides:records-totals:{digest}'

    def get_totals(self):
        key = self._totals_cache_key()
        totals = cache.get(key)
        if totals is None:
            aggregate = self.get_filtered_queryset().order_by().aggregate(
                applications=Count('id'), lbs=Sum('lbs_chemical'), acres=Sum('acres_treated'),
            )
            totals = {
                'applications': aggregate['applications'] or 0,
                'lbs': aggregate['lbs'] or 0,
                'acres': aggregate['acres'] or 0,
            }
            cache.set(key, totals, RECORDS_TOTALS_TTL)
        return totals

    def _clear_url(self, *params):
        return clear_url(self.request, *params)

    def get_active_filters(self):
        filters = []
        for param in ('chemical', 'product', 'commodity'):
            obj = self.related.get(param)
            if obj and obj is not MISSING:
                filters.append({'label': getattr(obj, 'display_name', obj.name), 'clear_url': self._clear_url(param)})
        # The county is visible (and clearable) in the filter form itself, so
        # it doesn't get a chip; chips are for the hidden entity/area filters.
        for param in ('region', 'section'):
            obj = self.related.get(param)
            if obj and obj is not MISSING:
                filters.append({'label': getattr(obj, 'display_name', obj.name), 'clear_url': self._clear_url(param)})
        if self.point:
            filters.append({'label': f'Within {self.radius} mi', 'clear_url': self._clear_url('lat', 'lng', 'radius')})
        return filters

    def get_summary_sentence(self, totals):
        sentence = (
            f"{totals['applications']:,} applications, "
            f"{totals['lbs']:,.0f} lbs, "
            f"{totals['acres']:,.0f} acres treated"
        )
        descriptors = []
        label = stats.year_label(self.year, self.all_years)
        if label:
            descriptors.append(label)
        if self.county:
            descriptors.append(self.county.name)
        for param in ('chemical', 'product', 'commodity'):
            obj = self.related.get(param)
            if obj and obj is not MISSING:
                descriptors.append(obj.display_name)
        if descriptors:
            sentence += ' — ' + ', '.join(descriptors)
        return sentence

    def get_map_config(self):
        chemical = self.related.get('chemical')
        product = self.related.get('product')
        commodity = self.related.get('commodity')
        section = self.related.get('section')
        region = self.related.get('region')

        center, zoom, radius = resolve_map_center(
            section=section, region=region, point=self.point, radius=self.radius, county=self.county,
        )

        return section_map_config(
            self.year,
            center=center,
            zoom=zoom,
            radius=radius,
            chemical=chemical if chemical and chemical is not MISSING else None,
            product=product if product and product is not MISSING else None,
            commodity=commodity if commodity and commodity is not MISSING else None,
            county=self.county.slug if self.county else None,
            all_years=self.all_years,
            show_notices=False,
        )

    def get_context_data(self, **kwargs):
        totals = self.get_totals()
        county_map = None
        if self.year or self.all_years:
            county_map = maps.county_map(stats.county_totals(self.year, self.all_years))
        return super().get_context_data(
            form=self.form,
            totals=totals,
            summary_sentence=self.get_summary_sentence(totals),
            sort=self.sort,
            active_filters=self.get_active_filters(),
            map_config=self.get_map_config(),
            county_map=county_map,
            # The entity pickers render the resolved objects; an unresolved
            # sqid has nothing to show, so it stays a plain hidden value.
            related={k: v for k, v in self.related.items() if v is not MISSING},
            api_docs_url=API_DOCS_URL,
            client_docs_url=CLIENT_DOCS_URL,
            section='records',
            **year_context(self.year, self.all_years, self.county),
            **kwargs,
        )


def _section_card(title, kind, rows, show_all_url):
    """
    related-card.html dict for a section page's top lists. Unlike
    ExplorerDetailMixin.related_card (which links "Show all" to the
    chemical/product/commodity list filtered on this entity), a section's
    "Show all" always points at the records browser filtered to the section
    itself -- there's no single entity to filter by.
    """
    return {
        'title': title,
        'kind': kind,
        'rows': rows,
        'show_pct': False,
        'show_lbs': True,
        'complete': False,
        'show_all_url': show_all_url,
    }


def _place_cards(context):
    """chemicals_card/products_card/commodities_card for place.html, all
    pointing "Show all" at the area's records browser -- there's no single
    entity to filter by, same as a section page's top lists."""
    records_url = context['records_url']
    return {
        'chemicals_card': _section_card('Top chemicals', 'chemicals', context['top_chemicals'], records_url),
        'products_card': _section_card('Top products', 'products', context['top_products'], records_url),
        'commodities_card': _section_card('Top commodities', 'commodities', context['top_commodities'], records_url),
    }


class SectionDetail(vanilla.DetailView):
    """
    A single MTRS square-mile section: stats, a 12-month bar chart, top
    chemicals/products/commodities, active notices, and a link into the
    records browser pre-filtered to this section.
    """
    model = Region
    lookup_field = 'sqid'
    lookup_url_kwarg = 'sqid'
    template_name = 'pesticides/section-detail.html'

    def get_queryset(self):
        return Region.objects.filter(type=Region.Type.MTRS)

    def get_context_data(self, **kwargs):
        section = self.object
        year, all_years = stats.resolve_year_param(self.request.GET.get('year'))
        rows = PesticideUseRollup.objects.filter(mtrs=section)

        county_name = (
            rows.exclude(county__isnull=True)
            .order_by('county__name')
            .values_list('county__name', flat=True)
            .first()
        )

        # A single section is at most a few thousand rollup rows even across
        # every loaded year, so these stay live aggregates.
        if year or all_years:
            totals = stats.year_totals(rows, year, all_years=all_years)
            by_month = stats.by_month(rows, year, all_years=all_years)
            chemical_count = (
                stats.in_year(rows, year, all_years)
                .filter(chemical__isnull=False).values('chemical').distinct().count()
            )
        else:
            totals = {'lbs': 0, 'applications': 0, 'counties': 0}
            by_month = []
            chemical_count = 0

        peak_month = None
        if by_month and any(month['lbs'] for month in by_month):
            peak = max(by_month, key=lambda month: month['lbs'])
            peak_month = calendar.month_name[peak['month']]

        top_chemicals = stats.top_related(rows, year, 'chemical', limit=10, all_years=all_years)
        top_products = stats.top_related(rows, year, 'product', lbs_field='lbs_product', limit=10, all_years=all_years)
        top_commodities = stats.top_related(rows, year, 'commodity', limit=10, all_years=all_years)

        notices = PesticideNotice.objects.filter(mtrs=section)
        upcoming = stats.upcoming_notices(notices)
        upcoming_count = stats.upcoming_count(notices)

        year_param = stats.year_param(year, all_years)
        records_url = reverse('pesticides:records') + f'?section={section.sqid}' + (
            f'&{year_param}' if year_param else ''
        )

        center = zoom = None
        if section.boundary_id:
            center, zoom = centroid(section), 13
        map_config = section_map_config(
            year, center=center, zoom=zoom, highlight=section.sqid, all_years=all_years,
        )

        return super().get_context_data(
            section='sections',
            county_name=county_name,
            years=stats.years_loaded(),
            **year_context(year, all_years, scope_county(self.request), county_scope=False),
            totals=totals,
            chemical_count=chemical_count,
            by_year=stats.by_year(rows),
            by_month=by_month,
            peak_month=peak_month,
            top_chemicals=top_chemicals,
            top_products=top_products,
            top_commodities=top_commodities,
            chemicals_card=_section_card('Top chemicals', 'chemicals', top_chemicals, records_url),
            products_card=_section_card('Top products', 'products', top_products, records_url),
            commodities_card=_section_card('Top commodities', 'commodities', top_commodities, records_url),
            upcoming=upcoming,
            upcoming_count=upcoming_count,
            records_url=records_url,
            map_config=map_config,
            api_docs_url=API_DOCS_URL,
            client_docs_url=CLIENT_DOCS_URL,
            **kwargs,
        )


NOTICE_RELATED_MODELS = {'chemical': Chemical, 'product': Product, 'region': PLACE_REGIONS, 'section': SECTION_REGIONS}
NOTICE_FIELD_MAP = {'chemical': 'chemicals', 'product': 'products'}


class NoticeList(vanilla.ListView):
    """
    SprayDays notices of intent -- active by default (still within the grace
    period, soonest first), or the archive (past the grace period, newest
    first, optionally narrowed to a year/month) with `?past=1`. Filters via
    `area_filter` and chemical/product sqids, same shape as RecordsBrowser.
    """
    model = PesticideNotice
    paginate_by = 50
    template_name = 'pesticides/notice-list.html'

    def dispatch(self, request, *args, **kwargs):
        self.form = NoticeFilterForm(request.GET)
        self.form.is_valid()
        self.related = resolve_related(request.GET, NOTICE_RELATED_MODELS)
        self.county = scope_county(request)
        self.point, self.radius = resolve_point_and_radius(self.form.cleaned_data)
        self.mode = 'past' if self.form.cleaned_data.get('past') else 'active'
        self.year, self.all_years = stats.resolve_year_param(request.GET.get('year'))
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        if any(value is MISSING for value in self.related.values()):
            return PesticideNotice.objects.none()

        queryset = PesticideNotice.objects.select_related('county', 'mtrs').prefetch_related('chemicals', 'products')
        queryset = area_filter(
            queryset,
            county=self.county,
            region=self.related.get('region'),
            section=self.related.get('section'),
            point=self.point,
            radius=self.radius,
        )

        data = self.form.cleaned_data
        if data.get('method'):
            queryset = queryset.filter(application_method__iexact=data['method'])
        for param, field in NOTICE_FIELD_MAP.items():
            obj = self.related.get(param)
            if obj:
                queryset = queryset.filter(**{field: obj})

        if self.mode == 'past':
            cutoff = timezone.now() - timedelta(days=stats.NOTICE_GRACE_DAYS)
            queryset = queryset.filter(scheduled_application__lt=cutoff)
            bounds = local_month_bounds(data.get('archive_year'), data.get('month'))
            if bounds is not None:
                start, end = bounds
                queryset = queryset.filter(scheduled_application__gte=start, scheduled_application__lt=end)
            queryset = queryset.order_by('-scheduled_application')
        else:
            queryset = stats._upcoming(queryset).order_by('scheduled_application')

        return queryset

    def get_archive_months(self):
        """Last 24 months (in America/Los_Angeles) with an archived notice, newest first."""
        if self.mode != 'past':
            return []
        cutoff = timezone.now() - timedelta(days=stats.NOTICE_GRACE_DAYS)
        months = (
            PesticideNotice.objects
            .filter(scheduled_application__lt=cutoff)
            .annotate(month=TruncMonth('scheduled_application', tzinfo=settings.DEFAULT_TIMEZONE))
            .values('month')
            .annotate(count=Count('id'))
            .order_by('-month')[:24]
        )
        return [
            {
                'year': row['month'].year,
                'month': row['month'].month,
                'label': f"{calendar.month_name[row['month'].month]} {row['month'].year}",
                'count': row['count'],
            }
            for row in months
        ]

    def get_active_filters(self):
        filters = []
        for param in ('chemical', 'product'):
            obj = self.related.get(param)
            if obj and obj is not MISSING:
                filters.append({'label': getattr(obj, 'display_name', obj.name), 'clear_url': clear_url(self.request, param)})
        for param in ('region', 'section'):
            obj = self.related.get(param)
            if obj and obj is not MISSING:
                filters.append({'label': getattr(obj, 'display_name', obj.name), 'clear_url': clear_url(self.request, param)})
        if self.point:
            filters.append({'label': f'Within {self.radius} mi', 'clear_url': clear_url(self.request, 'lat', 'lng', 'radius')})
        return filters

    def get_map_config(self):
        chemical = self.related.get('chemical')
        product = self.related.get('product')
        section = self.related.get('section')
        region = self.related.get('region')

        center, zoom, radius = resolve_map_center(
            section=section, region=region, point=self.point, radius=self.radius, county=self.county,
        )

        return section_map_config(
            stats.latest_year(),
            center=center,
            zoom=zoom,
            radius=radius,
            chemical=chemical if chemical and chemical is not MISSING else None,
            product=product if product and product is not MISSING else None,
            county=self.county.slug if self.county else None,
        )

    def get_context_data(self, **kwargs):
        data = self.form.cleaned_data
        # The site-wide `?year=` picker doesn't apply to notices (they're
        # scheduled, not reported by year), but the nav links still carry it,
        # so take the scope context and drop year_options -- that's what
        # keeps the year picker from rendering here. The county picker stays.
        year_ctx = year_context(self.year, self.all_years, self.county)
        year_ctx.pop('year_options', None)
        return super().get_context_data(
            form=self.form,
            section='notices',
            mode=self.mode,
            count=paginated_count(kwargs),
            map_config=self.get_map_config(),
            active_filters=self.get_active_filters(),
            archive_months=self.get_archive_months(),
            filter_year=data.get('archive_year'),
            filter_month=data.get('month'),
            **year_ctx,
            **kwargs,
        )


class NoticeDetail(vanilla.DetailView):
    """
    A single notice of intent: whether it's still active (within the 4-day
    grace period), its area/method/materials, a map, other active notices in
    the same section, and the SprayDays sign-up link.
    """
    model = PesticideNotice
    lookup_field = 'sqid'
    lookup_url_kwarg = 'sqid'
    template_name = 'pesticides/notice-detail.html'

    def get_queryset(self):
        return PesticideNotice.objects.select_related('county', 'mtrs').prefetch_related('chemicals', 'products')

    def get_context_data(self, **kwargs):
        notice = self.object
        is_active = notice.scheduled_application >= timezone.now() - timedelta(days=stats.NOTICE_GRACE_DAYS)
        window_end = notice.scheduled_application + timedelta(days=stats.NOTICE_GRACE_DAYS)

        center = None
        if notice.point:
            center = f'{notice.point.y:.4f},{notice.point.x:.4f}'
        elif notice.mtrs_id and notice.mtrs.boundary_id:
            center = centroid(notice.mtrs)
        map_config = section_map_config(stats.latest_year(), center=center, zoom=13 if center else None)

        related_notices = PesticideNotice.objects.none()
        if notice.mtrs_id:
            related_notices = (
                stats._upcoming(PesticideNotice.objects.filter(mtrs_id=notice.mtrs_id))
                .exclude(pk=notice.pk)
                .select_related('county', 'mtrs')
                .prefetch_related('chemicals', 'products')
                .order_by('scheduled_application')[:5]
            )

        if notice.mtrs_id:
            records_url = reverse('pesticides:records') + f'?section={notice.mtrs.sqid}'
        elif notice.county_id:
            records_url = reverse('pesticides:records') + f'?county={notice.county.slug}'
        else:
            records_url = reverse('pesticides:records')

        return super().get_context_data(
            section='notices',
            is_active=is_active,
            window_end=window_end,
            map_config=map_config,
            related_notices=related_notices,
            records_url=records_url,
            **kwargs,
        )


class NearMe(vanilla.TemplateView):
    """
    A place page centered on a lat/lng from the address bar (?lat=&lng=&
    radius=&label=), never stored server-side. Coordinates are validated in
    get() -- an invalid or missing pair bounces to the landing page's find
    form rather than rendering a broken page.
    """
    template_name = 'pesticides/place.html'

    def _parse_coords(self, data):
        try:
            lat = float(data['lat'])
            lng = float(data['lng'])
        except (KeyError, TypeError, ValueError):
            return None, None, None
        if not (math.isfinite(lat) and math.isfinite(lng)):
            return None, None, None
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            return None, None, None
        try:
            radius = int(data.get('radius', 1))
        except (TypeError, ValueError):
            return None, None, None
        if radius not in places.RADIUS_CHOICES:
            return None, None, None
        return lat, lng, radius

    def get(self, request, *args, **kwargs):
        lat, lng, radius = self._parse_coords(request.GET)
        if lat is None:
            return redirect(reverse('pesticides:home') + '?find=1')
        self.lat, self.lng, self.radius = lat, lng, radius
        # Truncate here, on the request's own GET, so every link built from
        # it below (year picker, radius switcher) carries the same
        # already-truncated label instead of the raw oversized one.
        label = request.GET.get('label')
        if label and len(label) > 120:
            request.GET = request.GET.copy()
            request.GET['label'] = label[:120]
        return super().get(request, *args, **kwargs)

    def _radius_url(self, miles):
        params = self.request.GET.copy()
        params['radius'] = miles
        return f'{self.request.path}?{params.urlencode()}'

    def get_context_data(self, **kwargs):
        year, all_years = stats.resolve_year_param(self.request.GET.get('year'))
        label = (self.request.GET.get('label') or f'{self.lat:.3f}, {self.lng:.3f}')[:120]
        area = places.point_area(self.lat, self.lng, self.radius, label=label)
        context = places.place_context(area, year, all_years)
        radius_options = [
            {'miles': miles, 'url': self._radius_url(miles), 'current': miles == self.radius}
            for miles in places.RADIUS_CHOICES
        ]
        return super().get_context_data(
            section=None,
            years=stats.years_loaded(),
            **context,
            **_place_cards(context),
            **year_context(year, all_years, scope_county(self.request), county_scope=False),
            privacy_note=True,
            radius_options=radius_options,
            api_docs_url=API_DOCS_URL,
            client_docs_url=CLIENT_DOCS_URL,
            **kwargs,
        )


class RegionPage(vanilla.TemplateView):
    """
    A place page for a county/city/ZIP/place `Region`. MTRS sections aren't
    included -- SectionDetail already covers those -- so an out-of-range
    `type` (including MTRS) 404s the same as an unresolved sqid.
    """
    template_name = 'pesticides/place.html'

    def get(self, request, *args, **kwargs):
        region = (
            Region.objects
            .filter(sqid=kwargs['sqid'], type__in=places.PLACE_REGION_TYPES)
            .select_related('boundary')
            .first()
        )
        if region is None or not region.boundary_id:
            raise Http404
        if region.slug != kwargs['slug']:
            canonical = reverse('pesticides:region', kwargs={'sqid': region.sqid, 'slug': region.slug})
            query = request.GET.urlencode()
            return redirect(f'{canonical}?{query}' if query else canonical, permanent=True)
        self.region = region
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        year, all_years = stats.resolve_year_param(self.request.GET.get('year'))
        area = places.region_area(self.region)
        context = places.place_context(area, year, all_years)
        within = places.regions_within(self.region) if self.region.type == Region.Type.COUNTY else None
        return super().get_context_data(
            section=None,
            years=stats.years_loaded(),
            within=within,
            **context,
            **_place_cards(context),
            **year_context(year, all_years, scope_county(self.request), county_scope=False),
            privacy_note=False,
            api_docs_url=API_DOCS_URL,
            client_docs_url=CLIENT_DOCS_URL,
            **kwargs,
        )
