from django import forms


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
