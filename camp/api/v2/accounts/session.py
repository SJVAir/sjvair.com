import json

from camp.utils.encoders import JSONEncoder

from . import serializers

# The API token is for token clients (mobile app, SDK users). A session-cookie
# client never needs it, so it is dropped from the responses it gets.
SESSION_EXCLUDE = ('api_token',)


def is_session_request(request):
    """
    True when resticus authenticated the request by session. resticus sets
    `request.authenticator` to None on the session path and to the
    authenticator instance when a token authenticated the request.
    """
    return getattr(request, 'authenticator', None) is None


class SessionUserMixin:
    """
    Account endpoints that require a signed-in user (401 when signed out) and
    leave `api_token` out of the response for session-cookie requests.
    """
    login_required = True

    def serialize(self, source, fields=None, include=None, exclude=None, fixup=None):
        if is_session_request(self.request):
            exclude = [*(exclude or []), *SESSION_EXCLUDE]
        return super().serialize(
            source, fields=fields, include=include, exclude=exclude, fixup=fixup
        )


def session_user_data(user):
    """
    The account response for a session-cookie user, as JSON-ready primitives
    (the `id` a string, as the API sends it).
    """
    data = serializers.UserSerializer(user, exclude=SESSION_EXCLUDE).data
    return json.loads(json.dumps(data, cls=JSONEncoder))
