import calendar
import hashlib
from datetime import date
from types import SimpleNamespace

from django.conf import settings
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Count, F, FloatField, IntegerField, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.functional import cached_property

import vanilla

from camp.api.v2.pesticides.sections import radius_bbox
from camp.apps.pesticides import maps, stats
from camp.apps.pesticides.forms import ChemicalFilterForm, CommodityFilterForm, ProductFilterForm, RecordsFilterForm
from camp.apps.pesticides.models import (
    Chemical, Commodity, PesticideNotice, PesticideUse, PesticideUseRollup, Product, ProductChemical,
)
from camp.apps.regions.models import Region
from camp.utils import leaflet

# Sentinel for "sqid didn't resolve to an object" in ExplorerListMixin.related.
# Not Http404 -- that's an exception class, not a value, and using it as a
# dict value / membership check reads as if it might be raised.
MISSING = object()

def year_context(year):
    """Context every explorer page needs for the year picker and year-pinned links."""
    return {
        'year': year,
        'latest_year': stats.latest_year(),
        'year_options': stats.available_years(),
        'year_qs': stats.year_query(year),
    }


# Public pages link developers to the documentation, never to raw endpoints.
API_DOCS_URL = '/api/2.0/docs/#tag/pesticides'
CLIENT_DOCS_URL = 'https://sjvair.github.io/sjvair-python/client/resources/pesticides.html'


