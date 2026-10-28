"""Keeps dashboard contents out of server error reports.

Sentry sends request bodies and stack-frame local variables by default, so an error inside a
documents endpoint could carry a private dashboard's body or name. For those requests both are
dropped; every other event is left as it is. No Django imports: settings load this module.
"""
from urllib.parse import urlsplit

DOCUMENTS_PATH = '/api/2.0/documents/'


def is_documents_event(event):
    url = (event.get('request') or {}).get('url') or ''
    return urlsplit(url).path.startswith(DOCUMENTS_PATH)


def stacktraces(event):
    """Every stacktrace in the event: on exceptions, on threads, and at the top level."""
    for key in ('exception', 'threads'):
        for value in (event.get(key) or {}).get('values') or []:
            if value.get('stacktrace'):
                yield value['stacktrace']
    if event.get('stacktrace'):
        yield event['stacktrace']


def scrub_documents(event, hint=None):
    """A Sentry `before_send`: drop request data and frame locals for documents requests."""
    if not is_documents_event(event):
        return event
    event['request'].pop('data', None)
    for stacktrace in stacktraces(event):
        for frame in stacktrace.get('frames') or []:
            frame.pop('vars', None)
    return event

