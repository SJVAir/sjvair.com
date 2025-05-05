from functools import lru_cache

@lru_cache
def get_all_entry_models(base_class=None):
    from camp.apps.entries.models import BaseEntry
    base_class = base_class or BaseEntry
    subclasses = set()

    def recurse(cls):
        for subclass in cls.__subclasses__():
            if hasattr(subclass, '_meta') and not subclass._meta.abstract:
                subclasses.add(subclass)
            recurse(subclass)

    recurse(base_class)
    return subclasses


@lru_cache()
def get_entry_model_by_name(name):
    name = name.lower()
    for model in get_all_entry_models():
        if model._meta.model_name == name:
            return model
