from django import forms

from . import api
from .models import PurpleAir


class PurpleAirAddForm(forms.ModelForm):
    class Meta:
        model = PurpleAir
        fields = ['name', 'purple_id', 'thingspeak_key']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].required = False
        self.fields['purple_id'].required = False
        self.fields['thingspeak_key'].required = False

    def clean(self):
        name = self.cleaned_data['name']
        purple_id = self.cleaned_data['purple_id']
        thingspeak_key = self.cleaned_data['thingspeak_key']

        if not name and not purple_id:
            raise forms.ValidationError('You must supply a name or PurpleAir ID', 'missing_data')

        if purple_id:
            self.devices = api.get_devices(purple_id, thingspeak_key)
            if self.devices is None:
                self.add_error('purple_id', 'Invalid PurpleAir ID or Thingspeak key')
                return

        elif name:
            self.devices = api.lookup_device(name)
            if self.devices is None:
                self.add_error('name', 'Invalid PurpleAir name.')
                return

    def save(self, *args, **kwargs):
        commit = kwargs.pop('commit', True)
        instance = super().save(commit=False, *args, **kwargs)

        # Accessing the devices property will set
        # the rest of the attrs.
        instance.purple_id = self.devices[0]['ID']
        instance.update_device_data(self.devices)

        if commit:
            instance.save()

        return instance
