from camp.api.v2.accounts.session import session_user_data


# Set by the account delete view; popped by the first /workspace/ page after it.
DELETED_ACCOUNT_SESSION_KEY = 'workspace_deleted_account'


def workspace_identity(user, deleted_account=None):
    """
    The signed-in user as the dashboard reads it from the page (the
    `sjvair-identity` block; shape set by the data-dashboard hosting
    contract): exactly what a session-cookie GET /api/2.0/account/ returns,
    so never the API token. `deletedAccount` is the id of an account just
    deleted in this browser, sent once and only when set.
    """
    user_data = session_user_data(user) if user.is_authenticated else None
    identity = {'v': 1, 'user': user_data}
    if deleted_account:
        identity['deletedAccount'] = deleted_account
    return identity
