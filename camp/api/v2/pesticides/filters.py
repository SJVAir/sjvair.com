import django_filters
from django.utils import timezone
from resticus.filters import FilterSet

from camp.apps.pesticides.models import Chemical, Commodity, PesticideNotice, PesticideUse, Product


class ChemicalFilter(FilterSet):
    name = django_filters.CharFilter(field_name='name', lookup_expr='icontains')
    category = django_filters.CharFilter(method='filter_category')

    def filter_category(self, queryset, name, value):
        return queryset.filter(categories__contains=[value])

    class Meta:
        model = Chemical
        fields = {
            'chem_code': ['exact'],
            'iarc_group': ['exact'],
        }


class CommodityFilter(FilterSet):
    name = django_filters.CharFilter(field_name='name', lookup_expr='icontains')

    class Meta:
        model = Commodity
        fields = {
            'site_code': ['exact'],
        }


class ProductFilter(FilterSet):
    name = django_filters.CharFilter(field_name='name', lookup_expr='icontains')

    class Meta:
        model = Product
        fields = {
            'fumigant': ['exact'],
            'california_restricted': ['exact'],
        }


class PesticideUseFilter(FilterSet):
    county = django_filters.CharFilter(field_name='county__slug')
    chemical = django_filters.NumberFilter(field_name='chemical__chem_code')
    product = django_filters.NumberFilter(field_name='product__prodno')

    class Meta:
        model = PesticideUse
        fields = {
            'year': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'aerial_ground': ['exact'],
            'application_date': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'mtrs__boundary__geometry': ['distance_lt', 'distance_gt', 'bbcontains', 'bboverlaps'],
        }


class PesticideSummaryFilter(FilterSet):
    chemical = django_filters.NumberFilter(field_name='chemical__chem_code')
    commodity = django_filters.CharFilter(field_name='commodity__site_code')
    category = django_filters.CharFilter(method='filter_category')
    iarc_group = django_filters.CharFilter(field_name='chemical__iarc_group')

    def filter_category(self, queryset, name, value):
        return queryset.filter(chemical__categories__contains=[value])

    class Meta:
        model = PesticideUse
        fields = {
            'year': ['exact', 'lte', 'gte'],
            'aerial_ground': ['exact'],
        }


class PesticideNoticeFilter(FilterSet):
    county = django_filters.CharFilter(field_name='county__slug')
    chemical = django_filters.NumberFilter(field_name='chemicals__chem_code')
    product = django_filters.NumberFilter(field_name='products__prodno')
    upcoming = django_filters.BooleanFilter(method='filter_upcoming')

    def filter_upcoming(self, queryset, name, value):
        if value:
            return queryset.filter(scheduled_application__gte=timezone.now())
        return queryset

    class Meta:
        model = PesticideNotice
        fields = {
            'application_method': ['exact', 'iexact'],
            'scheduled_application': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'point': ['distance_lt', 'distance_gt', 'bbcontains', 'bboverlaps'],
        }
