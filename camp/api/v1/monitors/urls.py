from django.urls import include, path

from . import endpoints

app_name = 'monitors'

urlpatterns = [
    path('', endpoints.MonitorList.as_view(), name='monitor-list'),
    # path('monitor/<monitor_id>/', endpoints.MonitorDetail.as_view(), name='monitor-detail'),
    # path('monitor/<monitor_id>/data/', endpoints.MonitorDetail.as_view(), name='monitor-data'),
    # path('monitor/<monitor_id>/export/', endpoints.MonitorDetail.as_view(), name='monitor-export'),
]
