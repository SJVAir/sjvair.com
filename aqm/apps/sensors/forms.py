from django import forms

from .models import SensorData

class PayloadForm(forms.ModelForm):
    class Meta:
        model = SensorData
        fields = ['payload']
