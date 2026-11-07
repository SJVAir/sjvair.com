import hashlib
import json
from types import SimpleNamespace

from django import forms
from django.db.models import Case, Count, Prefetch, Q, Sum, Value, When
from django.db.models.functions import Coalesce, Length, NullIf
from django.shortcuts import get_object_or_404

from resticus import generics, http

from camp.apps.pesticides import stats
from camp.apps.pesticides.places import monthly_use, rollup_rows_for
from camp.apps.pesticides.models import (
    Chemical, Commodity, PesticideNotice, PesticideUse, PesticideUseTotal, Product,
)
from camp.apps.regions.models import Region
from camp.apps.regions.resolve import CACHE_TIMEOUT, PlaceError, PlaceNotFound, _place_key, place_json, resolve_place
from camp.utils.views import CachedEndpointMixin

from .filters import ChemicalFilter, CommodityFilter, PesticideNoticeFilter, PesticideSummaryFilter, PesticideUseFilter, ProductFilter
from .serializers import (
    ChemicalSerializer,
    ChemicalDetailSerializer,
    CommoditySerializer,
    CommodityDetailSerializer,
    PesticideNoticeSerializer,
    PesticideSummaryResponseSerializer,
    PesticideUseSerializer,
    ProductSerializer,
    ProductDetailSerializer,
)


class CommodityList(generics.ListEndpoint):
    """List pesticide commodities (crops and sites where pesticides are applied)."""

    model = Commodity
    serializer_class = CommoditySerializer
    filter_class = CommodityFilter
    paginate = True


class CommodityDetail(generics.DetailEndpoint):
    """Retrieve a single commodity with its associated chemicals and products."""

    model = Commodity
    serializer_class = CommodityDetailSerializer
    lookup_field = 'sqid'
    lookup_url_kwarg = 'commodity_id'

    def get_queryset(self):
        return Commodity.objects.with_chemicals().with_products()


class ChemicalList(generics.ListEndpoint):
    """List pesticide chemicals with optional filtering by name, category, and IARC classification."""

    model = Chemical
    serializer_class = ChemicalSerializer
    filter_class = ChemicalFilter
    paginate = True


class ChemicalDetail(generics.DetailEndpoint):
    """Retrieve a single chemical with its associated products and commodities."""

    model = Chemical
    serializer_class = ChemicalDetailSerializer
    lookup_field = 'sqid'
    lookup_url_kwarg = 'chemical_id'

    def get_queryset(self):
        return Chemical.objects.prefetch_related(
            Prefetch('products', queryset=Product.objects.with_restricted())
        ).with_commodities()


class ProductList(generics.ListEndpoint):
    """List registered pesticide products."""

    model = Product
    serializer_class = ProductSerializer
    filter_class = ProductFilter
    paginate = True

    def get_queryset(self):
        return Product.objects.with_restricted()


class ProductDetail(generics.DetailEndpoint):
    """Retrieve a single pesticide product with its associated chemicals and commodities."""

    model = Product
    serializer_class = ProductDetailSerializer
    lookup_field = 'sqid'
    lookup_url_kwarg = 'product_id'

    def get_queryset(self):
        return Product.objects.with_restricted().prefetch_related('chemicals').with_commodities()


class PesticideUseMixin:
    model = PesticideUse
    serializer_class = PesticideUseSerializer
    paginate = True

    def get_queryset(self):
        # `product` is select_related, so it can't carry with_restricted()'s
        # annotation; prefetching its chemicals instead makes is_restricted's
        # fallback one query for the page rather than one per row.
        return (super().get_queryset()
            .select_related('county', 'mtrs', 'product', 'chemical', 'commodity', 'fume_method')
            .prefetch_related('product__chemicals'))


class PesticideUseList(PesticideUseMixin, generics.ListEndpoint):
    """List pesticide use records from California DPR's Pesticide Use Reporting (PUR) database."""

    filter_class = PesticideUseFilter


class PesticideUseDetail(PesticideUseMixin, generics.DetailEndpoint):
    """Retrieve a single pesticide use record."""

    lookup_field = 'sqid'
    lookup_url_kwarg = 'use_id'


class PesticideNoticeMixin:
    model = PesticideNotice
    serializer_class = PesticideNoticeSerializer
    paginate = True

    def get_queryset(self):
        return super().get_queryset().select_related('county').prefetch_related(
            'chemicals',
            Prefetch('products', queryset=Product.objects.with_restricted()),
        )


