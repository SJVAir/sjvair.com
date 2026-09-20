from types import SimpleNamespace

from django.db.models import Case, Count, Q, Sum, When
from django.shortcuts import get_object_or_404

from resticus import generics, http

from camp.apps.pesticides.models import Chemical, Commodity, PesticideNotice, PesticideUse, PesticideUseTotal, Product
from camp.apps.regions.models import Region
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
        return Chemical.objects.prefetch_related('products').with_commodities()


class ProductList(generics.ListEndpoint):
    """List registered pesticide products."""

    model = Product
    serializer_class = ProductSerializer
    filter_class = ProductFilter
    paginate = True


class ProductDetail(generics.DetailEndpoint):
    """Retrieve a single pesticide product with its associated chemicals and commodities."""

    model = Product
    serializer_class = ProductDetailSerializer
    lookup_field = 'sqid'
    lookup_url_kwarg = 'product_id'

    def get_queryset(self):
        return Product.objects.prefetch_related('chemicals').with_commodities()


class PesticideUseMixin:
    model = PesticideUse
    serializer_class = PesticideUseSerializer
    paginate = True

    def get_queryset(self):
        return super().get_queryset().select_related('county', 'mtrs', 'product', 'chemical', 'commodity')


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
        return super().get_queryset().select_related('county').prefetch_related('chemicals', 'products')


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
            Region.objects.select_related('boundary'),
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

        # Only names that actually appear in the use data: suggesting one that
        # filters every list down to nothing isn't a useful suggestion.
        used = PesticideUseTotal.objects.filter(**{f'{kind}__isnull': False}).values(kind)
        # Prefix matches first: an autocomplete for "gly" should lead with
        # the glyphosates, not with every glycol that contains the letters.
        starts = Q(name__istartswith=query)
        if kind == 'chemical':
            starts |= Q(preferred_name__istartswith=query)
        queryset = (model.objects.search(query)
            .filter(pk__in=used)
            .annotate(prefix=Case(When(starts, then=0), default=1))
            .order_by('prefix', '-rank', 'name', 'pk'))

        # A plain dict: CachedEndpointMixin caches it and wraps it in Http200.
        # Chemicals show their preferred name; the CDPR name rides along as
        # the detail when it differs, so a reader who typed "1080" sees why
        # "Sodium fluoroacetate" came up.
        def entry(obj):
            detail = str(getattr(obj, detail_field) or '')
            alias = getattr(obj, 'cdpr_alias', '')
            if alias:
                detail = f'{alias} · {detail}' if detail else alias
            return {'id': obj.sqid, 'name': obj.display_name, 'detail': detail}

        return {'results': [entry(obj) for obj in queryset[:limit]]}


class EntitySearch(CachedEndpointMixin, EntitySearchBase):
    """
    Autocomplete over the chemicals, products, and commodities that appear in the use data.

    `type=chemical|product|commodity` (required), `q` (the search text; fewer
    than two characters returns no results), and `limit` (default 10, capped
    at 25). Each result carries the entity's `id` (sqid), `name`, and a
    `detail` string -- chem code, registration number, or site code.
    """
    cache_timeout = 60 * 5
