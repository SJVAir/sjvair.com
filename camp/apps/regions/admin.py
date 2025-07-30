from base64 import b64encode

import yaml

from django.contrib import admin, messages
from django.contrib.gis.admin import OSMGeoAdmin
from django.utils.safestring import mark_safe

from camp.apps.regions.models import Region, Boundary
from camp.utils import maps


class BoundaryInline(admin.TabularInline):
    model = Boundary
    readonly_fields = ['get_map', 'get_info']
    extra = 0
    show_change_link = True

    def get_fields(self, request, obj=None):
        return self.readonly_fields

    def get_info(self, instance):
        return mark_safe(f'''
            <dl>
                <dt>Version</dt>
                <dd>{instance.version}</dd>
                <dt>Created</dt>
                <dd>{instance.created}</dd>
                <dt>Metadata</dt>
                <dd><pre>{yaml.dump(instance.metadata).strip()}</pre></dd>
            </dl>
        ''')
    get_info.short_description = 'Boundary Information'

    def get_map(self, instance):
        img = maps.from_geometries(instance.geometry, format='png', buffer=0.5)
        content = b64encode(img.getvalue()).decode()
        return mark_safe(f'<img src="data:image/png;base64,{content}" data-key="{instance.pk}" alt="v{instance.version} Map" />')
    get_map.short_description = 'Map'


@admin.register(Region)
class RegionAdmin(OSMGeoAdmin):
    inlines = [BoundaryInline]
    list_display = ['name', 'type', 'external_id', 'current_version']
    list_filter = ['type']
    readonly_fields = ['name', 'slug', 'external_id', 'type', 'boundary']
    search_fields = ['name', 'external_id']

    def current_version(self, instance):
        return instance.boundary.version if instance.boundary else '-'
    current_version.short_description = 'Version'

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        messages.add_message(request, messages.WARNING, "The next message is a lie:")
        pass

    def save_formset(self, request, form, formset, change):
        pass
