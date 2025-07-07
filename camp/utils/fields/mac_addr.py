from django.db import models
from django.core.exceptions import ValidationError
from netaddr import EUI, AddrFormatError, mac_unix_expanded


def validate_macaddr(value):
    try:
        EUI(value, dialect=mac_unix_expanded)
    except AddrFormatError:
        raise ValidationError(f'Invalid MAC address: {value}')


def normalize_macaddr(value):
    try:
        return str(EUI(value, dialect=mac_unix_expanded)).lower()
    except AddrFormatError:
        return value  # validation should catch this elsewhere


class MACAddressField(models.Field):
    description = 'MAC address stored using PostgreSQL macaddr type'
    default_validators = [validate_macaddr]

    def db_type(self, connection):
        return 'macaddr'

    def from_db_value(self, value, expression, connection):
        return value

    def to_python(self, value):
        return normalize_macaddr(value) if value else value

    def get_prep_value(self, value):
        return normalize_macaddr(value) if value else value

    def formfield(self, **kwargs):
        defaults = {'max_length': 17}
        defaults.update(kwargs)
        return super().formfield(**defaults)
