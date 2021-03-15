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


class MethaneDataForm(forms.Form):
    id = forms.DecimalField()
    bin1 = forms.DecimalField()
    bin2 = forms.DecimalField()
    bin3 = forms.DecimalField()
    bin4 = forms.DecimalField()

    temp = forms.DecimalField()
    rh = forms.DecimalField()

    CO_we = forms.DecimalField()
    CO_aux = forms.DecimalField()

    Figaro2600 = forms.DecimalField()
    Figaro2602 = forms.DecimalField()

    Plantower1_pm1_mass = forms.DecimalField()
    Plantower1_pm2_5_mass = forms.DecimalField()
    Plantower1_pm10_mass = forms.DecimalField()

    Plantower1_pm0_3_count = forms.DecimalField()
    Plantower1_pm0_5_count = forms.DecimalField()
    Plantower1_pm1_count = forms.DecimalField()
    Plantower1_pm2_5_count = forms.DecimalField()
    Plantower1_pm5_count = forms.DecimalField()
    Plantower1_pm10_count = forms.DecimalField()

    Plantower2_pm1_mass = forms.DecimalField()
    Plantower2_pm2_5_mass = forms.DecimalField()
    Plantower2_pm10_mass = forms.DecimalField()

    Plantower2_pm0_3_count = forms.DecimalField()
    Plantower2_pm0_5_count = forms.DecimalField()
    Plantower2_pm1_count = forms.DecimalField()
    Plantower2_pm2_5_count = forms.DecimalField()
    Plantower2_pm5_count = forms.DecimalField()
    Plantower2_pm10_count = forms.DecimalField()
