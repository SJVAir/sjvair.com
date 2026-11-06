from typing import Optional

from django.core.exceptions import ValidationError
from django_smalluuid.models import SmallUUIDField

_field = SmallUUIDField()


def parse_small_uuid(value) -> Optional[object]:
    '''The SmallUUID `value` names, by SmallUUIDField's own parsing rule, or None.

    The rule is lenient (base64 decoding skips whitespace, and the hex form is accepted
    too), so use the result's str(), the canonical 22-character form, as a key, never
    the raw value.'''
    if not value:
        return None
    try:
        return _field.to_python(value)
    except (ValidationError, ValueError, TypeError):
        return None


def is_small_uuid(value) -> bool:
    '''Whether `value` parses as a SmallUUIDField id.'''
    return parse_small_uuid(value) is not None
