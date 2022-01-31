from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import ugettext_lazy as _

from camp.apps.accounts.models import User
from camp.apps.alerts.admin import SubscriptionInline


@admin.register(User)
class UserAdmin(UserAdmin):
    fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('full_name', 'email', ('phone', 'phone_verified'), 'language', 'password', 'last_login', 'date_joined'),
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
            'fields': ('full_name', 'email', 'phone', 'language')
        }),
        ('Password', {
            'classes': ('wide',),
            'fields': ('password1', 'password2')
        }),
    )
    inlines = [SubscriptionInline]
    list_display = ('email', 'full_name', 'date_joined', 'is_staff', 'is_active')
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'language', 'groups')
    ordering = ('email',)
    readonly_fields = ('date_joined', 'last_login')
    search_fields = ('email', 'full_name')
