from django.db import models
from django.utils.translation import gettext_lazy as _


class Stage(models.TextChoices):
    RAW = 'raw', _('Raw')
    CORRECTED = 'corrected', _('Corrected')
    CLEANED = 'cleaned', _('Cleaned')
    CALIBRATED = 'calibrated', _('Calibrated')

STAGE_DESCRIPTIONS = {
    Stage.RAW: 'The reading exactly as the monitor or its data provider reported it, before any adjustment.',
    Stage.CORRECTED: "Raw readings from a monitor's two sensors checked against each other and combined into one value.",
    Stage.CLEANED: 'Readings with obvious errors removed or smoothed, such as impossible values and short spikes.',
    Stage.CALIBRATED: 'Readings adjusted to better match reference-grade instruments, or aggregated or computed by the data provider.',
}

STAGE_RULES = {
    Stage.RAW: {
        'single': True,
        'requires_processor': False,
    },
    Stage.CORRECTED: {
        'single': True,
        'requires_processor': True,
    },
    Stage.CLEANED: {
        'single': True,
        'requires_processor': True,
    },
    Stage.CALIBRATED: {
        'single': False,
        'requires_processor': True,
    },
}

def is_singleton(stage):
    return STAGE_RULES.get(stage, {}).get('single', False)

def requires_processor(stage):
    return STAGE_RULES.get(stage, {}).get('requires_processor', False)
