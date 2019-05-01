from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible

import jsonschema


@deconstructible
class JSONSchemaValidator:
    def __init__(self, schema):
        self.schema = schema

    def __call__(self, value):
        try:
            jsonschema.validate(schema=self.schema, instance=value)
        except jsonschema.ValidationError as err:
            raise ValidationError(err.message)
