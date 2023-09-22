from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path 

from camp.utils.views import PageTemplate, AdminStats, FlushQueue, RenderStatic

admin.site.site_title = "SJVAir Admin"
admin.site.site_header = "SJVAir Admin"
# admin.site.site_url = None

urlpatterns = [
    path('api/', include('camp.api.urls', namespace='api')),
    path('account/', include(('camp.apps.accounts.urls', 'account'), namespace='account')),

    # @sjvair/monitor-map specific routes
    path('monitor/<monitor_id>/', PageTemplate.as_view(template_name='pages/index.html')),
    path('widget/', RenderStatic.as_view(static_file='widget/index.html')),

    # Admin-y stuff
    path('admin/', include('admin_honeypot.urls', namespace='admin_honeypot')),
    path('batcave/stats.json', AdminStats.as_view(), name='admin-stats'),
    path('batcave/flush-queue/<str:key>/', FlushQueue.as_view(), name='flush-queue'),
    path('batcave/', admin.site.urls),
]

if settings.DEBUG:
    import debug_toolbar
    urlpatterns += [path('__debug__/', include(debug_toolbar.urls))]
    # urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Catch-all to render templates based on the path
urlpatterns += [re_path('^', PageTemplate.as_view())]
