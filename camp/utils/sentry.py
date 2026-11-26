"""The Sentry `before_send` for every privacy rule we apply to error reports.

Documents requests lose their body and frame locals (see camp.apps.documents.sentry). The place
lookup takes coordinates, so its request data, query string and frame locals are dropped too.
Everything else is left as it is. No Django imports: settings load this module.
"""
from urllib.parse import urlsplit

from camp.apps.documents.sentry import is_documents_event, scrub_documents, stacktraces

# Shared with camp.api.middleware.CoordinateQueryGuardMiddleware.
LOOKUP_PATH = '/api/2.0/regions/places/lookup'


def is_lookup_path(path):
    """The place lookup's path, with or without its trailing slash."""
    return path.rstrip('/') == LOOKUP_PATH


def is_lookup_event(event):
    url = (event.get('request') or {}).get('url') or ''
    return is_lookup_path(urlsplit(url).path)


def scrub_lookup(event):
    request = event['request']
    request.pop('data', None)
    request.pop('query_string', None)
    if request.get('url'):
        request['url'] = urlsplit(request['url'])._replace(query='', fragment='').geturl()
    event.pop('breadcrumbs', None)
    for value in (event.get('exception') or {}).get('values') or []:
        value.pop('value', None)
    for stacktrace in stacktraces(event):
        for frame in stacktrace.get('frames') or []:
            frame.pop('vars', None)
    return event


def scrub_event(event, hint=None):
    if is_documents_event(event):
        return scrub_documents(event, hint)
    if is_lookup_event(event):
        return scrub_lookup(event)
    return event
