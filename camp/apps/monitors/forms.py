from django import forms
from django.contrib.admin.widgets import AdminDateWidget, FilteredSelectMultiple

from .models import Group


class EntryExportForm(forms.Form):
    start_date = forms.DateField(label='Start Date', required=True, widget=AdminDateWidget)
    end_date = forms.DateField(label='End Date', required=True, widget=AdminDateWidget)


class MonitorAdminForm(forms.ModelForm):
    groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.all(),
        required=False,
        widget=FilteredSelectMultiple(
            verbose_name='Groups',
            is_stacked=False
        )
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance and self.instance.pk:
            self.fields['groups'].initial = self.instance.groups.all()

    def save(self, commit=True):
        instance = super().save(commit=False)

        if commit:
            instance.save()

        if instance.pk:
            instance.groups.set(self.cleaned_data['groups'])
            self.save_m2m()

        return instance
