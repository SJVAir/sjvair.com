from django import forms

from camp.apps.alerts.models import Subscription


class SubscribeForm(forms.ModelForm):
    class Meta:
        model = Subscription
        fields = ['level']
