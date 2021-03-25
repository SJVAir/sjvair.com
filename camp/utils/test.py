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

    if response.get('Content-Type') == 'application/json':
        return json.loads(content)
    return content
