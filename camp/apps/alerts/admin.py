from django.contrib import admin
from .models import Subscription, Alert


class SubscriptionInline(admin.TabularInline):
    extra = 0
    fields = ['monitor', 'level']
    model = Subscription
    raw_id_fields = ['monitor']


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ['monitor', 'county', 'level', 'start_time', 'end_time']
    list_filter = ['start_time', 'level', 'monitor__county']

    def county(self, instance):
        return instance.monitor.county
