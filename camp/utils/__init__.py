from decimal import Decimal
from typing import Union


Number = Union[int, float, Decimal]

def clamp(
    value: Number,
    min_value: Number = Decimal('-Infinity'),
    max_value: Number = Decimal('Infinity')
) -> Number:
    """
    Clamps a numeric value to the given range.

    Args:
        value (int | float | Decimal): The input value to clamp.
        min_value (int | float | Decimal, optional): The minimum allowable value.
        max_value (int | float | Decimal, optional): The maximum allowable value.

    Returns:
        int | float | Decimal: The clamped result.
    """
    return max(min_value, min(value, max_value))


class classproperty:
    def __init__(self, func):
        self.func = func

    def __get__(self, instance, owner):
        return self.func(owner)