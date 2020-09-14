from django import forms

from camp.apps.monitors.models import Entry


class EntryForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['timestamp'].required = False

        for key in Entry.ENVIRONMENT:
            self.fields[key].required = False

    class Meta:
        model = Entry
        fields = ['timestamp', 'sensor'] + Entry.ENVIRONMENT
