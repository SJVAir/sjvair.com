import os.path

from django.utils import timezone


def get_default_calibration(monitor_model, entry_model):
    from camp.apps.calibrations.models import DefaultCalibration

    try:
        return DefaultCalibration.objects.get(
            monitor_type=monitor_model.monitor_type,
            entry_type=entry_model.entry_type
        ).calibration
    except DefaultCalibration.DoesNotExist:
        return ''  # fallback to raw


def calibration_model_upload_to(instance, filename):
    """
    Determines upload path for calibration model files.

    Structure:
      calibrations/<entry_type>/<model_name>/<year>/<month>/<filename>
    """
    now = timezone.now()

    return os.path.join(
        'calibrations',
        instance.entry_type or 'unknown',
        instance.model_name or 'model',
        f'{now.year}',
        f'{now.month:02}',
        filename
    )
