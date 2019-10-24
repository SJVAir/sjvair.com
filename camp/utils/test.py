import json


def get_response_data(response):
    '''
        Given a response object, parse the JSON
        and return the data structure.
    '''
    if hasattr(response, 'streaming_content'):
        return json.loads(''.join([b.decode('utf8') for b in response.streaming_content]))
    return json.loads(response.content)
