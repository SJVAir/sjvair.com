from django.urls import include, path

from . import endpoints

app_name = 'alerts'

urlpatterns = [
    path('current/', endpoints.CurrentAlertValues.as_view(), name='current'),
    path('subscribe/', endpoints.Subscribe.as_view(), name='subscribe'),
    path('unsubscribe/', endpoints.Unsubscribe.as_view(), name='unsubscribe'),
]
