from camp.api.v2.accounts.session import session_user_data


def workspace_identity(user):
    """
    The signed-in user as the dashboard reads it from the page (the
    `sjvair-identity` block; shape set by the data-dashboard hosting
    contract): exactly what a session-cookie GET /api/2.0/account/ returns,
    so never the API token.
    """
    if not user.is_authenticated:
        return {'v': 1, 'user': None}
    return {'v': 1, 'user': session_user_data(user)}
