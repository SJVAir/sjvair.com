from django import forms
from django.contrib.admin.widgets import FilteredSelectMultiple

from camp.apps.entries.fields import EntryTypeField

from .models import Group, DefaultSensor


class MonitorAdminForm(forms.ModelForm):
    groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.all(), 
        required=False,
        widget=FilteredSelectMultiple(
            verbose_name='Groups',
            is_stacked=False
        )
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance and self.instance.pk:
            print(self.instance.groups.all())
            self.fields['groups'].initial = self.instance.groups.all()

    def save(self, commit=True):
        instance = super().save(commit=False)

        if commit:
            instance.save()

        if instance.pk:
            instance.groups.set(self.cleaned_data['groups'])
            self.save_m2m()

        return instance


class DefaultSensorForm(forms.ModelForm):
    class Meta:
        model = DefaultSensor
        fields = '__all__'

    def __init__(self, *args, monitor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.monitor = monitor or getattr(self.instance, 'monitor', None)

        if not self.monitor:
            return

        get_model_map = EntryTypeField.get_model_map()
        valid_models = [
            model for model, config in self.monitor.ENTRY_CONFIG.items()
            if config.get('sensors') is not None
        ]
        valid_model_names = {model._meta.model_name for model in valid_models}

        if not self.instance._state.adding:
            # Editing existing — freeze entry_type field
            current_name = self.instance.entry_type
            self.fields['entry_type'].disabled = True
            self.fields['entry_type'].choices = [
                (current_name, get_model_map[current_name].label)
            ]
        else:
            # Creating — filter to only unused entry_type types
            used_names = DefaultSensor.objects.filter(
                monitor=self.monitor
            ).exclude(pk=self.instance.pk).values_list('entry_type', flat=True)

            available_names = valid_model_names - set(used_names)

            self.fields['entry_type'].choices = sorted([
                (name, get_model_map[name].label)
                for name in available_names
            ], key=lambda x: x[1].lower())

        # Populate sensor field if we know which entry_type it is
        entry_type_name = self.instance.entry_type if not self.instance._state.adding else None
        model_cls = get_model_map.get(entry_type_name)
        sensors = self.monitor.ENTRY_CONFIG.get(model_cls, {}).get('sensors', [])

        if sensors:
            self.fields['sensor'] = forms.ChoiceField(
                choices=[(s, s) for s in sensors],
                required=False,
            )

    def clean(self):
        cleaned = super().clean()
        model_name = cleaned.get('entry_type')
        model_cls = EntryTypeField.get_model_map().get(model_name)

        if model_cls and self.monitor:
            config = self.monitor.ENTRY_CONFIG.get(model_cls)
            if not config or not config.get('sensors'):
                raise forms.ValidationError(
                    f'{model_cls.label} is not a multi-sensor entry type for this monitor.'
                )
        return cleaned

    def clean_sensor(self):
        sensor = self.cleaned_data.get('sensor')
        model_name = self.cleaned_data.get('entry_type')
        model_cls = EntryTypeField.get_model_map().get(model_name)

        if not model_cls or not self.monitor:
            return sensor

        sensors = self.monitor.ENTRY_CONFIG.get(model_cls, {}).get('sensors', [])
        if sensors and sensor not in sensors:
            raise forms.ValidationError(
                f"'{sensor}' is not a valid sensor option for {model_cls.label}."
            )

        return sensor
