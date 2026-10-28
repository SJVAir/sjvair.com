import json
import secrets

from datetime import timedelta, timezone as dt_timezone

from io import BytesIO
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.http import HttpResponse
from django.utils import timezone
from resticus import http
from resticus.views import Endpoint

from camp.apps.documents.models import DocumentProfile, PurgedDocument, SavedDocument

from camp.apps.documents import purge

from . import save, serializers
from .responses import refuse

CURSOR_OVERLAP = timedelta(seconds=10)
PACIFIC = ZoneInfo('America/Los_Angeles')


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


class BodilessMixin:
    """Skips body parsing for `bodiless_methods`: resticus refuses a body with no content type."""

    bodiless_methods = ()

    def parse_body(self, request):
        if request.method in self.bodiless_methods:
            return (None, None)
        return super().parse_body(request)


def owned_document(request, id, with_body=True):
    """The signed-in user's document, or None when it is missing or someone else's.

    Pass `with_body=False` where only its metadata is used, to skip loading the body.
    """
    documents = SavedDocument.objects.filter(owner=request.user, pk=id)
    if not with_body:
        documents = documents.defer('body')
    return documents.first()


def refuse_absent(request, id):
    """Answer for a document the user cannot open: gone if they purged it, otherwise not found.

    Missing and not-yours share this one path so the two answers are byte-identical.
    """
    if PurgedDocument.objects.filter(owner=request.user, pk=id).exists():
        return refuse('gone', 410, 'This document was permanently deleted.')
    return not_found()


def not_found():
    return refuse('not_found', 404, 'No such document.')


def not_deleted():
    return refuse('not_deleted', 409, 'Move the document to the trash first.')


class DocumentList(NoStoreMixin, Endpoint):
    documented = False
    login_required = True

    def get(self, request):
        now = timezone.now()
        documents = SavedDocument.objects.filter(owner=request.user).defer('body')
        purged = []
        since = request.params.get('since')
        if since:
            moment = save.parse_moment(since)
            if moment is None:
                return refuse(
                    'invalid', 400, 'since must be an ISO 8601 date and time.',
                    {'fields': {'since': ['Enter a valid date and time.']}},
                )
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


class DocumentExport(NoStoreMixin, Endpoint):
    """The "Download my dashboards" backup: the dashboard's own backup file format."""
    documented = False
    login_required = True

    def get(self, request):
        now = timezone.now()
        documents = SavedDocument.objects.filter(
            owner=request.user, deleted_at__isnull=True
        ).order_by('created_at', 'id')
        envelope = {
            'format': 'sjvair-workspace',
            'type': 'backup',
            'formatVersion': 1,
            'exportedAt': file_timestamp(now),
            'documents': [backup_document(doc) for doc in documents],
        }
        response = HttpResponse(
            json.dumps(envelope, ensure_ascii=False, separators=(',', ':')),
            content_type='application/json',
        )
        day = now.astimezone(PACIFIC).strftime('%Y-%m-%d')
        response['Content-Disposition'] = f'attachment; filename="sjvair-dashboards-{day}.json"'
        return response


def file_timestamp(moment):
    """An instant as the dashboard writes it (`Date.toISOString()`): UTC, milliseconds, Z."""
    moment = moment.astimezone(dt_timezone.utc)
    return moment.strftime('%Y-%m-%dT%H:%M:%S.') + f'{moment.microsecond // 1000:03d}Z'


def backup_document(doc):
    """One document in the backup file (camelCase, the dashboard's format; version restarts)."""
    data = {
        'kind': doc.kind,
        'schemaVersion': doc.schema_version,
        'id': doc.id,
        'name': doc.name,
    }
    if doc.copied_from:
        data['copiedFrom'] = doc.copied_from
    data.update({
        'version': 0,
        'createdAt': file_timestamp(doc.created_at),
        'updatedAt': file_timestamp(doc.updated_at),
        'body': doc.body,
    })
    return data


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


class DocumentDetail(NoStoreMixin, BodilessMixin, Endpoint):
    documented = False
    login_required = True
    bodiless_methods = ('DELETE',)

    def dispatch(self, request, *args, **kwargs):
        if request.method == 'PUT' and is_session_user(request):
            refusal = read_save_body(request)
            if refusal is not None:
                return refusal
        return super().dispatch(request, *args, **kwargs)

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
            return not_deleted()
        if not purge.purge_document(doc):
            # Restored or purged since it was read: answer for the row as it is now.
            doc = owned_document(request, id)
            if doc is None:
                return refuse_absent(request, id)
            return not_deleted()
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


class DocumentSnapshotList(NoStoreMixin, Endpoint):
    """A document's snapshots, newest first, without their bodies."""
    documented = False
    login_required = True

    def get(self, request, id):
        doc = owned_document(request, id, with_body=False)
        if doc is None:
            return refuse_absent(request, id)
        snapshots = doc.snapshots.defer('body').order_by('-created_at', '-id')
        return http.Http200({'data': [
            {
                'id': snap.id,
                'version': snap.version,
                'schema_version': snap.schema_version,
                'reason': snap.reason,
                'created_at': snap.created_at,
            }
            for snap in snapshots
        ]})


