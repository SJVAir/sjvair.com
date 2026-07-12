from django.contrib import admin
from django.urls import path

from .models import Subscription, Alert, AlertUpdate, Notification
from .views import SubscriptionCountyStats


class SubscriptionInline(admin.TabularInline):
    extra = 0
    fields = ['monitor', 'level']
    model = Subscription
    raw_id_fields = ['monitor']


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ['user', 'monitor', 'level']
    list_filter = ['level', 'monitor__county']

    def get_urls(self):
        return [
            path(
                "county-stats/",
                self.admin_site.admin_view(SubscriptionCountyStats.as_view()),
                name=f"alerts_subscription_county_stats",
            ),
            *super().get_urls(),
        ]


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ['monitor', 'county', 'start_time', 'end_time']
    list_filter = ['start_time', 'monitor__county']

    def county(self, instance):
        return instance.monitor.county


@admin.register(AlertUpdate)
class AlertUpdateAdmin(admin.ModelAdmin):
    list_display = ['alert', 'timestamp', 'level']
    list_filter = ['level']
    raw_id_fields = ['alert']


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'status', 'created', 'sent_at']
    list_filter = ['status']
    raw_id_fields = ['alert_update', 'subscription', 'user']
    readonly_fields = ['created', 'modified']
