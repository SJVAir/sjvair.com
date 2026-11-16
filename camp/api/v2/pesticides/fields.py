"""
Form fields shared by the pesticide endpoints. They live apart from
endpoints.py so sections.py can use them: endpoints imports places, which
imports sections, so sections can't import endpoints at module scope.
"""
from django import forms

from camp.apps.pesticides.models import Chemical, PesticideUse


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


class SqidChoiceField(forms.CharField):
    """
    One of `model`'s rows by its sqid (the `id` its list endpoint returns), cleaned to the
    instance. Not a CDPR code: sqids can be all digits, so a code can't be told from an id.
    A value that isn't one of our ids is `invalid`; a well-formed id with no row (deleted
    or merged) is `not_found`, so a client can show a saved filter as retired.
    """

    MAX_PK = 2**63 - 1  # BigAutoField
    # Decoding is quadratic in length, and a real id is well under this; refuse longer ones
    # before decoding, so a long value can't cost CPU on every uncached error answer.
    MAX_LENGTH = 32

    def __init__(self, model, **kwargs):
        self.model = model
        kwargs.setdefault('required', False)
        super().__init__(**kwargs)

    def clean(self, value):
        value = super().clean(value)
        if not value:
            return None
        if len(value) > self.MAX_LENGTH:
            raise forms.ValidationError(
                f'Not a {self.model._meta.model_name} id.', code='invalid')
        codec = self.model._meta.get_field('sqid').sqids_instance
        decoded = codec.decode(value)
        # sqids decodes some other spellings to the same number; only the canonical one is an id.
        # Past the pk column's range it can't be a row, and the lookup itself would fail.
        if len(decoded) != 1 or decoded[0] > self.MAX_PK or codec.encode(decoded) != value:
            raise forms.ValidationError(
                f'Not a {self.model._meta.model_name} id.', code='invalid')
        try:
            return self.model.objects.get(pk=decoded[0])
        except self.model.DoesNotExist:
            raise forms.ValidationError(
                f'No {self.model._meta.model_name} has this id.', code='not_found')


# The blank (not reported) application method, as the explorer's forms name it.
NO_METHOD = 'none'

# `aerial_ground`'s values: the use records' method codes, plus `none` for not reported.
AERIAL_GROUND_CHOICES = [*PesticideUse.AerialGround.choices, (NO_METHOD, 'Not reported')]
