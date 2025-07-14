import os.path

from django.utils import timezone


def get_default_calibration(monitor_model, entry_model):
    from camp.apps.calibrations.models import DefaultCalibration
    default = '' # Default to an empty string.

    # First, look it up.
    try:
        default = DefaultCalibration.objects.get(
            monitor_type=monitor_model.monitor_type,
            entry_type=entry_model.entry_type
        ).calibration
    except DefaultCalibration.DoesNotExist:
        pass

    # Nothing configured? Default to the first calibrated processor.
    if not default:
        try:
            default_stage = monitor_model.get_default_stage(entry_model)
            default = monitor_model.ENTRY_CONFIG[entry_model]['processors'][default_stage][0].name
        except (IndexError, KeyError):
            pass

    return default


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
