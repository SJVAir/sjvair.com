from django import forms
from django.db import models
from django.utils.module_loading import import_string


class EntryTypeField(models.CharField):
    description = 'Stores an entry type as a model name and resolves it to a class.'

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('max_length', 50)
        super().__init__(*args, **kwargs)

    def formfield(self, **kwargs):
        include_blank = kwargs.pop('include_blank', True)
        choices = self.get_choices(include_blank=include_blank)

        return forms.ChoiceField(
            choices=choices,
            required=not self.blank,
            label=self.verbose_name,
            help_text=self.help_text,
            initial=self.default if self.has_default() else None,
        )

    @staticmethod
    def get_model_map():
        get_models = import_string('camp.apps.entries.utils.get_all_entry_models')
        return {model.entry_type: model for model in get_models()}

    @classmethod
    def get_choices(cls, include_blank=True):
        choices = sorted([
            (entry_type, model.label)
            for entry_type, model in cls.get_model_map().items()
        ], key=lambda x: x[1])


        if include_blank:
            return [('', '---------')] + choices
        return choices
