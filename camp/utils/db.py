import psycopg2.errorcodes


def is_unique_violation(err):
    '''True if a Django IntegrityError came from a unique constraint.'''
    return getattr(err.__cause__, 'pgcode', None) == psycopg2.errorcodes.UNIQUE_VIOLATION
