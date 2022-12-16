from datetime import timedelta

from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from huey import crontab
from huey.contrib.djhuey import db_task, db_periodic_task

from camp.api.v1.monitors.endpoints import MonitorList
from camp.utils.test import get_response_data
from camp.utils.text import render_markdown
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


# @db_periodic_task(crontab(minute='15'), priority=100)
@db_task()
def check_monitor_status():
    inactive_monitors = {}
    this_hour = timezone.now().replace(minute=0, second=0, microsecond=0)

    for subclass in Monitor.subclasses():
        SubMonitor = getattr(Monitor, subclass).related.related_model
        upper_bound = this_hour - timedelta(hours=1)
        lower_bound = upper_bound - timedelta(seconds=SubMonitor.LAST_ACTIVE_LIMIT)
        inactive_monitors[SubMonitor.__name__] = list((SubMonitor.objects
            .filter(latest__timestamp__range=(lower_bound, upper_bound))
            .select_related('latest')
        ))

        print(SubMonitor.__name__, lower_bound, upper_bound, len(inactive_monitors[SubMonitor.__name__]))

    # Filter out devices with no new inactivity.
    inactive_monitors = {k: v for k, v in inactive_monitors.items() if len(v)}

    if any([len(ml) >= 0 for ml in inactive_monitors.values()]):
        total_inactive = sum([len(ml) for ml in inactive_monitors.values()])
        message_md = render_to_string('email/monitor-alerts.md', {
            'inactive_monitors': inactive_monitors,
            'total_inactive': total_inactive
        })
        message_html = render_markdown(message_md)

        send_mail(
            subject=f'[Monitor Inactivity] {total_inactive} New Inactive Monitors',
            message=message_md,
            html_message=message_html,
            recipient_list=['derek@rootaccess.org'],
            from_email=None,
        )



