from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import ugettext_lazy as _

from aqm.apps.accounts.models import User


@admin.register(User)
class UserAdmin(UserAdmin):
    fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'full_name', 'password', 'last_login', 'date_joined'),
        }),
        (_('Permissions'), {
            'classes': ('wide', 'collapse',),
            'fields': (
                'is_active', 'is_staff', 'is_superuser', 'groups',
                'user_permissions',
            ),
        }),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'full_name')
        }),
        ('Password', {
            'classes': ('wide',),
            'fields': ('password1', 'password2')
        }),
    )
    list_display = ('email', 'full_name', 'date_joined', 'is_staff', 'is_active')
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'groups')
    ordering = ('email',)
    readonly_fields = ('date_joined', 'last_login')
    search_fields = ('email', 'full_name')
