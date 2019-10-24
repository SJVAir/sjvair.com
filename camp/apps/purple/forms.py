from django import forms

from . import api
from .models import PurpleAir


class PurpleAirAddForm(forms.ModelForm):
    class Meta:
        model = PurpleAir
        fields = ['label', 'purple_id']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['label'].required = False
        self.fields['purple_id'].required = False


    def clean(self):
        label = self.cleaned_data['label']
        purple_id = self.cleaned_data['purple_id']

        if not label and not purple_id:
            raise forms.ValidationError('You must supply a label or PurpleAir ID', 'missing_data')

        if purple_id:
            self.devices = api.get_devices(purple_id)
            if self.devices is None:
                self.add_error('purple_id', 'Invalid PurpleAir ID')

            if self.devices and label and self.devices[0]['Label'] != label:
                message = 'Label and Purple ID do not match'
                raise forms.ValidationError(message, code='data_mismatch')

        elif label:
            device = api.lookup_device(label)
            if device is None:
                self.add_error('label', 'Invalid PurpleAir label')
                return

            self.devices = api.get_devices(device['ID'])

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
