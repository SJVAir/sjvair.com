from model_utils.managers import InheritanceManager as BaseInheritanceManager

# For more information on how to use InheritanceManager,
# check out the django-model-utils docs:
# https://django-model-utils.rtfd.io/en/latest/managers.html#inheritancemanager

# This manager ensures that relations always return the concrete model.


class InheritanceManager(BaseInheritanceManager):
    def get_queryset(self):
        return super().get_queryset().select_subclasses()
