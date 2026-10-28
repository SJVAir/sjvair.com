from resticus.http import JSONResponse


def refuse(code, status, message, data=None):
    """A refusal in the wire shape: resticus's error body plus an optional `data` payload."""
    payload = {'errors': {'detail': [{'message': message, 'code': code}]}}
    if data is not None:
        payload['data'] = data
    response = JSONResponse(payload, status=status)
    response['Cache-Control'] = 'no-store'
    return response