class PesticideNoticeList(PesticideNoticeMixin, generics.ListEndpoint):
    """List upcoming pesticide application notices from CDFA's Notice of Intent (NOI) program."""

    filter_class = PesticideNoticeFilter


class PesticideNoticeDetail(PesticideNoticeMixin, generics.DetailEndpoint):
    """Retrieve a single pesticide application notice."""

    lookup_field = 'sqid'
    lookup_url_kwarg = 'notice_id'


class PesticideRegionMixin:
    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.region = get_object_or_404(
            Region.all_objects.select_related('boundary'),
            sqid=self.kwargs['region_id'],
        )

    def get_region_queryset(self, queryset):
        if self.region.type == Region.Type.COUNTY:
            return queryset.filter(county=self.region)
        try:
            geometry = self.region.boundary.geometry
        except AttributeError:
            return queryset.none()
        return queryset.filter(mtrs__boundary__geometry__intersects=geometry)


class PesticideRegionSummary(PesticideRegionMixin, generics.ListEndpoint):
    """
    Aggregate pesticide use records by chemical, commodity, and year for a region.

    County regions use a direct FK; all other region types use an MTRS spatial join.
    """

    model = PesticideUse
    serializer_class = PesticideSummaryResponseSerializer
    filter_class = PesticideSummaryFilter
    paginate = False

    def get_queryset(self):
        return self.get_region_queryset(PesticideUse.objects.all())

    def aggregate(self, queryset):
        return list(
            queryset
            .values('chemical_id', 'commodity_id', 'year')
            .annotate(
                total_lbs=Sum('lbs_chemical'),
                total_acres=Sum('acres_treated'),
                application_count=Count('id'),
            )
            .order_by('-year', 'chemical_id', 'commodity_id')
        )

    def build_rows(self, rows):
        chemical_ids = {r['chemical_id'] for r in rows if r['chemical_id']}
        commodity_ids = {r['commodity_id'] for r in rows if r['commodity_id']}
        chemicals = {c.pk: c for c in Chemical.objects.filter(pk__in=chemical_ids)}
        commodities = {c.pk: c for c in Commodity.objects.filter(pk__in=commodity_ids)}

        return [
            SimpleNamespace(
                year=row['year'],
                chemical=chemicals.get(row['chemical_id']),
                commodity=commodities.get(row['commodity_id']),
                total_lbs=row['total_lbs'],
                total_acres=row['total_acres'],
                application_count=row['application_count'],
            )
            for row in rows
        ]

    def get(self, request, region_id):
        queryset = self.get_queryset()
        queryset = self.filter_queryset(queryset)
        rows = self.build_rows(self.aggregate(queryset))
        return self.serialize(SimpleNamespace(
            region=self.region,
            data=rows,
            count=len(rows),
        ))


class PesticideRegionNotice(PesticideRegionMixin, PesticideNoticeMixin, generics.ListEndpoint):
    """List pesticide application notices for a region. County uses a direct FK; other region types use an MTRS spatial join."""

    filter_class = PesticideNoticeFilter

    def get_queryset(self):
        return self.get_region_queryset(super().get_queryset())


class PesticideRegionUse(PesticideRegionMixin, PesticideUseMixin, generics.ListEndpoint):
    """List pesticide use records for a region. County uses a direct FK; other region types use an MTRS spatial join."""

    filter_class = PesticideUseFilter

    def get_queryset(self):
        return self.get_region_queryset(super().get_queryset())


# Backs the entity picker (`includes/entity-picker.html`) on the explorer's
# list and records pages. One endpoint for all three kinds, so the picker JS
# only needs a single URL plus a `type`.
SEARCH_KINDS = {
    'chemical': (Chemical, 'chem_code'),
    'product': (Product, 'reg_number'),
    'commodity': (Commodity, 'site_code'),
}
# What each kind's bare CDPR code is called in a result's `detail`: a lone
# "560" or "524-475" doesn't say what it identifies.
SEARCH_CODE_LABELS = {
    'chemical': 'CDPR chem code',
    'product': 'CDPR reg. no.',
    'commodity': 'CDPR site code',
}
SEARCH_DEFAULT_LIMIT = 10
SEARCH_MAX_LIMIT = 25
SEARCH_MIN_LENGTH = 2


