from django import forms

from camp.apps.sensors.models import SensorData

class PayloadForm(forms.ModelForm):
    class Meta:
        model = SensorData
        fields = ['payload']
