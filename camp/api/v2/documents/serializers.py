from camp.apps.documents.models import DocumentProfile


def meta(doc):
    """DocumentMeta: a Document without its body, plus its size."""
    return {
        'id': doc.id,
        'kind': doc.kind,
        'name': doc.name,
        'schema_version': doc.schema_version,
        'version': doc.version,
        'copied_from': doc.copied_from,
        'deleted_at': doc.deleted_at,
        'created_at': doc.created_at,
        'updated_at': doc.updated_at,
        'visibility': doc.visibility,
        'share_token': doc.share_token,
        'size': doc.size,
    }


def document(doc):
    """Document: everything a client needs to open a dashboard."""
    data = meta(doc)
    del data['size']
    data['body'] = doc.body
    return data


def entries(changes):
    """Flatten saved DocumentChange rows (in order) into Entry dicts."""
    return [
        {
            'version': change.version,
            'schema_version': entry['schema_version'],
            'change': entry['change'],
        }
        for change in changes
        for entry in change.entries
    ]


def owner_profile(doc):
    """The owner's DocumentProfile, or None when they have never set one up."""
    try:
        return doc.owner.document_profile
    except DocumentProfile.DoesNotExist:
        return None


def sharing_blocked(doc):
    """Whether this document may not be shared: turned off for it, or for its owner."""
    profile = owner_profile(doc)
    return doc.sharing_disabled or (profile is not None and profile.sharing_blocked)


def shareable(doc):
    """Whether a share link may open this document right now."""
    return (
        doc.visibility in ('link', 'public')
        and bool(doc.share_token)
        and doc.deleted_at is None
        and not sharing_blocked(doc)
    )


def display_name(doc):
    """The owner's chosen public name, never their real name: None unless they set one."""
    profile = owner_profile(doc)
    return (profile.display_name or None) if profile is not None else None


def shared(doc):
    """SharedDocument: what a share link shows. Carries nothing that identifies the owner.

    The id is the document's own (so a copy can record `copied_from`), not the owner's.
    """
    return {
        'id': doc.id,
        'kind': doc.kind,
        'name': doc.name,
        'schema_version': doc.schema_version,
        'version': doc.version,
        'body': doc.body,
        'updated_at': doc.updated_at,
        'display_name': display_name(doc),
    }


def credit(doc):
    """What a copy's "Based on…" line shows: the dashboard's name and the owner's public name."""
    return {'name': doc.name, 'display_name': display_name(doc)}
