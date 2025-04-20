from django import forms

from .models import DefaultCalibration


class DefaultCalibrationForm(forms.ModelForm):
    class Meta:
        model = DefaultCalibration
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not self.instance._state.adding:
            self.fields['monitor_type'].disabled = True
            self.fields['entry_type'].disabled = True

        monitor_model = self.instance.monitor_model
        entry_model = self.instance.entry_model

        if monitor_model and entry_model:
            config = monitor_model.ENTRY_CONFIG.get(entry_model)
            if config:
                choices = [('', '-- none --')] + [
                    (c.name, c.name)
                    for c in config.get('calibrations', [])
                ]
                self.fields['calibration'] = forms.ChoiceField(
                    choices=choices,
                    required=False,
                    label='Calibration',
                    initial=self.instance.calibration,
                )