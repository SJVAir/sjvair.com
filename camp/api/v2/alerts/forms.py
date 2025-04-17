from django import forms

from camp.apps.alerts.models import Subscription


class SubscribeForm(forms.ModelForm):
    class Meta:
        model = Subscription
        fields = ['level']


    # def __init__(self, *args, **kwargs):
    #     self.user = kwargs.pop('user')
    #     self.monitor = kwargs.pop('monitor')
    #     super().__init__(self, *args, **kwargs)
