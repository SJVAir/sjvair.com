from django.contrib import admin
from django.utils.safestring import mark_safe

from camp.utils.admin import ReadOnlyAdminMixin

from .models import Granule


@admin.register(Granule)
class GranuleAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    date_hierarchy = 'timestamp'
    list_display = ('preview_thumbnail', 'product', 'timestamp', 'version', 'is_final')
    list_filter = ('product', 'is_final', 'version')
    search_fields = ('sqid__exact',)
    ordering = ('-timestamp',)
    readonly_fields = ('sqid', 'product', 'timestamp', 'version', 'is_final', 'preview_display', 'bounds_display')

    fieldsets = [
        (None, {
            'fields': ['sqid', 'product', 'timestamp', ('version', 'is_final')],
        }),
        ('Preview', {
            'fields': ['preview_display'],
        }),
        ('Location', {
            'fields': ['bounds_display'],
        }),
    ]

    @admin.display(description='Preview')
    def preview_thumbnail(self, granule):
        if not granule.preview:
            return '—'
        return mark_safe(f'<img src="{granule.preview.url}" style="height: 40px;" />')

    @admin.display(description='Preview')
    def preview_display(self, granule):
        if not granule.preview:
            return '—'
        return mark_safe(f'<img src="{granule.preview.url}" style="max-width: 600px;" />')

    @admin.display(description='Bounds')
    def bounds_display(self, granule):
        # A plain extent reads better than raw WKT here, and every granule
        # shares roughly the same clipped AOI, so a per-row rendered map
        # (which would also mean a live basemap-tile fetch on every admin
        # page load) wouldn't carry much differentiating information --
        # the preview image is the visual that actually varies per row.
        if not granule.bounds:
            return '—'
        lon_min, lat_min, lon_max, lat_max = granule.bounds.extent
        return f'{lat_min:.3f}, {lon_min:.3f} to {lat_max:.3f}, {lon_max:.3f}'
