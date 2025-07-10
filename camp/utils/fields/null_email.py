from django.db import models


class NullEmailField(models.EmailField):
    """
    Subclass of the EmailField that allows empty strings to be stored
    as NULL for uniqueness purposes.
    """

    description = "CharField that stores NULL but returns ''."

    def from_db_value(self, value, expression, connection):
        """
        Gets value right out of the db and changes it if its ``None``.
        """
        if value is None:
            return ''
        return value


    def to_python(self, value):
        """
        Gets value right out of the db or an instance, and changes it if its ``None``.
        """
        if value is None:
            return ''
        return value

    def get_prep_value(self, value):
        """
        Catches value right before sending to db.
        """
        if value == '':
            return None
        return value
