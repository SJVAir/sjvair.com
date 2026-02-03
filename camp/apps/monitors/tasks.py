from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone

from django_huey import db_task, db_periodic_task
from huey import crontab

from camp.utils.text import render_markdown
from .models import Entry, Monitor


# @db_periodic_task(crontab(hour='13', minute='0'), priority=100)
# def check_monitor_status():
#     # Update to run daily – monitors that have been offline for 24-48 hours
#     inactive_monitors = {}
#     upper_bound = timezone.now() - timedelta(hours=24)
#     lower_bound = timezone.now() - timedelta(hours=48)

#     for subclass in Monitor.subclasses():
#         SubMonitor = getattr(Monitor, subclass).related.related_model
#         inactive_monitors[SubMonitor.__name__] = list((SubMonitor.objects
#             .filter(latest__timestamp__range=(lower_bound, upper_bound))
#             .select_related('latest')
#         ))

#         print(SubMonitor.__name__, lower_bound, upper_bound, len(inactive_monitors[SubMonitor.__name__]))

#     # Filter out devices with no new inactivity.
#     inactive_monitors = {k: v for k, v in inactive_monitors.items() if len(v)}

#     if any([len(ml) >= 0 for ml in inactive_monitors.values()]):
#         total_inactive = sum([len(ml) for ml in inactive_monitors.values()])
#         message = render_to_string('email/monitor-alerts.md', {
#             'inactive_monitors': inactive_monitors,
#             'total_inactive': total_inactive
#         })

#         print(message)
#         send_mail(
#             subject=f'[Monitor Inactivity] {total_inactive} New Inactive Monitors',
#             message=message,
#             html_message=render_markdown(message),
#             recipient_list=settings.SJVAIR_INACTIVE_ALERT_EMAILS,
#             from_email=None,
#         )


@db_task(queue='secondary')
def recalibrate_entry(entry_id):
    entry = Entry.objects.get(pk=entry_id)
    entry.calibrate_pm25()
    entry.pm25_avg_15 = entry.get_average('pm25', 15)
    entry.pm25_avg_60 = entry.get_average('pm25', 60)
    entry.save()
