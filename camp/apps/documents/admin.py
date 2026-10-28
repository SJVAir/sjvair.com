from django.contrib import admin, messages

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
    # (and would list its changes and snapshots on the confirmation page), so it is not offered.
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

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
