from django import forms
from django.contrib.admin.widgets import FilteredSelectMultiple
from django.contrib.contenttypes.models import ContentType

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

        # EntryModels eligible for configuration
        entry_models = [
            EntryModel for (EntryModel, config)
            in self.monitor.ENTRY_CONFIG.items()
            if config.get('sensors') is not None
        ]
        valid_cts = list(ContentType.objects.get_for_models(*entry_models).values())
        self.fields['content_type'].queryset = ContentType.objects.filter(pk__in=[ct.pk for ct in valid_cts])

        if not self.instance._state.adding:
            self.fields['content_type'].disabled = True
            self.fields['content_type'].queryset = self.fields['content_type'].queryset.filter(pk=self.instance.content_type_id)
        else:
            used_ct_ids = (DefaultSensor.objects
                .filter(monitor=self.monitor)
                .exclude(pk=self.instance.pk)
                .values_list('content_type_id', flat=True)
            )
            self.fields['content_type'].queryset = self.fields['content_type'].queryset.exclude(pk__in=used_ct_ids)

        self.fields['content_type'].choices = sorted([
            (ct.pk, ct.model_class().label)
            for ct in self.fields['content_type'].queryset
        ], key=lambda x: x[1].lower())

        # If the model has sensors configured, set choices on sensor field
        model_cls = self.instance.content_type.model_class() if self.instance.content_type_id else None
        sensors = self.monitor.ENTRY_CONFIG.get(model_cls, {}).get('sensors', [])
        if sensors:
            self.fields['sensor'] = forms.ChoiceField(
                choices=[(s, s) for s in sensors],
                required=False,
            )

    def clean(self):
        cleaned = super().clean()
        ct = cleaned.get('content_type')

        if ct and self.monitor:
            model_cls = ct.model_class()
            config = self.monitor.ENTRY_CONFIG.get(model_cls)
            if not config or not config.get('sensors'):
                raise forms.ValidationError(f"{model_cls.label} is not a multi-sensor entry type for this monitor.")

        return cleaned

    def clean_sensor(self):
        sensor = self.cleaned_data.get('sensor')
        ct = self.cleaned_data.get('content_type')

        if not ct or not self.monitor:
            return sensor  # Nothing to validate yet

        model_cls = ct.model_class()
        sensors = self.monitor.ENTRY_CONFIG.get(model_cls, {}).get('sensors', [])

        if sensors and sensor not in sensors:
            raise forms.ValidationError(f"'{sensor}' is not a valid sensor option for {model_cls.label}.")

        return sensor