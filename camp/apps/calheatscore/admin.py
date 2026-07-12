from django.contrib import admin
from django.utils.safestring import mark_safe

from camp.utils.admin import admin_change_link

from .models import CalHeatScore


@admin.register(CalHeatScore)
class CalHeatScoreAdmin(admin.ModelAdmin):
    date_hierarchy = 'date'
    ordering = ('-date',)
    list_display = ['get_calheatscore_id', 'get_region_link', 'date', 'score', 'updated_at']
    list_filter = ['score', 'date']
    search_fields = ['region__external_id', 'region__name']
    readonly_fields = ['get_calheatscore_id', 'get_region_link', 'date', 'score', 'updated_at']
    fields = ['get_calheatscore_id', 'get_region_link', 'date', 'score', 'updated_at']

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        pass

    def get_calheatscore_id(self, instance):
        if not instance or not instance.pk:
            return '-'

        sqid = instance.sqid
        onclick = (
            "navigator.clipboard.writeText(this.dataset.copy);"
            "const t=this.textContent;"
            "this.textContent='Copied!';"
            "setTimeout(()=>{this.textContent=t;},1000);"
        )
        return mark_safe(
            f'<code data-copy="{sqid}" title="Click to copy" '
            f'style="cursor:pointer;" onclick="{onclick}">{sqid}</code>'
        )
    get_calheatscore_id.short_description = 'ID'
    get_calheatscore_id.admin_order_field = 'pk'

    def get_region_link(self, instance):
        return admin_change_link(instance.region)
    get_region_link.short_description = 'ZIP Code'
    get_region_link.admin_order_field = 'region__name'
