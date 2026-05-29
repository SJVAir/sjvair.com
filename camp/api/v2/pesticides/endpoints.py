from types import SimpleNamespace

from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404

from resticus import generics

from camp.apps.pesticides.models import Chemical, Commodity, PesticideNotice, PesticideUse, Product
from camp.apps.regions.models import Region

from .filters import ChemicalFilter, CommodityFilter, PesticideNoticeFilter, PesticideSummaryFilter, PesticideUseFilter, ProductFilter
from .serializers import (
    ChemicalSerializer,
    ChemicalDetailSerializer,
    CommoditySerializer,
    CommodityDetailSerializer,
    PesticideNoticeSerializer,
    PesticideSummaryResponseSerializer,
    PesticideSummarySerializer,
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
        return super().get_queryset().select_related('product', 'chemical', 'commodity')


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
        return super().get_queryset().prefetch_related('chemicals', 'products')


class PesticideNoticeList(PesticideNoticeMixin, generics.ListEndpoint):
    """List upcoming pesticide application notices from CDFA's Notice of Intent (NOI) program."""

    filter_class = PesticideNoticeFilter


class PesticideNoticeDetail(PesticideNoticeMixin, generics.DetailEndpoint):
    """Retrieve a single pesticide application notice."""

    lookup_field = 'sqid'
    lookup_url_kwarg = 'notice_id'


class PesticideSummary(generics.ListEndpoint):
    """
    Aggregate pesticide use records by chemical, commodity, and year for a region.

    The region is specified as a sqid in the URL path. County uses a direct FK;
    all other region types use an MTRS spatial join.
    """

    model = PesticideUse
    serializer_class = PesticideSummaryResponseSerializer
    filter_class = PesticideSummaryFilter
    paginate = False

    def get_queryset(self):
        self.region = get_object_or_404(
            Region.objects.select_related('boundary'),
            sqid=self.kwargs['region_id'],
        )
        if self.region.type == Region.Type.COUNTY:
            return PesticideUse.objects.filter(county=self.region)
        try:
            geometry = self.region.boundary.geometry
        except AttributeError:
            return PesticideUse.objects.none()
        return PesticideUse.objects.filter(
            mtrs__boundary__geometry__intersects=geometry
        )

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
