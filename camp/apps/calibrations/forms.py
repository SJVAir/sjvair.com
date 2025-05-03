from django import forms

from .models import DefaultCalibration


class DefaultCalibrationForm(forms.ModelForm):
    '''
    Admin form for DefaultCalibration.

    - Disables `monitor_type` and `entry_type` fields on edit to prevent changing identity.
    - Dynamically sets `calibration` choices to match valid options from ENTRY_CONFIG.
    - Allows blank calibration (representing no calibration).
    '''

    class Meta:
        model = DefaultCalibration
        fields = ['monitor_type', 'entry_type', 'calibration']
        widgets = {
            'calibration': forms.Select()
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance.monitor_model and self.instance.entry_model:
            choices = self.get_calibration_choices(self.instance)
            self.fields['calibration'].choices = choices

        if not self.instance._state.adding:
            self.fields['monitor_type'].disabled = True
            self.fields['entry_type'].disabled = True

    @classmethod
    def get_calibration_choices(cls, instance):
        choices = [('', '-- none --')] + [
            (str(proc.name), str(proc.name))
            for proc in instance.allowed_processors
        ]
        print('\n.get_calibration_choices()', choices)
        return choices
