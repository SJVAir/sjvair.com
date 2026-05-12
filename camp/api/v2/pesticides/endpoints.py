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
    model = Commodity
    serializer_class = CommoditySerializer
    filter_class = CommodityFilter
    paginate = True


class CommodityDetail(generics.DetailEndpoint):
    model = Commodity
    serializer_class = CommodityDetailSerializer
    lookup_field = 'sqid'

    def get_queryset(self):
        return Commodity.objects.with_chemicals().with_products()


class ChemicalList(generics.ListEndpoint):
    model = Chemical
    serializer_class = ChemicalSerializer
    filter_class = ChemicalFilter
    paginate = True


class ChemicalDetail(generics.DetailEndpoint):
    model = Chemical
    serializer_class = ChemicalDetailSerializer
    lookup_field = 'sqid'

    def get_queryset(self):
        return Chemical.objects.prefetch_related('products').with_commodities()


class ProductList(generics.ListEndpoint):
    model = Product
    serializer_class = ProductSerializer
    filter_class = ProductFilter
    paginate = True


class ProductDetail(generics.DetailEndpoint):
    model = Product
    serializer_class = ProductDetailSerializer
    lookup_field = 'sqid'

    def get_queryset(self):
        return Product.objects.prefetch_related('chemicals').with_commodities()


class PesticideUseMixin:
    model = PesticideUse
    serializer_class = PesticideUseSerializer
    paginate = True

    def get_queryset(self):
        return super().get_queryset().select_related('product', 'chemical', 'commodity')


class PesticideUseList(PesticideUseMixin, generics.ListEndpoint):
    filter_class = PesticideUseFilter


class PesticideUseDetail(PesticideUseMixin, generics.DetailEndpoint):
    lookup_field = 'sqid'


class PesticideNoticeMixin:
    model = PesticideNotice
    serializer_class = PesticideNoticeSerializer
    paginate = True

    def get_queryset(self):
        return super().get_queryset().prefetch_related('chemicals', 'products')


class PesticideNoticeList(PesticideNoticeMixin, generics.ListEndpoint):
    filter_class = PesticideNoticeFilter


class PesticideNoticeDetail(PesticideNoticeMixin, generics.DetailEndpoint):
    lookup_field = 'sqid'
