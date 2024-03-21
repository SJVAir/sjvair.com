from resticus import serializers

from camp.apps.accounts.models import User

class UserSerializer(serializers.Serializer):
    model = User
    fields = ['full_name', 'email', 'phone', 'language']
