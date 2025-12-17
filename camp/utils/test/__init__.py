import json

from django.test.utils import override_settings


def debug(fn):
    return override_settings(DEBUG=True)(fn)


def get_response_data(response):
    '''
        Given a response object, parse the JSON
        and return the data structure.
    '''
    if hasattr(response, 'streaming_content'):
        content = b''.join(list(response.streaming_content))
    else:
        content = response.content

    if isinstance(content, bytes):
        content = content.decode('utf-8')

    if response.get('Content-Type', '').startswith('application/json'):
        return json.loads(content)
    return content


def is_close(actual, expected, tol=1e-6):
    """
    Returns True if two floating point numbers are close within a tolerance.

    Args:
        actual (float): The value you got.
        expected (float): The value you expected.
        tol (float): Acceptable difference (default: 1e-6).

    Raises:
        AssertionError: if values are not within tolerance.
    """
    return abs(actual - expected) < tol
