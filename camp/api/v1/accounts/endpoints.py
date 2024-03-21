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

from resticus import generics
from resticus.http import JSONResponse
from resticus.exceptions import AuthenticationFailed
from resticus.permissions import AllowAny
from resticus.serializers import serialize
from resticus.settings import api_settings
from resticus.views import TokenAuthEndpoint, Endpoint
from sentry_sdk import capture_exception
from twilio.base.exceptions import TwilioRestException

from camp.apps.accounts.models import User

from .forms import (
    PasswordResetForm,
    UserForm,
    PhoneVerificatonForm,
)
from .serializers import UserSerializer


class LoginEndpoint(TokenAuthEndpoint):
    """
    Logs in a user and gets auth token
    """
    pass


class RegisterEndpoint(generics.CreateEndpoint):
    """
    Create a new user and send code for phone number validation.
    """
    form_class = UserForm
    model = User
    serializer = UserSerializer


class PhoneValidationEndpoint(Endpoint):
    """
    Send the user a code for phone number validation.
    """
    form_class = UserForm

    def get(self, request, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return JSONResponse(
                {"error": _("Please log in to validate phone number.")}, status=400
            )

        code = "".join([random.choice(digits) for _ in range(6)])
        cache_key = f"phv|user:{user.phone}"
        cache.set(cache_key, code, 60 * 30)

        msg = _(
            f"Your one time verificaton code: {code}. This code will expire in 15 minutes."
        )

        try:
            tasks.send_sms_message(user.phone, msg)
            return JSONResponse(
                {
                    "message": _(
                        f"Verification code was sent to phone number ending in {str(user.phone)[-4:]}."
                    )
                },
                status=200,
            )

        except TwilioRestException as e:
            error_msg = _(f"Could not send message. {e}")
            capture_exception(e)
            return JSONResponse({"error": error_msg}, status=400)


class PhoneValidationConfirmEndpoint(Endpoint):
    """
    User can enter the code to validate their phone number.
    """

    def post(self, request, *args, **kwargs):
        user = User.objects.get(pk=kwargs["user_id"])
        form = PhoneVerificatonForm(request.data, request=request, user=user)
        if form.is_valid():
            return self.form_valid(form)
        return self.form_invalid(form)

    def form_valid(self, form):
        form.save()
        return JSONResponse({"message": _("Phone number was successfully confirmed.")})

    def form_invalid(self, form):
        return JSONResponse({"errors": form.errors.get_json_data()}, status=400)


class UserDetail(generics.DetailUpdateDeleteEndpoint):
    """
    Retrieve, update or delete a user
    """

    form_class = UserForm

    def get_object(self):
        return self.request.user

    def get_form(self, **kwargs):
        return super().get_form(request=self.request, **kwargs)


class PasswordResetEndpoint(Endpoint):
    """
    User can request an email with a password reset code.
    """

    def post(self, request, *args, **kwargs):
        # 1. Validate the email address submitted
        try:
            email = forms.EmailField().clean(request.data.get("email"))
        except forms.ValidationError:
            return JSONResponse(
                {"error": {"email": _("Please enter a valid email address.")}}
            )

        # 2. Confirm that the user exists
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            subject = _("Password Reset Request")
            # fmt: off
            from_email = "SJVAir <no-reply@sjvair.com>"
            # fmt: on
            context = {
                "reset_link": reverse("api:v1:reset-password"),
                "register_link": reverse("api:v1:register"),
            }

            try:
                send_email(
                    emailclass=PasswordResetInvalidEmail,
                    context=context,
                    subject=subject,
                    from_email=from_email,
                    send_to=[email],
                )

                return JSONResponse(
                    {
                        "status": _("Password reset email was sent to {email}.").format(
                            email=email
                        )
                    }
                )

            except AnymailRequestsAPIError as e:
                if "'to' parameter is not a valid address." in e.response.text:
                    return JSONResponse(
                        {
                            "status": _(
                                "Unable to send. {} is not a valid email."
                            ).format(email)
                        }
                    )
                else:
                    return JSONResponse({"status": _("Unable to send message.")})

        # 3. Create the reset code and go!
        code = "".join([random.choice(digits) for _ in range(6)])
        cache_key = f"pwr|user:{email}"
        cache.set(cache_key, code, 60 * 30)

        subject = _("Your Password Reset Code")
        from_email = "SJVAir <no-reply@sjvair.com>"
        context = {"user": user, "code": code}

        try:
            send_email(
                emailclass=PasswordResetEmail,
                context=context,
                subject=subject,
                from_email=from_email,
                send_to=[email],
            )

            return JSONResponse(
                {
                    "status": _("Password reset email was sent to {email}.").format(
                        email=email
                    )
                }
            )

        except AnymailRequestsAPIError as e:
            if "'to' parameter is not a valid address." in e.response.text:
                return JSONResponse(
                    {
                        "status": _("Unable to send. {} is not a valid email.").format(
                            email
                        )
                    }
                )
            else:
                return JSONResponse(
                    {"status": _("Unable to send. {}").format(e.response["message"])}
                )


class PasswordResetConfirmEndpoint(Endpoint):
    """
    User can use the code to reset their password.
    """

    def post(self, request, *args, **kwargs):
        form = PasswordResetForm(request.data, request=request)
        if form.is_valid():
            return self.form_valid(form)
        return self.form_invalid(form)

    def form_valid(self, form):
        form.save()
        return JSONResponse({"message": _("Password successfully updated.")})

    def form_invalid(self, form):
        return JSONResponse({"errors": form.errors.get_json_data()}, status=400)
