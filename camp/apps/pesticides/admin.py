from django.contrib import admin

from camp.apps.pesticides.models import Chemical, Commodity, Product, ProductChemical, PURRecord
from camp.utils.admin import ReadOnlyAdminMixin, admin_change_link


class ProductChemicalInline(ReadOnlyAdminMixin, admin.TabularInline):
    model = ProductChemical
    extra = 0
    raw_id_fields = ['chemical']


@admin.register(Chemical)
class ChemicalAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ['name', 'chem_code', 'cas_number', 'categories']
    search_fields = ['name', 'chem_code', 'cas_number']
    list_filter = ['categories']


@admin.register(Commodity)
class CommodityAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ['name', 'site_code']
    search_fields = ['name', 'site_code']


@admin.register(Product)
class ProductAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ['name', 'prodno', 'reg_number', 'fumigant', 'california_restricted']
    search_fields = ['name', 'prodno', 'reg_number']
    list_filter = ['fumigant', 'california_restricted']
    inlines = [ProductChemicalInline]


@admin.register(PURRecord)
class PURRecordAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    date_hierarchy = 'application_date'
    list_display = ['year', 'use_no', 'get_county', 'get_mtrs', 'get_commodity', 'get_product', 'get_chemical', 'lbs_chemical', 'acres_treated', 'application_date']
    list_filter = ['aerial_ground', 'county', 'product__fumigant', 'product__california_restricted']
    list_select_related = ['county', 'mtrs', 'commodity', 'product', 'chemical']
    ordering = ['-application_date']
    raw_id_fields = ['county', 'mtrs', 'product', 'chemical', 'commodity']
    search_fields = ['use_no', 'comtrs', 'chemical__name', 'product__name', 'commodity__name', 'county__name']
    show_full_result_count = False

    def get_county(self, instance):
        return admin_change_link(instance.county, instance.county.name)
    get_county.short_description = 'County'

    def get_mtrs(self, instance):
        return admin_change_link(instance.mtrs, instance.mtrs.name if instance.mtrs else None)
    get_mtrs.short_description = 'MTRS'

    def get_chemical(self, instance):
        return admin_change_link(instance.chemical)
    get_chemical.short_description = 'Chemical'

    def get_commodity(self, instance):
        return admin_change_link(instance.commodity)
    get_commodity.short_description = 'Commodity'

    def get_product(self, instance):
        return admin_change_link(instance.product)
    get_product.short_description = 'Product'
