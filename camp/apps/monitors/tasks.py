from django.test import RequestFactory
from django.urls import reverse

from huey import crontab
from huey.contrib.djhuey import db_task, db_periodic_task

from camp.api.v1.monitors.endpoints import MonitorList
from camp.utils.test import get_response_data
from .models import Entry, Monitor


@db_periodic_task(crontab(minute='*'), priority=100)
def refresh_monitor_list_cache():
    # We'll use Django's testing framework to directly call the
    # monitor-list endpoint with cache-busting. This will force
    # a refresh of the cache, and prevent the database from being
    # hit too often.

    monitor_list = MonitorList.as_view()
    factory = RequestFactory()

    url = reverse('api:v1:monitors:monitor-list')
    url = f'{url}?_cc=1'

    request = factory.get(url)
    response = monitor_list(request)

    content = get_response_data(response)
    assert response.status_code == 200

