from camp.apps.entries.models import BaseEntry


def get_all_entry_models(base_class=BaseEntry):
    subclasses = set()

    def recurse(cls):
        for subclass in cls.__subclasses__():
            if hasattr(subclass, '_meta') and not subclass._meta.abstract:
                subclasses.add(subclass)
            recurse(subclass)

    recurse(base_class)
    return subclasses

ENTRY_MODEL_LOOKUP = {
    model._meta.model_name: model
    for model in get_all_entry_models()
}

def get_entry_model_by_name(name):
    return ENTRY_MODEL_LOOKUP.get(name.lower())