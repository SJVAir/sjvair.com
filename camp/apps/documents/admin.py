from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied

from .models import BlockedBuild, DocumentProfile, SavedDocument

# Staff see metadata only. A private dashboard's body, snapshots, and change log are never shown,
# so DocumentChange, DocumentSnapshot, and PurgedDocument are deliberately not registered, and
# no field, column, search, or action here reads `body`.
METADATA = [
    'id',
    'owner',
    'kind',
    'name',
    'visibility',
    'size',
    'version',
    'created_at',
    'updated_at',
    'deleted_at',
    'sharing_disabled',
]


@admin.register(SavedDocument)
class SavedDocumentAdmin(admin.ModelAdmin):
    list_display = METADATA
    list_select_related = ['owner']
    list_filter = ['visibility', 'sharing_disabled']
    search_fields = ['id', 'owner__email']
    ordering = ['-updated_at']
    fields = METADATA
    readonly_fields = [name for name in METADATA if name != 'sharing_disabled']
    actions = ['disable_share_links', 'enable_share_links']

    # Deleting here would remove a user's dashboard without leaving a PurgedDocument record
    # (and would list its changes and snapshots on the confirmation page), so there is no delete
    # view, action, or link. The delete permission itself stays the usual one: deleting a User
    # cascades to their dashboards, and Django's User delete page needs it to allow that.
    def has_add_permission(self, request):
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions

    def delete_view(self, request, object_id, extra_context=None):
        raise PermissionDenied

    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = {**(extra_context or {}), 'show_delete': False}
        return super().change_view(request, object_id, form_url, extra_context)

    @admin.action(description='Disable share links for the selected documents')
    def disable_share_links(self, request, queryset):
        count = queryset.update(sharing_disabled=True)
        self.message_user(request, f'Disabled share links on {count} documents.', messages.SUCCESS)

    @admin.action(description='Enable share links for the selected documents')
    def enable_share_links(self, request, queryset):
        count = queryset.update(sharing_disabled=False)
        self.message_user(request, f'Enabled share links on {count} documents.', messages.SUCCESS)


@admin.register(DocumentProfile)
class DocumentProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'display_name', 'sharing_blocked']
    list_filter = ['sharing_blocked']
    search_fields = ['user__email', 'display_name']
    raw_id_fields = ['user']
    fields = ['user', 'display_name', 'sharing_blocked']


@admin.register(BlockedBuild)
class BlockedBuildAdmin(admin.ModelAdmin):
    list_display = ['build_id', 'note', 'created_at']
    search_fields = ['build_id', 'note']
    fields = ['build_id', 'note']
