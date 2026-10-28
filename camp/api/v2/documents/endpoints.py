from datetime import timedelta, timezone as dt_timezone

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from resticus import http
from resticus.views import Endpoint

from camp.apps.documents.models import PurgedDocument, SavedDocument

from . import serializers
from .responses import refuse

CURSOR_OVERLAP = timedelta(seconds=10)


class NoStoreMixin:
    """Puts `Cache-Control: no-store` on every response, resticus's own errors included."""

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
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


class DocumentDetail(NoStoreMixin, Endpoint):
    documented = False
    login_required = True

    def get(self, request, id):
        doc = owned_document(request, id)
        if doc is None:
            return refuse_absent(request, id)
        return http.Http200({'data': serializers.document(doc)})
