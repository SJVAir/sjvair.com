from huey import crontab
from huey.contrib.djhuey import db_periodic_task

from .models import Calibrator


@db_periodic_task(crontab(hour='8', minute='0'), priority=50)
def calibrate_monitors():
    for calibrator in Calibrator.objects.filter(is_enabled=True):
        print(calibrator.reference.name, '/', calibrator.colocated.name)
        calibrator.calibrate()
