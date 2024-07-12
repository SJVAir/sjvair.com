import random

from string import digits
from urllib.parse import urlunsplit, urlencode

import requests

from django import forms
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.contrib.auth import forms as auth_forms
from django.contrib.auth.tokens import default_token_generator as token_generator
from django.utils.decorators import method_decorator
from django.utils.http import urlsafe_base64_decode
from django.utils.translation import gettext as _
from django.views.generic.base import TemplateView
from django.views.decorators.csrf import csrf_exempt

from resticus import generics, http, mixins
from resticus.compat import get_user_model
from resticus.exceptions import AuthenticationFailed
from resticus.permissions import AllowAny
from resticus.serializers import serialize
from resticus.settings import api_settings
from resticus.views import TokenAuthEndpoint, Endpoint
from sentry_sdk import capture_exception
from twilio.base.exceptions import TwilioRestException

from camp.api.v1.endpoints import FormEndpoint
from camp.apps.alerts.models import Alert
from camp.apps.accounts.models import User

from . import forms, serializers


class AlertList(generics.ListEndpoint):
    model = Alert
    login_required = True

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = (queryset
            .filter(
                monitor__subscriptions__user_id=self.request.user.pk,
                end_time__isnull=True
            )
            .select_related('monitor')
            .distinct()
        )
        return queryset


class LoginEndpoint(TokenAuthEndpoint):
    """
    Logs in a user and gets auth token
    """
    
    serializer_class = serializers.UserSerializer

    def get(self, request, **kwargs):
        data = self.serializer_class(request.user).data
        return http.Http200({"data": data})

    def get_credentials(self, request):
        return {
            'identifier': request.data.get('identifier'),
            'password': request.data.get("password"),
        }


class RegisterEndpoint(generics.CreateEndpoint):
    """
    Create a new user and send code for phone number validation.
    """
    form_class = forms.UserForm
    model = User
    serializer_class = serializers.UserSerializer


class UserDetail(generics.DetailUpdateDeleteEndpoint):
    """
    Retrieve, update or delete a user
    """

    form_class = forms.UserForm
    model = User
    serializer_class = serializers.UserSerializer

    def get_object(self):
        return self.request.user


class ChangePasswordEndpoint(mixins.UpdateModelMixin, generics.GenericEndpoint):
    form_class = auth_forms.PasswordChangeForm
    model = User
    serializer_class = serializers.UserSerializer

    def get_object(self):
        return self.request.user

    def get_form(self, **kwargs):
        kwargs.update(user=kwargs.pop('instance'))
        return super().get_form(**kwargs)


class SendPhoneVerificationEndpoint(FormEndpoint):
    login_required = True
    form_class = forms.SendPhoneVerificationForm

    def post(self, request):
        if request.user.is_authenticated and request.user.phone_verified:
            return http.Http409()

        return super().post(request)

    def get_form(self, *args, **kwargs):
        return super().get_form(user=self.request.user, *args, **kwargs)

    def form_valid(self, form):
        self.request.user.send_phone_verification_code()
        return http.Http204()


class ConfirmPhoneVerificationEndpoint(FormEndpoint):
    login_required = True
    form_class = forms.ConfirmPhoneVerificationForm

    def post(self, request):
        if request.user.is_authenticated and request.user.phone_verified:
            return http.Http409()

        return super().post(request)

    def get_form(self, *args, **kwargs):
        return super().get_form(user=self.request.user, *args, **kwargs)

    def form_valid(self, form):
        form.save()
        return http.Http204()


class PasswordResetEndpoint(FormEndpoint):
    form_class = forms.PasswordResetForm

    def form_valid(self, form):
        options = form.save()
        return {'data': options}


class PasswordResetConfirmEndpoint(FormEndpoint):
    form_class = forms.SetPasswordForm

    def dispatch(self, *args, **kwargs):
        try:
            uidb64 = kwargs['uidb64']
            token = kwargs['token']
        except (KeyError, TypeError):
            print('args', args)
            print('kwargs', kwargs)
            return self.invalid_token()

        self.user = self.get_user(uidb64)
        if self.user and token_generator.check_token(self.user, token):
            return super().dispatch(*args, **kwargs)
        print('the end')
        return self.invalid_token()

    def invalid_token(self):
        return http.Http400({'error': 'Invalid token'})

    def get_user(self, uidb64):
        try:
            user_id = urlsafe_base64_decode(uidb64).decode()
            return User._default_manager.get(pk=user_id)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist, ValidationError):
            return None

    def get_form(self, *args, **kwargs):
        return super().get_form(user=self.user, *args, **kwargs)

    def form_valid(self, form):
        form.save()
        return http.Http204()