class EntitySearchBase(generics.Endpoint):
    # See the comment on sections.SectionListBase: the get() implementation
    # lives on this un-cached base so CachedEndpointMixin.get() on
    # EntitySearch below is the one actually dispatched to.
    def get(self, request):
        params = request.GET
        kind = params.get('type') or ''
        if kind not in SEARCH_KINDS:
            return http.Http400({'error': f'type must be one of {", ".join(sorted(SEARCH_KINDS))}'})

        model, detail_field = SEARCH_KINDS[kind]

        try:
            limit = int(params.get('limit') or SEARCH_DEFAULT_LIMIT)
        except ValueError:
            return http.Http400({'error': 'limit must be a number'})
        limit = max(1, min(limit, SEARCH_MAX_LIMIT))

        query = (params.get('q') or '').strip()
        if len(query) < SEARCH_MIN_LENGTH:
            return {'results': []}

        # Only names that actually appear in the use data -- in the year and
        # county the page is showing, when it says (`year=2020`, `year=all`,
        # `county=fresno`): suggesting one that filters the list down to
        # nothing isn't a useful suggestion.
        used = PesticideUseTotal.objects.filter(**{f'{kind}__isnull': False})
        year = (params.get('year') or '').strip()
        if year and year != 'all':
            if not year.isdigit():
                return http.Http400({'error': 'year must be a year or "all"'})
            used = used.filter(year=int(year))
        if params.get('county'):
            used = used.filter(county__slug=params['county'])
        used = used.values(kind)
        # Exact matches first, then prefix matches, then the rest: an
        # autocomplete for "sulfur" should lead with Sulfur, and "gly" with
        # the glyphosates, not every glycol that contains the letters. Within
        # a tier the closer text match leads, then the shorter shown name (so
        # "sulf" offers Sulfur before Sulfuric acid), then the alphabet.
        exact = Q(name__iexact=query)
        starts = Q(name__istartswith=query)
        # Typing a whole registration number, site code or CAS number is as exact as typing a name.
        if kind == 'chemical':
            exact |= Q(preferred_name__iexact=query)
            starts |= Q(preferred_name__istartswith=query)
            exact |= Q(cas_number__iexact=query)
            # A bare code ("1080") is shown as its preferred name
            # (display_chemical_name), so that is the length that matters.
            name_length = Case(
                When(name__regex=r'[A-Za-z]', then=Length('name')),
                default=Coalesce(Length(NullIf('preferred_name', Value(''))), Length('name')),
            )
        else:
            exact |= Q(**{f'{detail_field}__iexact': query})
            name_length = Length('name')
        queryset = (model.objects.search(query)
            .filter(pk__in=used)
            .annotate(
                tier=Case(When(exact, then=0), When(starts, then=1), default=2),
                name_length=name_length,
            )
            .order_by('tier', '-rank', 'name_length', 'name', 'pk'))

        # The explorer's narrowing: only the names applied under it in scope.
        # A totals row names one entity, so it can't answer for the others;
        # the rollup names all three on every row, and narrow_rows() knows
        # every narrowing, so no value is ever read as another.
        narrow = stats.resolve_narrow(params)
        if narrow:
            keys = stats.narrowed_keys(
                kind, narrow, int(year) if year.isdigit() else None, year == 'all' or not year,
                params.get('county') or None)
            queryset = queryset.filter(pk__in=list(keys))

        # A plain dict: CachedEndpointMixin caches it and wraps it in Http200.
        # Chemicals show their preferred name; the CDPR name rides along as
        # the detail when it differs, so a reader who typed "1080" sees why
        # "Sodium fluoroacetate" came up.
        def entry(obj):
            code = str(getattr(obj, detail_field) or '')
            detail = f'{SEARCH_CODE_LABELS[kind]} {code}' if code else ''
            alias = getattr(obj, 'cdpr_alias', '')
            if alias:
                detail = f'{alias} · {detail}' if detail else alias
            return {'id': obj.sqid, 'name': obj.display_name, 'detail': detail}

        return {'results': [entry(obj) for obj in queryset[:limit]]}


class EntitySearch(CachedEndpointMixin, EntitySearchBase):
    """
    Autocomplete over the chemicals, products, and commodities that appear in the use data.

    `type=chemical|product|commodity` (required), `q` (the search text; fewer
    than two characters returns no results), `year` (a year or `all`) and
    `county` (slug) to offer only names with reported use there, `narrow=concern|restricted|fumigant|aerial`
    (or the legacy `concern=1`) to offer only what that narrowing keeps, and
    `limit` (default 10, capped at 25). Each result carries the entity's `id` (sqid), `name`, and a
    `detail` string -- the CDPR chem code, registration number, or site code, labeled.
    """
    cache_timeout = 60 * 5


