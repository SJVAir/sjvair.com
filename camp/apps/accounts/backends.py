from django.contrib.auth import backends, get_user_model


class AuthenticationBackend(backends.ModelBackend):
    '''
        Custom authentication backend that allows the user
        to login with their email address or phone number.
    '''
    def authenticate(self, request, identifier=None, password=None, **kwargs):
        if identifier is None or password is None:
            return

        if not isinstance(identifier, str):
            identifier = str(identifier)

        UserModel = get_user_model()

        try:
            user = UserModel.objects.get(email__iexact=str(identifier))
        except UserModel.DoesNotExist:
            try:
                user = UserModel.objects.get(phone=identifier)
            except UserModel.DoesNotExist:
                # Run the default password hasher once to reduce the timing
                # difference between an existing and a nonexistent user (#20760).
                UserModel().set_password(password)
                return

        if user.check_password(password):
            return user
