import functools

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path

from redis.asyncio import Redis as RedisClient

from health_check.checks import Cache, Database, Storage
from health_check.contrib.psutil import Memory
from health_check.contrib.redis import Redis
from health_check.views import HealthCheckView

from camp.apps.monitors.health_checks import (
    AirGradientHealthCheck,
    AirNowHealthCheck,
    AQviewHealthCheck,
    CCACBAMHealthCheck,
    PurpleAirHealthCheck,
    VOZBoxHealthCheck,
)
from camp.utils import views

admin.site.site_title = "SJVAir Admin"
admin.site.site_header = "SJVAir Admin"

urlpatterns = [
    path('api/', include('camp.api.urls', namespace='api')),
    path('account/', include(('camp.apps.accounts.urls', 'account'), namespace='account')),
    path('contact/', include(('camp.apps.contact.urls', 'contact'), namespace='contact')),
    path('support/', include(('camp.apps.helpdesk.urls', 'helpdesk'), namespace='helpdesk')),
    path('app/', views.GetTheApp.as_view(), name='app'),

    # @sjvair/monitor-map specific routes
    path('monitor/<monitor_id>/', views.PageTemplate.as_view(template_name='pages/index.html')),
    path('widget/', views.RenderStatic.as_view(static_file='widget/index.html')),

    path('prose/', include('prose.urls')),

    # Admin-y stuff
    path('admin/', include('admin_honeypot.urls', namespace='admin_honeypot')),
    path('batcave/stats.json', views.AdminStats.as_view(), name='admin-stats'),
    path('batcave/flush-queue/<str:key>/', views.FlushQueue.as_view(), name='flush-queue'),

    path('batcave/', admin.site.urls),
]

urlpatterns += [path('system-status/', include(([
    path('', HealthCheckView.as_view(
        checks=[
            Database,
            Cache,
            Storage,
            Memory,
            functools.partial(Redis, client_factory=lambda: RedisClient.from_url(f'{settings.REDIS_URL}/0')),
        ],
        extra_context={'title': 'Infrastructure'},
    ), name='index'),

    path('data-feeds/', HealthCheckView.as_view(
        checks=[
            AirGradientHealthCheck,
            AirNowHealthCheck,
            AQviewHealthCheck,
            CCACBAMHealthCheck,
            PurpleAirHealthCheck,
            VOZBoxHealthCheck,
        ],
        extra_context={'title': 'Data Feeds'},
    ), name='data-feeds'),
], 'system-status')))]

if settings.DEBUG:
    import debug_toolbar
    urlpatterns += [path('__debug__/', include(debug_toolbar.urls))]
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Catch-all to render templates based on the path
urlpatterns += [re_path('^', views.PageTemplate.as_view())]
