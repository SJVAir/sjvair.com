from django.urls import reverse
from django.utils.safestring import mark_safe


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