class SqidChoiceField(forms.CharField):
    """
    One of `model`'s rows by its sqid (the `id` its list endpoint returns), cleaned to the
    instance. Not a CDPR code: sqids can be all digits, so a code can't be told from an id.
    A value that isn't one of our ids is `invalid`; a well-formed id with no row (deleted
    or merged) is `not_found`, so a client can show a saved filter as retired.
    """

    MAX_PK = 2**63 - 1  # BigAutoField

    def __init__(self, model, **kwargs):
        self.model = model
        kwargs.setdefault('required', False)
        super().__init__(**kwargs)

    def clean(self, value):
        value = super().clean(value)
        if not value:
            return None
        codec = self.model._meta.get_field('sqid').sqids_instance
        decoded = codec.decode(value)
        # sqids decodes some other spellings to the same number; only the canonical one is an id.
        # Past the pk column's range it can't be a row, and the lookup itself would fail.
        if len(decoded) != 1 or decoded[0] > self.MAX_PK or codec.encode(decoded) != value:
            raise forms.ValidationError(
                f'Not a {self.model._meta.model_name} id.', code='invalid')
        try:
            return self.model.objects.get(pk=decoded[0])
        except self.model.DoesNotExist:
            raise forms.ValidationError(
                f'No {self.model._meta.model_name} has this id.', code='not_found')


class PesticidePlaceForm(forms.Form):
    chemical = SqidChoiceField(Chemical)
    commodity = SqidChoiceField(Commodity)
    product = SqidChoiceField(Product)
    category = forms.ChoiceField(required=False, choices=Chemical.Category.choices)
    iarc_group = forms.ChoiceField(required=False, choices=Chemical.IARCGroup.choices)
    aerial_ground = forms.ChoiceField(required=False, choices=PesticideUse.AerialGround.choices)
    year__gte = forms.IntegerField(required=False, min_value=1900, max_value=2100)
    year__lte = forms.IntegerField(required=False, min_value=1900, max_value=2100)


class PesticidePlace(generics.Endpoint):
    """Monthly and yearly pesticide use for a place (?region_type= & ?region=,
    or ?monitor=; filterable by ?chemical=, ?commodity=, ?product= (our ids, as the list
    endpoints return them), ?category=,
    ?iarc_group=, ?aerial_ground=, ?year__gte=, ?year__lte=)."""

    @staticmethod
    def error(response_class, err):
        response = response_class({'error': str(err)})
        response['Cache-Control'] = 'no-cache'
        return response

    def get(self, request, *args, **kwargs):
        try:
            place = resolve_place(request.GET)
        except PlaceNotFound as err:
            return self.error(http.Http404, err)
        except PlaceError as err:
            return self.error(http.Http400, err)

        form = PesticidePlaceForm(request.GET)
        if not form.is_valid():
            response = http.Http400({'errors': form.errors.get_json_data()})
            response['Cache-Control'] = 'no-cache'
            return response
        # Blank values are not filters.
        filters = {k: v for k, v in form.cleaned_data.items() if v not in (None, '')}

        def build():
            rows = rollup_rows_for(place)
            if 'chemical' in filters:
                rows = rows.filter(chemical_id=filters['chemical'].pk)
            if 'commodity' in filters:
                rows = rows.filter(commodity_id=filters['commodity'].pk)
            if 'product' in filters:
                rows = rows.filter(product_id=filters['product'].pk)
            if 'category' in filters:
                rows = rows.filter(chemical__categories__contains=[filters['category']])
            if 'iarc_group' in filters:
                rows = rows.filter(chemical__iarc_group=filters['iarc_group'])
            if 'aerial_ground' in filters:
                rows = rows.filter(method=filters['aerial_ground'])
            if 'year__gte' in filters:
                rows = rows.filter(year__gte=filters['year__gte'])
            if 'year__lte' in filters:
                rows = rows.filter(year__lte=filters['year__lte'])
            chemical_scoped = 'chemical' in filters
            multi_chemical = not chemical_scoped and ('category' in filters or 'iarc_group' in filters)
            return monthly_use(rows, chemical_scoped, multi_chemical)

        # Instances hash by their pk, so the key doesn't depend on how an id was spelled.
        keyed = {k: (v.pk if hasattr(v, 'pk') else v) for k, v in filters.items()}
        key = stats.all_years_key('place', _place_key('pesticides', place), hashlib.md5(json.dumps(sorted(keyed.items())).encode()).hexdigest())
        data = stats.cached(key, build, ttl=CACHE_TIMEOUT)

        response = http.Http200({'data': {'place': place_json(place), **data}})
        response['Cache-Control'] = 'public, max-age=3600'
        return response
