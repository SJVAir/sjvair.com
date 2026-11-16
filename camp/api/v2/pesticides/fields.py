"""
Form fields shared by the pesticide endpoints. They live apart from
endpoints.py so sections.py can use them: endpoints imports places, which
imports sections, so sections can't import endpoints at module scope.
"""
from django import forms

from camp.apps.pesticides.models import Chemical


class CategoryListField(forms.Field):
    """
    Chemical categories, repeated (`category=a&category=b`) or comma-separated, kept as a
    sorted, deduplicated list (so every spelling shares a cache key); blanks are dropped.
    """
    widget = forms.MultipleHiddenInput  # reads every value of the parameter

    def __init__(self, **kwargs):
        kwargs.setdefault('required', False)
        super().__init__(**kwargs)

    def clean(self, value):
        values = {part.strip() for raw in (value or []) for part in str(raw).split(',')} - {''}
        unknown = sorted(values - set(Chemical.Category.values))
        if unknown:
            raise forms.ValidationError(f'Unknown category: {", ".join(unknown)}.', code='invalid')
        return sorted(values) or None


class PlaceChoiceField(forms.ChoiceField):
    """A ChoiceField whose unknown value is `invalid`, like the place endpoint's other fields."""

    def __init__(self, **kwargs):
        kwargs.setdefault('required', False)
        super().__init__(**kwargs)

    def validate(self, value):
        try:
            super().validate(value)
        except forms.ValidationError as err:
            raise forms.ValidationError(err.messages[0], code='invalid')
