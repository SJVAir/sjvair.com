from django.db import models
from django.core.exceptions import ValidationError
from netaddr import EUI, AddrFormatError, mac_unix


def validate_macaddr(value):
    try:
        EUI(value, dialect=mac_unix)
    except AddrFormatError:
        raise ValidationError(f'Invalid MAC address: {value}')


def normalize_macaddr(value):
    try:
        return str(EUI(value, dialect=mac_unix)).lower()
    except AddrFormatError:
        return value  # validation should catch this elsewhere


class MACAddressField(models.Field):
    description = 'MAC address stored using PostgreSQL macaddr type'

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('max_length', 17)  # Just for form rendering
        validators = kwargs.pop('validators', [])
        validators.append(validate_macaddr)
        kwargs['validators'] = validators
        super().__init__(*args, **kwargs)

    def db_type(self, connection):
        return 'macaddr'

    def from_db_value(self, value, expression, connection):
        return value

    def to_python(self, value):
        return normalize_macaddr(value) if value else value

    def get_prep_value(self, value):
        return normalize_macaddr(value) if value else value
