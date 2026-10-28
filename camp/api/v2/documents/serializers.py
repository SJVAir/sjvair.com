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
