from django import forms
from django.urls import reverse
from django.utils.safestring import mark_safe


class MapFigureMixin:
    """
    Loads the MapTiler SDK and the map figure initializer for admins (and
    inlines) that render maps via ``camp.utils.mapfigure.MapFigure``.

    Implemented as a ``media`` property rather than an inner ``Media``
    class so it still applies when the admin defines its own ``Media``
    (which would otherwise shadow the mixin's). Must precede the
    ModelAdmin / InlineModelAdmin base in the class's bases.
    """
    map_figure_media = forms.Media(
        css={
            'all': [
                'maptiler-sdk/maptiler-sdk.css',
                'js/admin/map-figure.css',
            ],
        },
        js=[
            'maptiler-sdk/maptiler-sdk.js',
            'js/maps/core.js',
            'js/maps/controls.js',
            'js/maps/chrome.js',
            'js/maps/shell.js',
            'js/maps/registry.js',
            'js/admin/map-figure.js',
        ],
    )

    @property
    def media(self):
        return super().media + self.map_figure_media


class ReadOnlyAdminMixin:
    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


def admin_change_link(obj, label=None):
    if obj is None:
        return '-'
    url = reverse(f'admin:{obj._meta.app_label}_{obj._meta.model_name}_change', args=[obj.pk])
    return mark_safe(f'<a href="{url}">{label or obj}</a>')
