from django_huey import db_task, db_periodic_task
from huey import crontab

from camp.apps.calibrations import trainers
from .models import Calibrator, CalibrationPair


@db_task(priority=50)
def train_pair(pair_id, trainer_name, end_time=None):
    pair = CalibrationPair.objects.get(pk=pair_id)
    calibration = pair.train(trainer_name, end_time)
    return calibration.pk if calibration else None


@db_task(priority=50)
def train_trainer(trainer_name):
    trainer = trainers[trainer_name]

    pairs = CalibrationPair.objects.filter(
        entry_type=trainer.entry_model.entry_type,
        is_enabled=True,
    )

    for pair in pairs:
        train_pair(pair.pk, trainer.name)


@db_task(priority=50)
def train_entry_type(entry_type):
    pairs = CalibrationPair.objects.filter(
        entry_type=entry_type,
        is_enabled=True,
    )

    for pair in pairs:
        for trainer in trainers.get_for_entry_type(entry_type):
            train_pair(pair.pk, trainer.name)


@db_periodic_task(crontab(hour='8', minute='0'), priority=50)
def train_pairs():
    pairs = CalibrationPair.objects.filter(is_enabled=True)
    for pair in pairs:
        for trainer in pair.get_trainers():
            train_pair(pair.pk, trainer.name)


# Legacy
@db_periodic_task(crontab(hour='8', minute='0'), priority=50)
def calibrate_monitors():
    for calibrator in Calibrator.objects.filter(is_enabled=True):
        calibrator.calibrate()
