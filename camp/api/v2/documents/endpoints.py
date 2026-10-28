from datetime import timedelta, timezone as dt_timezone

from io import BytesIO

from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from resticus import http
from resticus.views import Endpoint

from camp.apps.documents.models import PurgedDocument, SavedDocument

from camp.apps.documents import purge

from . import save, serializers
from .responses import refuse

CURSOR_OVERLAP = timedelta(seconds=10)


class NoStoreMixin:
    """Puts `Cache-Control: no-store` on every response, resticus's own errors included.

    A request over DATA_UPLOAD_MAX_MEMORY_SIZE is refused as `too_large` (resticus reads the
    body before its own error handling, so Django would otherwise answer with an HTML 400).
    """

    def dispatch(self, request, *args, **kwargs):
        try:
            response = super().dispatch(request, *args, **kwargs)
        except RequestDataTooBig:
            response = save.too_large()
        response['Cache-Control'] = 'no-store'
        return response


def owned_document(request, id):
    """The signed-in user's document, or None when it is missing or someone else's."""
    return SavedDocument.objects.filter(owner=request.user, pk=id).first()


def refuse_absent(request, id):
    """Answer for a document the user cannot open: gone if they purged it, otherwise not found.

    Missing and not-yours share this one path so the two answers are byte-identical.
    """
    if PurgedDocument.objects.filter(owner=request.user, pk=id).exists():
        return refuse('gone', 410, 'This document was permanently deleted.')
    return refuse('not_found', 404, 'No such document.')


class DocumentList(NoStoreMixin, Endpoint):
    documented = False
    login_required = True

    def get(self, request):
        now = timezone.now()
        documents = SavedDocument.objects.filter(owner=request.user)
        purged = []
        since = request.params.get('since')
        if since:
            moment = parse_datetime(since)
            if moment is None:
                return refuse(
                    'invalid', 400, 'since must be an ISO 8601 date and time.',
                    {'fields': {'since': ['Enter a valid date and time.']}},
                )
            if timezone.is_naive(moment):
                moment = timezone.make_aware(moment, dt_timezone.utc)
            documents = documents.filter(updated_at__gte=moment)
            purged = list(
                PurgedDocument.objects.filter(owner=request.user, purged_at__gte=moment)
                .order_by('purged_at')
                .values_list('id', flat=True)
            )
        return http.Http200({'data': {
            'documents': [serializers.meta(doc) for doc in documents.order_by('created_at', 'id')],
            'purged': purged,
            'cursor': now - CURSOR_OVERLAP,
        }})


def read_save_body(request):
    """Read a signed-in save's body under DOCUMENTS_MAX_REQUEST_BYTES instead of Django's cap.

    resticus reads the body before it authenticates, so the larger cap is applied here, and
    only for a PUT from a session user; everyone else keeps DATA_UPLOAD_MAX_MEMORY_SIZE.
    Returns a refusal when the request is too large, otherwise None (the body is then cached
    on the request, so Django's own cap check is skipped for this request only).
    """
    try:
        length = int(request.META.get('CONTENT_LENGTH') or 0)
    except ValueError:
        return save.too_large()
    if length < 0 or length > settings.DOCUMENTS_MAX_REQUEST_BYTES:
        return save.too_large()
    request._body = request.read()
    request._stream = BytesIO(request._body)
    return None


def is_session_user(request):
    user = getattr(request, 'user', None)
    return user is not None and user.is_authenticated


class DocumentDetail(NoStoreMixin, Endpoint):
    documented = False
    login_required = True

    def dispatch(self, request, *args, **kwargs):
        if request.method == 'PUT' and is_session_user(request):
            refusal = read_save_body(request)
            if refusal is not None:
                return refusal
        return super().dispatch(request, *args, **kwargs)

    def parse_body(self, request):
        # A DELETE carries no body, and resticus would refuse one with no content type.
        if request.method == 'DELETE':
            return (None, None)
        return super().parse_body(request)

    def get(self, request, id):
        doc = owned_document(request, id)
        if doc is None:
            return refuse_absent(request, id)
        return http.Http200({'data': serializers.document(doc)})

    def put(self, request, id):
        cleaned, errors = save.validate(request.data, id)
        if errors:
            return refuse('invalid', 400, 'The save is invalid.', {'fields': errors})
        return save.apply_save(request.user, id, cleaned)

    def delete(self, request, id):
        doc = owned_document(request, id)
        if doc is None:
            return refuse_absent(request, id)
        if doc.deleted_at is None:
            return refuse('not_deleted', 409, 'Move the document to the trash first.')
        purge.purge_document(doc)
        return http.Http204()


class DocumentChanges(NoStoreMixin, Endpoint):
    """What open dashboards poll: the changes after version `since`, or just the version."""
    documented = False
    login_required = True

    def get(self, request, id):
        since = parse_since(request.params.get('since'))
        if since is None:
            return refuse(
                'invalid', 400, 'since must be an integer of 0 or more.',
                {'fields': {'since': ['Enter a whole number of 0 or more.']}},
            )
        doc = owned_document(request, id)
        if doc is None:
            return refuse_absent(request, id)
        if since == doc.version:
            return http.Http200({'data': {'version': doc.version}})
        return http.Http200({'data': {
            'version': doc.version,
            'changes': save.changes_since(doc, since),
            'document': serializers.document(doc),
        }})


def parse_since(value):
    """`since` as an int >= 0, or None when it is missing or not one."""
    if value is None or not value.isascii() or not value.isdigit():
        return None
    return int(value)
