def workspace_identity(user):
    """
    The signed-in user as the dashboard reads it from the page (the
    `sjvair-identity` block; shape set by the data-dashboard hosting
    contract). Never the API token, never the phone number.
    """
    if not user.is_authenticated:
        return {'v': 1, 'user': None}
    return {'v': 1, 'user': {
        'id': str(user.pk),
        'name': user.full_name,
        'email': user.email or None,
        'emailVerified': False,  # until accounts have verified emails
        'phoneVerified': user.phone_verified,
    }}
