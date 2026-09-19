from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db.models import Prefetch, Q, QuerySet


class SearchMixin:
    """
    Postgres full-text search following camp/apps/helpdesk/managers.py, plus an
    icontains fallback so partial tokens ("chlor") still match. Subclasses set
    `search_primary` (weight A) and `search_secondary` (weight B, an identifier
    column matched with icontains as well).
    """
    search_primary = 'name'
    search_secondary = None

    def search(self, query):
        query = (query or '').strip()
        if not query:
            return self
        search_query = SearchQuery(query)
        search_vector = SearchVector(self.search_primary, weight='A')
        substring = Q(**{f'{self.search_primary}__icontains': query})
        if self.search_secondary:
            search_vector = search_vector + SearchVector(self.search_secondary, weight='B')
            substring = substring | Q(**{f'{self.search_secondary}__icontains': query})
        return (self
            .annotate(search=search_vector, rank=SearchRank(search_vector, search_query))
            .filter(Q(search=search_query) | substring)
            .order_by('-rank', self.search_primary, 'pk')
        )


class ChemicalQuerySet(SearchMixin, QuerySet):
    search_secondary = 'cas_number'
    def with_commodities(self, **filters):
        from camp.apps.pesticides.models import Commodity
        queryset = Commodity.objects.all()
        if filters:
            queryset = queryset.filter(**filters)
        return self.prefetch_related(
            Prefetch('commodities', queryset=queryset.distinct())
        )


class CommodityQuerySet(SearchMixin, QuerySet):
    search_secondary = 'site_code'
    def with_chemicals(self, **filters):
        from camp.apps.pesticides.models import Chemical
        queryset = Chemical.objects.all()
        if filters:
            queryset = queryset.filter(**filters)
        return self.prefetch_related(
            Prefetch('chemicals', queryset=queryset.distinct())
        )

    def with_products(self, **filters):
        from camp.apps.pesticides.models import Product
        queryset = Product.objects.all()
        if filters:
            queryset = queryset.filter(**filters)
        return self.prefetch_related(
            Prefetch('products', queryset=queryset.distinct())
        )


class ProductQuerySet(SearchMixin, QuerySet):
    search_secondary = 'reg_number'
    def with_commodities(self, **filters):
        from camp.apps.pesticides.models import Commodity
        queryset = Commodity.objects.all()
        if filters:
            queryset = queryset.filter(**filters)
        return self.prefetch_related(
            Prefetch('commodities', queryset=queryset.distinct())
        )
