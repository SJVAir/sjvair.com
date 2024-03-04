from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path 

from camp.utils import views

admin.site.site_title = "SJVAir Admin"
admin.site.site_header = "SJVAir Admin"

urlpatterns = [
    path('api/', include('camp.api.urls', namespace='api')),
    path('account/', include(('camp.apps.accounts.urls', 'account'), namespace='account')),
    path('contact/', include(('camp.apps.contact.urls', 'contact'), namespace='contact')),
    path('app/', views.GetTheApp.as_view(), name='app'),

    # @sjvair/monitor-map specific routes
    path('monitor/<monitor_id>/', views.PageTemplate.as_view(template_name='pages/index.html')),
    path('widget/', views.RenderStatic.as_view(static_file='widget/index.html')),

    # Admin-y stuff
    path('admin/', include('admin_honeypot.urls', namespace='admin_honeypot')),
    path('batcave/stats.json', views.AdminStats.as_view(), name='admin-stats'),
    path('batcave/flush-queue/<str:key>/', views.FlushQueue.as_view(), name='flush-queue'),
    path('batcave/', admin.site.urls),
]

if settings.DEBUG:
    import debug_toolbar
    urlpatterns += [path('__debug__/', include(debug_toolbar.urls))]
    # urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Catch-all to render templates based on the path
urlpatterns += [re_path('^', views.PageTemplate.as_view())]
