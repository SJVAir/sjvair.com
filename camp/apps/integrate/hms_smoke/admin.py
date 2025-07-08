from django.contrib import admin
from .models import Smoke

@admin.register(Smoke)
class SmokeAdmin(admin.ModelAdmin):
    date_hierarchy = 'date'
    list_filters = ['satellite', 'density', 'is_final']
    readonly_fields = ['id', 'satellite', 'density', 'is_final', 'start', 'end', 'geometry']
    can_delete = False