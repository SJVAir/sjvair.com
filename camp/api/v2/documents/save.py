"""Saving a document: request validation and the version-checked save transaction.

Every refusal returns before anything is written. The check order is fixed: shape, size,
blocked build, account, then (inside one transaction holding the row lock) the id and
version checks, and only then the write.
"""
import json
from datetime import timezone as dt_timezone

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from resticus import http

from camp.api.v2.accounts.session import session_user_data
from camp.apps.documents.models import (
    BlockedBuild, DocumentChange, PurgedDocument, SavedDocument, id_validator, measure,
)

from . import serializers
from .responses import refuse

# Ids answered by fixed endpoints (documents/profile/, documents/export/).
RESERVED_IDS = {'profile', 'export'}

FIELDS = (
    'kind', 'schema_version', 'name', 'body', 'deleted_at', 'copied_from', 'base_version',
    'changes', 'account_id', 'build_id', 'snapshot',
)

REQUIRED = 'This field is required.'


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_json(value):
    """False when the value holds NaN or Infinity, which JSON (and PostgreSQL) can't store."""
    try:
        json.dumps(value, allow_nan=False)
    except ValueError:
        return False
    return True


def parse_moment(value):
    """An aware datetime from an ISO 8601 string (naive means UTC), or None if it isn't one."""
    if not isinstance(value, str):
        return None
    try:
        moment = parse_datetime(value)
    except ValueError:
        return None
    if moment is not None and timezone.is_naive(moment):
        moment = timezone.make_aware(moment, dt_timezone.utc)
    return moment


def short_string(value, limit=64):
    return isinstance(value, str) and len(value) <= limit


def check_id(id):
    if id in RESERVED_IDS or id_validator.regex.match(id) is None:
        return 'Enter a valid document id.'
    return None


def check_changes(value):
    if not isinstance(value, list):
        return 'Must be a list.'
    for item in value:
        if (
            not isinstance(item, dict)
            or not is_int(item.get('schema_version'))
            or item['schema_version'] < 1
            or not isinstance(item.get('change'), dict)
        ):
            return 'Each change must be {schema_version: integer >= 1, change: object}.'
    if not is_json(value):
        return 'Must be valid JSON (no NaN or Infinity).'
    return None


def check_field(name, value):
    """The error message for one save field, or None when it is valid."""
    if name == 'kind':
        return None if value == 'dashboard' else 'Only "dashboard" documents can be saved.'
    if name == 'schema_version':
        return None if is_int(value) and value >= 1 else 'Must be an integer >= 1.'
    if name == 'name':
        return None if value is None or short_string(value, 100) else (
            'Must be null or a string of at most 100 characters.'
        )
    if name == 'body':
        if not isinstance(value, dict):
            return 'Must be an object.'
        return None if is_json(value) else 'Must be valid JSON (no NaN or Infinity).'
    if name == 'deleted_at':
        if value is None:
            return None
        return None if parse_moment(value) else (
            'Must be null or an ISO 8601 date and time.'
        )
    if name == 'copied_from':
        return None if value is None or short_string(value) else (
            'Must be null or a string of at most 64 characters.'
        )
    if name == 'base_version':
        return None if value is None or (is_int(value) and value >= 0) else (
            'Must be null or an integer >= 0.'
        )
    if name == 'changes':
        return check_changes(value)
    if name in ('account_id', 'build_id'):
        return None if short_string(value) else 'Must be a string of at most 64 characters.'
    if name == 'snapshot':
        return None if value in (None, 'conflict') else 'Must be null or "conflict".'
    raise KeyError(name)


def validate(data, id):
    """Check a save request's shape. Returns (cleaned, errors); `errors` maps field to messages."""
    errors = {}
    message = check_id(id)
    if message:
        errors['id'] = [message]
    if not isinstance(data, dict):
        errors['request'] = ['The request must be a JSON object.']
        return {}, errors

    cleaned = {}
    for name in FIELDS:
        if name not in data:
            errors[name] = [REQUIRED]
            continue
        message = check_field(name, data[name])
        if message:
            errors[name] = [message]
        else:
            cleaned[name] = data[name]
    if errors:
        return {}, errors

    if cleaned['deleted_at'] is not None:
        cleaned['deleted_at'] = parse_moment(cleaned['deleted_at'])
    cleaned['changes'] = [
        {'schema_version': item['schema_version'], 'change': item['change']}
        for item in cleaned['changes']
    ]
    return cleaned, {}


