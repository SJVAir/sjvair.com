from camp.apps.calibrations.models import DefaultCalibration


def get_default_calibration(monitor_model, entry_model):
    monitor_type = monitor_model._meta.model_name
    entry_type = entry_model._meta.model_name

    try:
        return DefaultCalibration.objects.get(
            monitor_type=monitor_type,
            entry_type=entry_type
        ).calibration
    except DefaultCalibration.DoesNotExist:
        return ''  # fallback to raw