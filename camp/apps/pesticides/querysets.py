from django.db.models import Prefetch, QuerySet


class ChemicalQuerySet(QuerySet):
    def with_commodities(self, **filters):
        from camp.apps.pesticides.models import Commodity
        queryset = Commodity.objects.all()
        if filters:
            queryset = queryset.filter(**filters)
        return self.prefetch_related(
            Prefetch('commodities', queryset=queryset.distinct())
        )


class CommodityQuerySet(QuerySet):
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


class ProductQuerySet(QuerySet):
    def with_commodities(self, **filters):
        from camp.apps.pesticides.models import Commodity
        queryset = Commodity.objects.all()
        if filters:
            queryset = queryset.filter(**filters)
        return self.prefetch_related(
            Prefetch('commodities', queryset=queryset.distinct())
        )
