from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path

from camp.utils.views import PageTemplate

urlpatterns = [
    path('api', include('camp.api.urls', namespace='v1')),

    # Admin-y stuff
    path('admin/', include('admin_honeypot.urls', namespace='admin_honeypot')),
    path('batcave/', admin.site.urls),
]

if settings.DEBUG:
    import debug_toolbar
    urlpatterns += [path('__debug__/', include(debug_toolbar.urls))]
    # urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Catch-all to render templates based on the path
urlpatterns += [re_path('^', PageTemplate.as_view())]
