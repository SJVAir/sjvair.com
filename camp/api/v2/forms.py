from django import forms
from django.conf import settings
from django.utils import timezone


class PacificDateTimeField(forms.DateTimeField):
    """A DateTimeField that reads a zone-less value as Pacific wall time,
    whatever zone is active. Zone-aware values ("Z" or an offset) keep
    their own zone."""

    def to_python(self, value):
        with timezone.override(settings.DEFAULT_TIMEZONE):
            return super().to_python(value)


class BboxField(forms.CharField):
    """A `west,south,east,north` bounding box, cleaned to a 4-tuple of floats
    (or None when blank)."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('required', False)
        super().__init__(*args, **kwargs)

    def clean(self, value):
        value = super().clean(value)
        if not value:
            return None

        parts = value.split(',')
        if len(parts) != 4:
            raise forms.ValidationError('bbox must be "west,south,east,north"')

        try:
            return tuple(float(p) for p in parts)
        except ValueError:
            raise forms.ValidationError('bbox values must be numbers')
