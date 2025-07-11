from django.contrib import admin
from django.urls import path

from .models import Subscription, Alert
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