def lbs_subquery(field, year, lbs_field='lbs_chemical'):
    """Sum of pounds in `year` for the outer row, via `PesticideUseRollup.<field>`."""
    return Subquery(
        PesticideUseRollup.objects
        .filter(**{field: OuterRef('pk')}, year=year)
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


def related_pks(field, obj, target):
    """PKs of `target` (a PesticideUseRollup FK name) that share a rollup row with obj."""
    return PesticideUseRollup.objects.filter(**{field: obj}).values(target)


class ExplorerListMixin:
    paginate_by = 50
    form_class = None
    section = None
    sort_fields = {}
    default_sort = 'name'
    related_models = {}

    def dispatch(self, request, *args, **kwargs):
        self.form = self.form_class(request.GET)
        self.form.is_valid()
        self.year = stats.resolve_year(request.GET.get('year'))
        self.related = self.get_related_objects()
        return super().dispatch(request, *args, **kwargs)

    def get_search_query(self):
        return (self.form.cleaned_data.get('q') or '').strip()

    def get_related_objects(self):
        related = {}
        for param, model in self.related_models.items():
            value = self.request.GET.get(param)
            if value:
                related[param] = model.objects.filter(sqid=value).first() or MISSING
        return related

    def apply_related(self, queryset):
        for param, obj in self.related.items():
            if obj is MISSING:
                return queryset.none()
            queryset = self.filter_related(queryset, param, obj)
        return queryset

    def filter_related(self, queryset, param, obj):
        raise NotImplementedError

    def apply_filters(self, queryset, data):
        return queryset

    def annotate_queryset(self, queryset, year):
        return queryset

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
        for param, obj in self.related.items():
            if obj is not MISSING:
                parts.append(f'linked to {obj.name}')
        return ' '.join(parts)

    def describe_filters(self, data):
        return []

    def get_context_data(self, **kwargs):
        count = kwargs['paginator'].count if kwargs.get('paginator') else len(kwargs.get('object_list', []))
        return super().get_context_data(
            form=self.form,
            query=self.get_search_query(),
            sort=self.sort,
            result_count=count,
            **year_context(self.year),
            summary_sentence=self.get_summary_sentence(count),
            related={k: v for k, v in self.related.items() if v is not MISSING},
            section=self.section,
            **kwargs,
        )


class ChemicalList(ExplorerListMixin, vanilla.ListView):
    model = Chemical
    form_class = ChemicalFilterForm
    template_name = 'pesticides/chemical-list.html'
    section = 'chemicals'
    sort_fields = {'name': 'name', 'lbs': 'lbs_applied', 'products': 'product_count', 'iarc': 'iarc_group'}
    default_sort = '-lbs'
    related_models = {'product': Product, 'commodity': Commodity}

    def filter_related(self, queryset, param, obj):
        if param == 'product':
            return queryset.filter(product_chemicals__product=obj)
        return queryset.filter(pk__in=related_pks('commodity', obj, 'chemical'))

    def apply_filters(self, queryset, data):
        if data.get('category'):
            queryset = queryset.filter(categories__overlap=data['category'])
        if data.get('iarc_group'):
            queryset = queryset.filter(iarc_group=data['iarc_group'])
        return queryset

    def annotate_queryset(self, queryset, year):
        queryset = queryset.annotate(
            product_count=Coalesce(count_subquery(ProductChemical, 'chemical', 'product'), 0)
        )
        if year:
            queryset = queryset.annotate(lbs_applied=lbs_subquery('chemical', year))
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
        return redirect(obj.get_absolute_url(), permanent=True)


class Home(vanilla.TemplateView):
    template_name = 'pesticides/home.html'

    def get_context_data(self, **kwargs):
        year = stats.resolve_year(self.request.GET.get('year'))
        data = stats.landing_stats(year)
        county_map = maps.county_map(data['by_county']) if data['by_county'] else None
        # landing_stats carries `year`/`latest_year` too; year_context wins on overlap.
        return super().get_context_data(
            section=None,
            county_map=county_map,
            api_docs_url=API_DOCS_URL,
            client_docs_url=CLIENT_DOCS_URL,
            **{**data, **year_context(year)},
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

    def filter_related(self, queryset, param, obj):
        if param == 'chemical':
            return queryset.filter(product_chemicals__chemical=obj)
        return queryset.filter(pk__in=related_pks('commodity', obj, 'product'))

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
        if year:
            queryset = queryset.annotate(lbs_applied=lbs_subquery('product', year, lbs_field='lbs_product'))
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
    form_class = CommodityFilterForm
    template_name = 'pesticides/commodity-list.html'
    section = 'commodities'
    sort_fields = {'name': 'name', 'lbs': 'lbs_applied', 'chemicals': 'chemical_count', 'site': 'site_code'}
    default_sort = '-lbs'
    related_models = {'chemical': Chemical, 'product': Product}

    def filter_related(self, queryset, param, obj):
        return queryset.filter(pk__in=related_pks(param, obj, 'commodity'))

    def annotate_queryset(self, queryset, year):
        if not year:
            return queryset.annotate(lbs_applied=F('pk') * 0.0, chemical_count=F('pk') * 0)
        chemical_count = Subquery(
            PesticideUseRollup.objects
            .filter(commodity=OuterRef('pk'), year=year)
            .values('commodity')
            .annotate(n=Count('chemical', distinct=True))
            .values('n'),
        )
        return queryset.annotate(
            lbs_applied=lbs_subquery('commodity', year),
            chemical_count=Coalesce(chemical_count, 0),
        )


class ExplorerDetailMixin:
    lookup_field = 'sqid'
    lookup_url_kwarg = 'sqid'
    section = None
    lbs_field = 'lbs_chemical'
    use_field = None          # PesticideUse FK name for this entity
    api_param = None          # v2 API query param name, shown as a hint for developers
    has_notices = True

    def get_uses(self):
        return PesticideUse.objects.filter(**{self.use_field: self.object})

    def get_rollup(self):
        return PesticideUseRollup.objects.filter(**{self.use_field: self.object})

    def get_notices(self):
        return PesticideNotice.objects.none()

    def api_value(self):
        raise NotImplementedError

    def get_related(self, year):
        """Return (related_a, related_b) dicts. Each: {title, kind, rows, show_all_url}."""
        raise NotImplementedError

    def related_card(self, title, kind, rows, list_url_name, param, show_pct=False, show_lbs=True, complete=False):
        """
        show_pct: rows carry pct_active (only product<->chemical relations do).
        show_lbs: rows carry pounds (a product's ingredient list does not).
        complete: every related object is already listed, so no "Show all".
        """
        return {
            'title': title,
            'kind': kind,
            'rows': rows,
            'show_pct': show_pct,
            'show_lbs': show_lbs,
            'complete': complete,
            'show_all_url': reverse(list_url_name) + f'?{param}={self.object.sqid}' + (
                f'&year={self.year}' if stats.year_query(self.year) else ''
            ),
        }

    def get_summary_sentence(self, totals, year, top, verb='on'):
        if not totals['applications'] or year is None:
            return ''
        sentence = f'Applied in {totals["counties"]} of {stats.SJV_COUNTY_COUNT} SJV counties in {year}'
        names = [r.obj.name.title() for r in top[:2]]
        if names:
            joined = ' and '.join(names)
            sentence += f', mostly {verb} {joined}' if verb else f', mostly {joined}'
        return sentence + '.'

    def get_context_data(self, **kwargs):
        year = stats.resolve_year(self.request.GET.get('year'))
        self.year = year
        uses = self.get_uses()
        rows = self.get_rollup()
        notices = self.get_notices()
        totals = stats.year_totals(rows, year, self.lbs_field) if year else {'lbs': 0, 'applications': 0, 'counties': 0}
        related_a, related_b = self.get_related(year)
        context = super().get_context_data(
            section=self.section,
            years=stats.years_loaded(),
            **year_context(year),
            county_total=stats.SJV_COUNTY_COUNT,
            totals=totals,
            by_year=stats.by_year(rows, self.lbs_field),
            by_county=stats.by_county(rows, year, self.lbs_field) if year else [],
            by_month=stats.by_month(rows, year, self.lbs_field) if year else [],
            related_a=related_a,
            related_b=related_b,
            recent_uses=stats.recent_uses(uses.filter(year=year)) if year else [],
            has_notices=self.has_notices,
            upcoming=stats.upcoming_notices(notices) if self.has_notices else [],
            upcoming_by_county=stats.upcoming_by_county(notices) if self.has_notices else [],
            upcoming_count=stats.upcoming_count(notices) if self.has_notices else 0,
            notice_window=stats.notice_window(),
            api_docs_url=API_DOCS_URL,
            client_docs_url=CLIENT_DOCS_URL,
            api_filter=f'{self.api_param}={self.api_value()}',
            **kwargs,
        )
        context['summary_sentence'] = self.get_summary_sentence(totals, year, self.summary_top(context))
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

    def get_related(self, year):
        rows = self.get_rollup()
        pct = dict(self.object.product_chemicals.values_list('product_id', 'pct_active'))
        products = with_pct_active(stats.top_related(rows, year, 'product', self.lbs_field), pct)
        commodities = stats.top_related(rows, year, 'commodity', self.lbs_field)
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

    def get_related(self, year):
        rows = self.get_rollup()
        pct = dict(self.object.product_chemicals.values_list('chemical_id', 'pct_active'))
        # Active ingredients are a property of the product, not of use records,
        # so list all of them (ranked by pct_active) rather than by pounds.
        chemicals = [
            SimpleNamespace(obj=c, lbs=None, pct_active=pct.get(c.pk))
            for c in sorted(self.object.chemicals.all(), key=lambda c: -(pct.get(c.pk) or 0))
        ]
        commodities = stats.top_related(rows, year, 'commodity', self.lbs_field)
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

    def get_related(self, year):
        rows = self.get_rollup()
        return (
            self.related_card('Chemicals applied', 'chemicals', stats.top_related(rows, year, 'chemical'), 'pesticides:chemical-list', 'commodity'),
            self.related_card('Products applied', 'products', stats.top_related(rows, year, 'product', 'lbs_product'), 'pesticides:product-list', 'commodity'),
        )

    def summary_top(self, context):
        return context['related_a']['rows']

    def get_summary_sentence(self, totals, year, top, verb=None):
        return super().get_summary_sentence(totals, year, top, verb=None)


SJV_CENTER = '36.75,-119.80'
SJV_ZOOM = 8


def section_map_config(year, *, center=None, zoom=None, radius=None, chemical=None, product=None, commodity=None, county=None):
    return {
        'sections_url': '/api/2.0/pesticides/sections/',
        'notices_url': '/api/2.0/pesticides/notices/active/',
        'section_url_pattern': '/api/2.0/pesticides/sections/{id}/',
        'tile_url': leaflet.TILE_URL.format(key=settings.MAPTILER_API_KEY, z='{z}', x='{x}', y='{y}'),
        'attribution': leaflet.TILE_ATTRIBUTION,
        'year': year or '',
        'center': center or SJV_CENTER,
        'zoom': zoom or SJV_ZOOM,
        'radius': radius or '',
        'chemical': str(chemical.chem_code) if chemical else '',
        'product': str(product.prodno) if product else '',
        'commodity': commodity.site_code if commodity else '',
        'county': county or '',
    }


class MapPage(vanilla.TemplateView):
    template_name = 'pesticides/map.html'

    def get_context_data(self, **kwargs):
        request = self.request
        year = stats.resolve_year(request.GET.get('year'))

        chemical = None
        chemical_sqid = request.GET.get('chemical')
        if chemical_sqid:
            chemical = Chemical.objects.filter(sqid=chemical_sqid).first()

        product = None
        product_sqid = request.GET.get('product')
        if product_sqid:
            product = Product.objects.filter(sqid=product_sqid).first()

        commodity = None
        commodity_sqid = request.GET.get('commodity')
        if commodity_sqid:
            commodity = Commodity.objects.filter(sqid=commodity_sqid).first()

        county = None
        county_slug = request.GET.get('county')
        if county_slug:
            county = Region.objects.filter(type=Region.Type.COUNTY, slug=county_slug).first()

        map_config = section_map_config(
            year,
            chemical=chemical,
            product=product,
            commodity=commodity,
            county=county.slug if county else None,
        )

        filters = []
        for param, obj in (('chemical', chemical), ('product', product), ('commodity', commodity), ('county', county)):
            if obj is None:
                continue
            params = request.GET.copy()
            params.pop(param, None)
            encoded = params.urlencode()
            filters.append({
                'label': obj.name,
                'clear_url': f'?{encoded}' if encoded else '?',
            })

        county_map = None
        if year:
            county_map = maps.county_map(stats.by_county(PesticideUseRollup.objects.all(), year))

        return super().get_context_data(
            section='map',
            map_config=map_config,
            filters=filters,
            county_map=county_map,
            **year_context(year),
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
        if not region.boundary_id:
            return queryset.none()
        queryset = queryset.filter(**{
            field('mtrs__boundary__geometry__intersects'): region.boundary.geometry,
        })
    elif point is not None and radius is not None:
        queryset = queryset.filter(**{
            # Bbox prefilter first -- see radius_bbox's docstring: the planner
            # can use the geometry GiST index on bboverlaps but not on a raw
            # distance_lte, so without it this forces a full table scan.
            field('mtrs__boundary__geometry__bboverlaps'): radius_bbox(point.y, point.x, radius),
            field('mtrs__boundary__geometry__distance_lte'): (point, D(mi=radius)),
        })

    return queryset


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
        'region': Region,
        'section': Region,
    }

    def dispatch(self, request, *args, **kwargs):
        self.year = stats.resolve_year(request.GET.get('year'))
        self.form = RecordsFilterForm(self._build_form_data(request.GET))
        self.form.is_valid()
        self.related = self._get_related_objects()
        self.county = self._get_county()
        self.point, self.radius = self._get_point_and_radius()
        return super().dispatch(request, *args, **kwargs)

    def _build_form_data(self, get):
        """
        A mutable copy of the querystring with `start`/`end` defaulted to
        Jan 1 / Dec 31 of the resolved year when neither is given, so the
        page never silently lists every year's records. DateField.to_python
        accepts a date object directly, so these round-trip through the form
        (and render back out) exactly like an explicitly-submitted value.
        """
        data = get.copy()
        if not data.get('start') and not data.get('end') and self.year:
            data['start'] = date(self.year, 1, 1)
            data['end'] = date(self.year, 12, 31)
        return data

    def _get_related_objects(self):
        related = {}
        for param, model in self.RELATED_MODELS.items():
            value = self.request.GET.get(param)
            if value:
                related[param] = model.objects.filter(sqid=value).first() or MISSING
        return related

    def _get_county(self):
        slug = self.form.cleaned_data.get('county')
        if not slug:
            return None
        return Region.objects.filter(type=Region.Type.COUNTY, slug=slug).select_related('boundary').first()

    def _get_point_and_radius(self):
        """
        lat/lng come off `RecordsFilterForm`'s FloatFields, which already
        reject `nan`/`inf` strings during is_valid() -- that's what keeps
        GEOS from being handed a non-finite coordinate below. Range-check
        the parsed floats the same way the sections API does
        (camp/api/v2/pesticides/sections.py) so an out-of-range lat/lng
        (e.g. lat=200) is treated as "no point" rather than reaching Point().
        An off-list radius is clamped to 1 mile.
        """
        data = self.form.cleaned_data
        lat, lng = data.get('lat'), data.get('lng')
        if lat is None or lng is None:
            return None, None
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            return None, None
        try:
            radius = int(data.get('radius') or 1)
        except (TypeError, ValueError):
            radius = 1
        if radius not in (1, 3, 5):
            radius = 1
        return Point(lng, lat, srid=4326), radius

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

        if data.get('start'):
            queryset = queryset.filter(application_date__gte=data['start'])
        if data.get('end'):
            queryset = queryset.filter(application_date__lte=data['end'])

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
        page.object_list = [objects[pk] for pk in page_pks if pk in objects]
        return page

    def _totals_cache_key(self):
        data = self.form.cleaned_data
        params = {
            'start': data.get('start'),
            'end': data.get('end'),
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
        data = self.request.GET.copy()
        for param in params:
            data.pop(param, None)
        data.pop('page', None)
        encoded = data.urlencode()
        return f'{self.request.path}?{encoded}' if encoded else self.request.path

    def get_active_filters(self):
        filters = []
        for param in ('chemical', 'product', 'commodity'):
            obj = self.related.get(param)
            if obj and obj is not MISSING:
                filters.append({'label': obj.name, 'clear_url': self._clear_url(param)})
        if self.county:
            filters.append({'label': self.county.name, 'clear_url': self._clear_url('county')})
        for param in ('region', 'section'):
            obj = self.related.get(param)
            if obj and obj is not MISSING:
                filters.append({'label': obj.name, 'clear_url': self._clear_url(param)})
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
        if self.year:
            descriptors.append(str(self.year))
        if self.county:
            descriptors.append(self.county.name)
        for param in ('chemical', 'product', 'commodity'):
            obj = self.related.get(param)
            if obj and obj is not MISSING:
                descriptors.append(obj.name.title())
        if descriptors:
            sentence += ' — ' + ', '.join(descriptors)
        return sentence

    @staticmethod
    def _centroid(region):
        point = region.boundary.geometry.centroid
        return f'{point.y:.4f},{point.x:.4f}'

    def get_map_config(self):
        chemical = self.related.get('chemical')
        product = self.related.get('product')
        commodity = self.related.get('commodity')
        section = self.related.get('section')
        region = self.related.get('region')

        center = zoom = radius = None
        if section and section is not MISSING and section.boundary_id:
            center, zoom = self._centroid(section), 13
        elif region and region is not MISSING and region.boundary_id:
            center, zoom = self._centroid(region), 10
        elif self.point:
            center, zoom, radius = f'{self.point.y:.4f},{self.point.x:.4f}', 12, self.radius
        elif self.county and self.county.boundary_id:
            center, zoom = self._centroid(self.county), 9

        return section_map_config(
            self.year,
            center=center,
            zoom=zoom,
            radius=radius,
            chemical=chemical if chemical and chemical is not MISSING else None,
            product=product if product and product is not MISSING else None,
            commodity=commodity if commodity and commodity is not MISSING else None,
            county=self.county.slug if self.county else None,
        )

    def get_context_data(self, **kwargs):
        totals = self.get_totals()
        county_map = None
        if self.year:
            county_map = maps.county_map(stats.by_county(PesticideUseRollup.objects.all(), self.year))
        return super().get_context_data(
            form=self.form,
            totals=totals,
            summary_sentence=self.get_summary_sentence(totals),
            sort=self.sort,
            active_filters=self.get_active_filters(),
            map_config=self.get_map_config(),
            county_map=county_map,
            api_docs_url=API_DOCS_URL,
            client_docs_url=CLIENT_DOCS_URL,
            section='records',
            **year_context(self.year),
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
        year = stats.resolve_year(self.request.GET.get('year'))
        rows = PesticideUseRollup.objects.filter(mtrs=section)

        county_name = (
            rows.exclude(county__isnull=True)
            .order_by('county__name')
            .values_list('county__name', flat=True)
            .first()
        )

        if year:
            totals = stats.year_totals(rows, year)
            by_month = stats.by_month(rows, year)
            recent_uses = stats.recent_uses(PesticideUse.objects.filter(mtrs=section, year=year), limit=5)
            chemical_count = rows.filter(year=year, chemical__isnull=False).values('chemical').distinct().count()
        else:
            totals = {'lbs': 0, 'applications': 0, 'counties': 0}
            by_month = []
            recent_uses = PesticideUse.objects.none()
            chemical_count = 0

        peak_month = None
        if by_month and any(month['lbs'] for month in by_month):
            peak = max(by_month, key=lambda month: month['lbs'])
            peak_month = calendar.month_name[peak['month']]

        top_chemicals = stats.top_related(rows, year, 'chemical', limit=10)
        top_products = stats.top_related(rows, year, 'product', lbs_field='lbs_product', limit=10)
        top_commodities = stats.top_related(rows, year, 'commodity', limit=10)

        notices = PesticideNotice.objects.filter(mtrs=section)
        upcoming = stats.upcoming_notices(notices)

        records_url = reverse('pesticides:records') + f'?section={section.sqid}' + (
            f'&year={year}' if stats.year_query(year) else ''
        )

        center = zoom = None
        if section.boundary_id:
            center, zoom = RecordsBrowser._centroid(section), 13
        map_config = section_map_config(year, center=center, zoom=zoom)

        return super().get_context_data(
            section='sections',
            county_name=county_name,
            years=stats.years_loaded(),
            **year_context(year),
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
            recent_uses=recent_uses,
            records_url=records_url,
            map_config=map_config,
            api_docs_url=API_DOCS_URL,
            client_docs_url=CLIENT_DOCS_URL,
            **kwargs,
        )
