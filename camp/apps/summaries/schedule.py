from django.utils import timezone

from camp.utils.datetime import localtime

# Huey crontabs run in UTC. A Pacific hour lands on one of two UTC hours
# depending on DST, so each rollup is scheduled on both and guarded with
# is_pacific_hour(). Keys are the Pacific hour, values the UTC hours that
# contain it in PDT and PST.
ROLLUP_UTC_HOURS = {1: '8,9', 2: '9,10'}


def is_pacific_hour(hour, now=None):
    """
    True when `now` falls in the given Pacific hour. The repeated hour on
    the fall-back day counts once (fold 0 only).
    """
    local = localtime(now or timezone.now())
    return local.hour == hour and local.fold == 0
