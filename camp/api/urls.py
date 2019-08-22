from django.urls import include, path

app_name = 'api'

urlpatterns = [
    path('1.0/', include('camp.api.v1.urls', namespace='v1')),
]