def changes_since(doc, base_version):
    """Log entries for versions base_version+1 … doc.version, or None if the log can't say."""
    if base_version is None or base_version > doc.version:
        return None
    rows = list(
        doc.changes.filter(version__gt=base_version, version__lte=doc.version).order_by('version')
    )
    if len(rows) != doc.version - base_version:
        return None
    return serializers.entries(rows)


def stale(doc, base_version):
    return refuse('stale_base', 409, 'The document changed since this save was based on it.', {
        'version': doc.version,
        'schema_version': doc.schema_version,
        'changes': changes_since(doc, base_version),
        'document': serializers.document(doc),
    })


def apply_save(user, id, cleaned):
    """Run the checks that need the database, then write. Returns the response."""
    cleaned['size'] = measure(cleaned['body'])
    if cleaned['size'] > settings.DOCUMENTS_MAX_BODY or (
        measure(cleaned['changes']) > settings.DOCUMENTS_MAX_CHANGES
    ):
        return too_large()

    if BlockedBuild.objects.filter(build_id=cleaned['build_id']).exists():
        return refuse('build_blocked', 409, 'This version of the app can no longer save.')

    signed_in_as = session_user_data(user)['id']
    if cleaned['account_id'] != signed_in_as:
        return refuse(
            'account_mismatch', 403, 'This save belongs to a different account.',
            {'signed_in_as': signed_in_as},
        )

    # (Task 4: the per-account rate limit goes here, before the transaction.)

    try:
        return save_locked(user, id, cleaned)
    except IntegrityError:
        # Another request created this id between our lookup and insert. Run the checks
        # again: they now see that row and refuse (stale_base or id_taken).
        return save_locked(user, id, cleaned)


def save_locked(user, id, cleaned):
    with transaction.atomic():
        doc = SavedDocument.objects.select_for_update().filter(pk=id).first()

        purged = PurgedDocument.objects.filter(pk=id).first()
        if purged is not None:
            if purged.owner_id == user.pk:
                return refuse('gone', 410, 'This document was permanently deleted.')
            return id_taken()
        if doc is not None and doc.owner_id != user.pk:
            return id_taken()

        base_version = cleaned['base_version']
        if doc is None:
            if base_version is not None:
                return refuse('not_found', 404, 'No such document.')
        else:
            if base_version is None or base_version != doc.version:
                return stale(doc, base_version)
            if cleaned['schema_version'] < doc.schema_version:
                return refuse(
                    'schema_downgrade', 409, 'The stored document uses a newer schema.',
                    {'schema_version': doc.schema_version},
                )

        # (Task 4: the document-count and storage limits go here, after the version checks.)

        # (Task 4: the snapshot step goes here, before the write.)

        return write(user, id, doc, cleaned)


def write(user, id, doc, cleaned):
    created = doc is None
    if created:
        doc = SavedDocument(id=id, owner=user, version=0)
    doc.kind = cleaned['kind']
    doc.name = cleaned['name']
    doc.body = cleaned['body']
    doc.size = cleaned['size']
    doc.schema_version = cleaned['schema_version']
    doc.deleted_at = cleaned['deleted_at']
    doc.copied_from = cleaned['copied_from']
    doc.version += 1
    doc.save(force_insert=created)

    DocumentChange.objects.create(document=doc, version=doc.version, entries=cleaned['changes'])
    doc.changes.filter(version__lte=doc.version - settings.DOCUMENTS_LOG_LIMIT).delete()

    return http.Http200({'data': {'version': doc.version, 'updated_at': doc.updated_at}})


def id_taken():
    return refuse('id_taken', 409, 'This id is already in use.')


def too_large():
    return refuse('too_large', 413, 'The document is too large to save.')
