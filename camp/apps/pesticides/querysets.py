from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db.models import BooleanField, Case, Exists, OuterRef, Prefetch, Q, QuerySet, Value, When


class SearchMixin:
    """
    Postgres full-text search following camp/apps/helpdesk/managers.py, plus an
    icontains fallback so partial tokens ("chlor") still match. Subclasses set
    `search_primary` (weight A) and `search_secondary` (weight B, an identifier
    column matched with icontains as well).
    """
    search_primary = 'name'
    search_secondary = None
    # Further name columns matched like the primary (weight A + icontains).
    search_aliases = ()

    def search(self, query):
        query = (query or '').strip()
        if not query:
            return self
        search_query = SearchQuery(query)
        search_vector = SearchVector(self.search_primary, weight='A')
        substring = Q(**{f'{self.search_primary}__icontains': query})
        for alias in self.search_aliases:
            search_vector = search_vector + SearchVector(alias, weight='A')
            substring = substring | Q(**{f'{alias}__icontains': query})
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
    search_aliases = ('preferred_name',)
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
        # with_restricted() so a serialized product's `is_restricted` reads an
        # annotation rather than walking its chemicals once per row.
        queryset = Product.objects.with_restricted()
        if filters:
            queryset = queryset.filter(**filters)
        return self.prefetch_related(
            Prefetch('products', queryset=queryset.distinct())
        )


class ProductQuerySet(SearchMixin, QuerySet):
    search_secondary = 'reg_number'

    @staticmethod
    def restricted_expression():
        """
        Whether a product is restricted: CDPR's per-product flag when its
        RESTRICTED.txt lists the product (it applies 3 CCR 6400's formulation
        and use exemptions), else -- NULL, not in the file -- whether any
        ingredient is on our 3 CCR 6400 list.
        """
        from camp.apps.pesticides.models import Chemical, ProductChemical
        return Case(
            When(california_restricted=True, then=Value(True)),
            When(california_restricted=False, then=Value(False)),
            default=Exists(ProductChemical.objects.filter(
                product=OuterRef('pk'),
                chemical__categories__contains=[Chemical.Category.CALIFORNIA_RESTRICTED],
            )),
            output_field=BooleanField(),
        )

    def with_restricted(self):
        """
        Annotate whether each product is restricted (see restricted_expression),
        so `Product.is_restricted` costs no query per row. Serializing a list
        without this walks each product's chemicals.
        """
        return self.annotate(restricted_status=self.restricted_expression())

    def restricted(self, value=True):
        """The products that are (or, with value=False, are not) restricted."""
        return self.alias(restricted_alias=self.restricted_expression()).filter(restricted_alias=value)
    def with_commodities(self, **filters):
        from camp.apps.pesticides.models import Commodity
        queryset = Commodity.objects.all()
        if filters:
            queryset = queryset.filter(**filters)
        return self.prefetch_related(
            Prefetch('commodities', queryset=queryset.distinct())
        )