class DocumentSnapshotDetail(NoStoreMixin, Endpoint):
    documented = False
    login_required = True

    def get(self, request, id, snapshot_id):
        doc = owned_document(request, id)
        if doc is None:
            return refuse_absent(request, id)
        snap = doc.snapshots.filter(pk=snapshot_id).first()
        if snap is None:
            return not_found()
        return http.Http200({'data': {
            'id': snap.id,
            'version': snap.version,
            'schema_version': snap.schema_version,
            'name': snap.name,
            'body': snap.body,
            'created_at': snap.created_at,
        }})


def parse_since(value):
    """`since` as an int >= 0, or None when it is missing or not one."""
    if value is None or not value.isascii() or not value.isdigit():
        return None
    return int(value)


class DocumentShare(NoStoreMixin, BodilessMixin, Endpoint):
    """Turn a document's share link on (POST) or off (DELETE)."""
    documented = False
    login_required = True
    bodiless_methods = ('POST', 'DELETE')

    def post(self, request, id):
        doc = owned_document(request, id)
        if doc is None or doc.deleted_at is not None:
            return not_found()
        if serializers.sharing_blocked(doc):
            return refuse('sharing_blocked', 403, 'Sharing is turned off for this dashboard.')
        doc.visibility = SavedDocument.Visibility.LINK
        if not doc.share_token:
            doc.share_token = new_share_token()
        # Sharing is not an edit, so version stays; updated_at moves so `?since=` carries the
        # new visibility and token to the owner's other devices.
        SavedDocument.objects.filter(pk=doc.pk).update(
            visibility=doc.visibility, share_token=doc.share_token, updated_at=timezone.now()
        )
        return http.Http200({'data': {'share_token': doc.share_token}})

    def delete(self, request, id):
        doc = owned_document(request, id)
        if doc is None:
            return not_found()
        # The token is dropped, not kept: sharing again makes a new one, so this link stays dead.
        SavedDocument.objects.filter(pk=doc.pk).update(
            visibility=SavedDocument.Visibility.PRIVATE, share_token=None,
            updated_at=timezone.now(),
        )
        return http.Http204()


def new_share_token():
    while True:
        token = secrets.token_urlsafe(16)
        if not SavedDocument.objects.filter(share_token=token).exists():
            return token


def not_shared():
    """The one answer for a share link that does not open, whatever the reason.

    Private, revoked, deleted, unknown, turned off, and blocked owner all get these same bytes,
    so a link reveals nothing about the document behind it.
    """
    return refuse('not_found', 404, 'This shared dashboard is no longer available.')


def shared_document(token):
    """The document behind a share link, or None when the link does not open."""
    doc = (
        SavedDocument.objects.select_related('owner__document_profile')
        .filter(share_token=token)
        .first()
    )
    if doc is None or not serializers.shareable(doc):
        return None
    return doc


class SharedDocumentDetail(NoStoreMixin, Endpoint):
    """A shared dashboard, for anyone with the link (signed in or not)."""
    documented = False
    login_required = False

    def get(self, request, token):
        doc = shared_document(token)
        if doc is None:
            return not_shared()
        return http.Http200({'data': serializers.shared(doc)})


class SharedDocumentChanges(NoStoreMixin, Endpoint):
    """What an open shared dashboard polls: just the version, or the whole SharedDocument."""
    documented = False
    login_required = False

    def get(self, request, token):
        # The link is checked first, so a bad since never tells a known token from an unknown one.
        doc = shared_document(token)
        if doc is None:
            return not_shared()
        since = parse_since(request.params.get('since'))
        if since is None:
            return refuse(
                'invalid', 400, 'since must be an integer of 0 or more.',
                {'fields': {'since': ['Enter a whole number of 0 or more.']}},
            )
        if since == doc.version:
            return http.Http200({'data': {'version': doc.version}})
        return http.Http200({'data': serializers.shared(doc)})


class DocumentCredit(NoStoreMixin, Endpoint):
    """The "Based on…" credit for a copy: open to the owner, or to anyone while it is shared."""
    documented = False
    login_required = False

    def get(self, request, id):
        doc = SavedDocument.objects.select_related('owner__document_profile').filter(pk=id).first()
        if doc is None:
            return not_found()
        is_owner = request.user.is_authenticated and doc.owner_id == request.user.pk
        if not (is_owner or serializers.shareable(doc)):
            return not_found()
        return http.Http200({'data': serializers.credit(doc)})


class DocumentProfileDetail(NoStoreMixin, Endpoint):
    """The signed-in user's public display name for shared dashboards."""
    documented = False
    login_required = True

    def get(self, request):
        # Reading never creates a profile; a user without one has no display name yet.
        profile = DocumentProfile.objects.filter(user=request.user).first()
        display_name = profile.display_name if profile is not None else None
        return http.Http200({'data': {'display_name': display_name or None}})

    def put(self, request):
        data = request.data
        if not isinstance(data, dict) or 'display_name' not in data:
            return invalid_display_name('This field is required.')
        value = data['display_name']
        if value is not None and not isinstance(value, str):
            return invalid_display_name('Enter text or null.')
        value = (value or '').strip() or None
        max_length = DocumentProfile._meta.get_field('display_name').max_length
        if value is not None and len(value) > max_length:
            return invalid_display_name(f'Use {max_length} characters or fewer.')
        profile, _ = DocumentProfile.objects.get_or_create(user=request.user)
        profile.display_name = value
        profile.save(update_fields=['display_name'])
        return http.Http200({'data': {'display_name': profile.display_name}})


def invalid_display_name(message):
    return refuse(
        'invalid', 400, 'The display name is invalid.', {'fields': {'display_name': [message]}}
    )
