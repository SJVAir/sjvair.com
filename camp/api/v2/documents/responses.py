from resticus.http import JSONResponse

from camp.apps.documents.models import PurgedDocument


def refuse(code, status, message, data=None):
    """A refusal in the wire shape: resticus's error body plus an optional `data` payload."""
    payload = {'errors': {'detail': [{'message': message, 'code': code}]}}
    if data is not None:
        payload['data'] = data
    response = JSONResponse(payload, status=status)
    response['Cache-Control'] = 'no-store'
    return response


def refuse_absent(request, id):
    """Answer for a document the user cannot open: gone if they purged it, otherwise not found.

    Missing and not-yours share this one path so the two answers are byte-identical.
    """
    if PurgedDocument.objects.filter(owner=request.user, pk=id).exists():
        return refuse('gone', 410, 'This document was permanently deleted.')
    return not_found()


def not_found():
    return refuse('not_found', 404, 'No such document.')
