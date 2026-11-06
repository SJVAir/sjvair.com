from django.core.exceptions import ValidationError
from django_smalluuid.models import SmallUUIDField

_field = SmallUUIDField()


def is_small_uuid(value) -> bool:
    '''Whether `value` parses as a SmallUUIDField id, by the field's own rule.'''
    if not value:
        return False
    try:
        _field.to_python(value)
    except (ValidationError, ValueError, TypeError):
        return False
    return True
