"""
SJVAir's outdoor activity guidelines for schools, by PM2.5 level.

Served by monitors/meta/ (the pm25 entry's `school_guidelines`) and rendered on
/guidelines/schools/. Activity keys are permanent. The text is verbatim from the
original schools page; don't reword it.
"""
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from django.utils.translation import gettext_lazy as _

SCHOOL_GUIDELINES_LABEL = _('Outdoor Activity Guidelines for Schools')
SCHOOL_GUIDELINES_PATH = '/guidelines/schools/'

_NO_RESTRICTIONS = _('No restrictions.')
_MANAGE = _('Ensure that sensitive individuals are medically managing their condition.')
_REMAIN_INDOORS = _('Sensitive individuals should remain indoors.')
_NO_OUTDOOR = _('No outdoor activity.')
_MOVE_INDOORS = _('All activities should be moved indoors.')
_NO_ACTIVITIES = _('No outdoor or indoor activities.')
_SENSITIVE_INDOORS = _('Sensitive individuals should exercise indoors or avoid vigorous outdoor activities.')
_CIF = _('Increase rest breaks and substitutions per CIF guidelines for extreme heat.')


@dataclass(frozen=True)
class Activity:
    key: str
    label: str
    duration: Optional[str]
    levels: Dict[str, Tuple[str, ...]]


SCHOOL_ACTIVITIES = (
    Activity(
        key='recess',
        label=_('Recess'),
        duration=_('15 minutes'),
        levels={
            'good': (_NO_RESTRICTIONS,),
            'moderate': (_MANAGE,),
            'unhealthy_sensitive': (_SENSITIVE_INDOORS,),
            'unhealthy': (
                _('Exercise indoors or avoid vigorous outdoor activities.'),
                _REMAIN_INDOORS,
            ),
            'very_unhealthy': (_NO_OUTDOOR, _MOVE_INDOORS),
            'hazardous': (_NO_ACTIVITIES,),
        },
    ),
    Activity(
        key='pe',
        label=_('P.E.'),
        duration=_('1 hour'),
        levels={
            'good': (_NO_RESTRICTIONS,),
            'moderate': (_MANAGE,),
            'unhealthy_sensitive': (_SENSITIVE_INDOORS,),
            'unhealthy': (
                _('Exercise indoors or limit vigorous outdoor activities to a maximum of 15 minutes.'),
                _REMAIN_INDOORS,
            ),
            'very_unhealthy': (_NO_OUTDOOR, _MOVE_INDOORS),
            'hazardous': (_NO_ACTIVITIES,),
        },
    ),
    Activity(
        key='athletics',
        label=_('Athletic Practice & Training'),
        duration=_('2-4 hours'),
        levels={
            'good': (_NO_RESTRICTIONS,),
            'moderate': (_MANAGE,),
            'unhealthy_sensitive': (
                _('Reduce vigorous exercise to 30 min per hour of practice time with increased breaks and substitutions.'),
                _MANAGE,
            ),
            'unhealthy': (
                _('Exercise indoors or reduce vigorous exercise to 30 minutes of practice time with increased rest breaks and substitutions.'),
                _REMAIN_INDOORS,
            ),
            'very_unhealthy': (_NO_OUTDOOR, _MOVE_INDOORS),
            'hazardous': (_NO_ACTIVITIES,),
        },
    ),
    Activity(
        key='events',
        label=_('Scheduled Sporting Events'),
        duration=None,
        levels={
            'good': (_NO_RESTRICTIONS,),
            'moderate': (_MANAGE,),
            'unhealthy_sensitive': (_CIF, _MANAGE),
            'unhealthy': (_CIF, _MANAGE),
            'very_unhealthy': (_NO_OUTDOOR, _MOVE_INDOORS),
            'hazardous': (_NO_ACTIVITIES,),
        },
    ),
)


def school_guidelines_json(request) -> dict:
    """The `school_guidelines` block for monitors/meta/, every string a plain str."""
    return {
        'label': str(SCHOOL_GUIDELINES_LABEL),
        'resolution': 'hour',
        'source': {
            'name': 'SJVAir',
            'url': request.build_absolute_uri(SCHOOL_GUIDELINES_PATH),
        },
        'activities': [
            {
                'key': activity.key,
                'label': str(activity.label),
                'duration': str(activity.duration) if activity.duration is not None else None,
                'levels': {
                    key: [str(sentence) for sentence in sentences]
                    for key, sentences in activity.levels.items()
                },
            }
            for activity in SCHOOL_ACTIVITIES
        ],
    }
