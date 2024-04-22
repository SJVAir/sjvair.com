import random

from string import digits
from urllib.parse import urlunsplit, urlencode

import requests

from django import forms
from django.conf import settings
from django.core.cache import cache
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views.generic.base import TemplateView
from django.views.decorators.csrf import csrf_exempt

from resticus import generics, http
from resticus.compat import get_user_model
from resticus.exceptions import AuthenticationFailed
from resticus.permissions import AllowAny
from resticus.serializers import serialize
from resticus.settings import api_settings
from resticus.views import TokenAuthEndpoint, Endpoint
from sentry_sdk import capture_exception
from twilio.base.exceptions import TwilioRestException

from camp.apps.accounts.models import User

from . import forms, serializers


class LoginEndpoint(TokenAuthEndpoint):
    """
    Logs in a user and gets auth token
    """
    
    user_fields = ['id', 'name', 'email', 'phone']

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


class SendPhoneVerificationEndpoint(generics.GenericEndpoint):
    login_required = True
    form_class = forms.SendPhoneVerificationForm

    def post(self, request):
        if request.user.is_authenticated and request.user.phone_verified:
            return http.Http409()

        form = self.get_form(data=request.data)
        if form.is_valid():
            return self.form_valid(form)
        return self.form_invalid(form)

    def get_form(self, *args, **kwargs):
        return super().get_form(user=self.request.user, *args, **kwargs)

    def get_object(self):
        return self.request.user

    def form_valid(self, form):
        self.request.user.send_phone_verification_code()
        return http.Http204()


class ConfirmPhoneVerificationEndpoint(generics.GenericEndpoint):
    login_required = True
    form_class = forms.ConfirmPhoneVerificationForm

    def post(self, request):
        if request.user.is_authenticated and request.user.phone_verified:
            return http.Http409()
            
        form = self.get_form(data=request.data)
        if form.is_valid():
            return self.form_valid(form)
        return self.form_invalid(form)

    def get_form(self, *args, **kwargs):
        return super().get_form(user=self.request.user, *args, **kwargs)

    def get_object(self):
        return self.request.user


class UserDetail(generics.DetailUpdateDeleteEndpoint):
    """
    Retrieve, update or delete a user
    """

    form_class = forms.UserForm

    def get_object(self):
        return self.request.user

    def get_form(self, **kwargs):
        return super().get_form(request=self.request, **kwargs)
