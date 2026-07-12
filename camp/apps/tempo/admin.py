from django.contrib import admin

from .models import Granule


@admin.register(Granule)
class GranuleAdmin(admin.ModelAdmin):
    list_display = ('product', 'timestamp', 'version', 'is_final')
    list_filter = ('product', 'is_final', 'version')
    search_fields = ('sqid__exact',)
    date_hierarchy = 'timestamp'
    exclude = ('raster', 'bounds')
