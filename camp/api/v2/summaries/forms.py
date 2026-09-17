from django import forms


class BulkMonitorSummaryForm(forms.Form):
    start = forms.DateField(required=True)
    end = forms.DateField(required=True)
    bbox = forms.CharField(required=False)

    def clean_bbox(self):
        value = self.cleaned_data.get('bbox')
        if not value:
            return None

        parts = value.split(',')
        if len(parts) != 4:
            raise forms.ValidationError('bbox must be "west,south,east,north"')

        try:
            return tuple(float(p) for p in parts)
        except ValueError:
            raise forms.ValidationError('bbox values must be numbers')

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('start')
        end = cleaned_data.get('end')

        if start and end and start > end:
            raise forms.ValidationError('start must be on or before end.')

        return cleaned_data
