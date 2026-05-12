from resticus import generics

from camp.apps.pesticides.models import Chemical, Commodity, PesticideNotice, PesticideUse, Product

from .filters import ChemicalFilter, CommodityFilter, PesticideNoticeFilter, PesticideUseFilter, ProductFilter
from .serializers import (
    ChemicalSerializer,
    ChemicalDetailSerializer,
    CommoditySerializer,
    CommodityDetailSerializer,
    PesticideNoticeSerializer,
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
