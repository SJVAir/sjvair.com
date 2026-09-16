from django.db.models import Count, F, FloatField, IntegerField, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce
from django.http import Http404
from django.shortcuts import redirect

import vanilla

from camp.apps.pesticides import stats
from camp.apps.pesticides.forms import ChemicalFilterForm, CommodityFilterForm, ProductFilterForm
from camp.apps.pesticides.models import (
    Chemical, Commodity, PesticideNotice, PesticideUse, Product, ProductChemical,
)

# Sentinel for "sqid didn't resolve to an object" in ExplorerListMixin.related.
# Not Http404 -- that's an exception class, not a value, and using it as a
# dict value / membership check reads as if it might be raised.
MISSING = object()


def lbs_subquery(field, year, lbs_field='lbs_chemical'):
    """Sum of pounds in `year` for the outer row, via `PesticideUse.<field>`."""
    return Subquery(
        PesticideUse.objects
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
    """PKs of `target` (a PesticideUse FK name) that share a use record with obj."""
    return PesticideUse.objects.filter(**{field: obj}).values(target)


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
        self.latest_year = stats.latest_year()
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
        queryset = self.annotate_queryset(queryset, self.latest_year)
        self.sort, field, desc = self.get_sort()
        if field:
            expr = F(field).desc(nulls_last=True) if desc else F(field).asc(nulls_last=True)
            queryset = queryset.order_by(expr, 'name')
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
            latest_year=self.latest_year,
            result_count=count,
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
            PesticideUse.objects
            .filter(commodity=OuterRef('pk'), year=year)
            .values('commodity')
            .annotate(n=Count('chemical', distinct=True))
            .values('n'),
        )
        return queryset.annotate(
            lbs_applied=lbs_subquery('commodity', year),
            chemical_count=Coalesce(chemical_count, 0),
        )


class ChemicalDetail(vanilla.TemplateView):
    template_name = 'pesticides/chemical-detail.html'


class ProductDetail(vanilla.TemplateView):
    template_name = 'pesticides/product-detail.html'


class CommodityDetail(vanilla.TemplateView):
    template_name = 'pesticides/commodity-detail.html'
