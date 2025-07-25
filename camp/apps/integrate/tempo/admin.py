from django.contrib import admin

from .models import TempoGrid


@admin.register(TempoGrid)
class O3totAdmin(admin.ModelAdmin):
    date_hierarchy = 'timestamp'
    list_filter  = ['pollutant', ]
    readonly_fields = ['id', 'timestamp','pollutant', ]
    list_display = ['id', 'pollutant', 'timestamp',  ]
    ordering = ('-timestamp', )
    
    def has_add_permission(self, request, obj = None):
        return False
    
    def has_delete_permission(self, request, obj = None):
        return False
    
    def has_change_permission(self, request, obj = None):
        return False
    
    
# @admin.register(HchoFile)
# class O3totAdmin(admin.ModelAdmin):
#     date_hierarchy = 'timestamp'
#     readonly_fields = ['id', 'timestamp', ]
#     list_display = ['id', 'timestamp', 'file', ]
#     ordering = ('-timestamp', )
    
#     def has_add_permission(self, request, obj = None):
#         return False
    
#     def has_delete_permission(self, request, obj = None):
#         return False
    
#     def has_change_permission(self, request, obj = None):
#         return False
    
    
# @admin.register(No2File)
# class O3totAdmin(admin.ModelAdmin):
#     date_hierarchy = 'timestamp'
#     readonly_fields = ['id', 'timestamp', ]
#     list_display = ['id', 'timestamp', 'file', ]
#     ordering = ('-timestamp', )
    
#     def has_add_permission(self, request, obj = None):
#         return False
    
#     def has_delete_permission(self, request, obj = None):
#         return False
    
#     def has_change_permission(self, request, obj = None):
#         return False
    