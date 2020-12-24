from django.core.exceptions import ValidationError

from py_expression_eval import Parser as ExpressionParser


def validate_formula(value):
    from camp.apps.monitors.models import Entry

    if value:
        parser = ExpressionParser()
        expression = parser.parse(value)
        context = {field: 1 for field in Entry.ENVIRONMENT}
        try:
            expression.evaluate(context)
        except Exception as err:
            raise ValidationError(err.args[0])
