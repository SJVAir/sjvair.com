from django import forms
from django.db import models

from functools import lru_cache


class MonitorTypeField(models.CharField):
    description = 'Stores a monitor type as a model name and resolves it to a class.'

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
    @lru_cache
    def get_model_map():
        from .models import Monitor
        return {
            subclass: getattr(Monitor, subclass).related.related_model
            for subclass in Monitor.subclasses()
        }

    @classmethod
    def get_choices(cls, include_blank=True):
        choices = [
            (name, model._meta.verbose_name)
            for name, model in cls.get_model_map().items()
        ]
        if include_blank:
            return [('', '---------')] + choices
        return choices