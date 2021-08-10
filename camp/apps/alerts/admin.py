from django.contrib import admin
from .models import Subscription


class SubscriptionInline(admin.TabularInline):
    extra = 0
    fields = ['monitor', 'level']
    model = Subscription
    raw_id_fields = ['monitor']
