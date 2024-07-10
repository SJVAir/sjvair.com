from resticus import serializers
from resticus.auth import TokenAuth

from camp.apps.accounts.models import User


# TODO: This should be a shortcut in `resticus.auth.TokenAuth`.
def get_token(user):
    TokenModel = TokenAuth.get_token_model()
    token, created = TokenModel.objects.get_or_create(user=user)
    return token.key


class UserSerializer(serializers.Serializer):
    model = User
    fields = [
        'id',
        'full_name',
        'email',
        'phone',
        'phone_verified',
        'language',
        ('api_token', get_token),
    ]
