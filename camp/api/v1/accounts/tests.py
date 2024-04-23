import json
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase, RequestFactory
from django.urls import reverse

from camp.apps.accounts.backends import AuthenticationBackend
from camp.apps.accounts.models import User
from camp.utils.test import debug, get_response_data

from . import endpoints

client = Client()

login = endpoints.LoginEndpoint.as_view()
register = endpoints.RegisterEndpoint.as_view()
# password_reset = endpoints.PasswordResetEndpoint.as_view()
# password_reset_confirm = endpoints.PasswordResetConfirmEndpoint.as_view()
send_phone_verification = endpoints.SendPhoneVerificationEndpoint.as_view()
confirm_phone_verification = endpoints.ConfirmPhoneVerificationEndpoint.as_view()


class AuthenticationTests(TestCase):
    fixtures = ['users']

    def setUp(self):
        self.user = User.objects.get(email="user@sjvair.com")
        self.factory = RequestFactory()

    def test_authentication_backend(self):
        backend = AuthenticationBackend()
        url = reverse("api:v1:account:login")
        request = self.factory.post(url,
            {
                "identifier": "user@sjvair.com",
                "password": "letmein"
            },
            content_type="application/json",
        )
        user = backend.authenticate(
            request=request, identifier=self.user.email, password="letmein",
        )
        assert user is not None
        assert user.pk == self.user.pk

    def test_valid_login(self):
        url = reverse("api:v1:account:login")
        request = self.factory.post(url,
            {
                "identifier": "user@sjvair.com",
                "password": "letmein"
            },
            content_type="application/json",
        )
        response = login(request)
        data = get_response_data(response)

        assert response.status_code == 200
        assert "api_token" in data["data"]
        assert "id" in data["data"]
        assert data["data"]["id"] == str(self.user.pk)

    def test_invalid_login(self):
        url = reverse("api:v1:account:login")
        request = self.factory.post(url,
            {
                "identifier": "user@sjvair.com",
                "password": "lolnope"
            },
            content_type="application/json",
        )
        response = login(request)
        data = get_response_data(response)

        assert response.status_code == 401
        assert "errors" in data

    @patch("camp.apps.accounts.tasks.send_sms_message")
    def test_register_new_user(self, send_sms_message):
        url = reverse("api:v1:account:register")
        payload = {
            "full_name": "Alice Test",
            "email": "alice.test@sjvair.com",
            "phone": "661-555-5555",
            "password": "t0kenize th!s",
            "confirm_password": "t0kenize th!s",
        }
        request = self.factory.post(url, payload, content_type="application/json")
        response = register(request)
        data = get_response_data(response)

        # Assert we got a valid status code and the correct response data.
        assert response.status_code == 201
        assert "api_token" in data["data"]
        assert data['data']['api_token']['key'] is not None
        assert "id" in data["data"]
        assert data["data"]["email"] == payload["email"]

        # Assert the user was created, the password was correctly saved,
        # and they were sent a text to verify their phone number.
        user = User.objects.get(pk=data["data"]["id"])
        assert user.check_password(payload["password"])
        assert send_sms_message.called

    def test_register_invalid_password(self):
        url = reverse("api:v1:account:register")
        payload = {
            "full_name": "Bob Test",
            "email": "bob.test@sjvair.com",
            "phone": "559-555-5555",
            "password": "password",
        }
        request = self.factory.post(url, payload, content_type="application/json")
        response = register(request)
        data = get_response_data(response)

        assert response.status_code == 400
        assert data["errors"]["password"][0]["code"] == "password_too_common"

    def test_register_duplicate_phone(self):
        url = reverse("api:v1:account:register")
        payload = {
            "full_name": "Duplicate User",
            "phone": str(self.user.phone),
            "password": "t0kenize th!s",
        }
        request = self.factory.post(url, payload, content_type="application/json")
        response = register(request)
        data = get_response_data(response)

        assert response.status_code == 400
        assert data["errors"]["phone"][0]["code"] == "duplicate_phone"

    def test_register_duplicate_email(self):
        url = reverse("api:v1:account:register")
        payload = {
            "full_name": "Duplicate User",
            "phone": '818-555-5555',
            "email": self.user.email,
            "password": "t0kenize th!s",
        }
        request = self.factory.post(url, payload, content_type="application/json")
        response = register(request)
        data = get_response_data(response)

        assert response.status_code == 400
        assert data["errors"]["email"][0]["code"] == "duplicate_email"

    def test_register_duplicate_email_case_sensitive(self):
        url = reverse("api:v1:account:register")
        payload = {
            "full_name": "Duplicate User",
            "email": self.user.email.upper(),
            "phone": "818-555-5555",
            "password": "t0kenize th!s",
        }
        request = self.factory.post(url, payload, content_type="application/json")
        response = register(request)
        data = get_response_data(response)

        assert response.status_code == 400
        assert data["errors"]["email"][0]["code"] == "duplicate_email"

    @patch("camp.apps.accounts.tasks.send_sms_message")
    def test_validate_phone(self, send_sms_message):
        self.user.phone = "559-555-5555"
        self.user.phone_verified = False
        self.user.save()

        url = reverse("api:v1:account:phone-verify-send")
        request = self.factory.post(url)
        request.user = self.user
        response = send_phone_verification(request)

        assert response.status_code == 204
        assert send_sms_message.called

    @patch("camp.apps.accounts.tasks.send_sms_message")
    def test_validate_phone_confirm(self, send_sms_message):
        """
        Ensure a user can validate their phone number with the code
        """
        self.user.phone = "559-555-5555"
        self.user.phone_verified = False
        self.user.save()

        code = '123456'
        cache.set(self.user.phone_verification_code_key, code, 30)

        url = reverse("api:v1:account:phone-verify-confirm")
        request = self.factory.post(url, {'code': code})
        request.user = self.user
        response = confirm_phone_verification(request)

        assert response.status_code == 204

        updated = User.objects.get(pk=self.user.pk)
        assert updated.phone_verified == True

    @patch("camp.apps.accounts.tasks.send_sms_message")
    def test_validate_phone_confirm_invalid(self, send_sms_message):
        """
        Ensure a user can validate their phone number with the code
        """
        self.user.phone = "559-555-5555"
        self.user.phone_verified = False
        self.user.save()

        cache.set(self.user.phone_verification_code_key, '123456', 30)

        url = reverse("api:v1:account:phone-verify-confirm")
        request = self.factory.post(url, {'code': '111111'})
        request.user = self.user
        response = confirm_phone_verification(request)
        data = get_response_data(response)

        assert response.status_code == 400
        assert 'errors' in data
        assert User.objects.filter(pk=self.user.pk, phone_verified=False).exists()

    # def test_get_password_reset_code(self):
    #     """
    #     Ensure a user can request a reset password code
    #     """
    #     url = reverse("api:v1:password-reset")
    #     payload = {"email": "user@sjvair.com"}
    #     request = self.factory.post(url, payload, content_type="application/json")
    #     response = password_reset(request)
    #     get_response_data(response)

    #     assert response.status_code == 200
    #     assert len(mail.outbox) == 1

    # def test_reset_password_confirm(self):
    #     """
    #     Ensure a user can reset password using the code
    #     """
    #     code = "123456"
    #     cache_key = f"pwr|user:user@sjvair.com"
    #     cache.set(cache_key, code, 60 * 30)
    #     url = reverse("api:v1:password-reset-confirm")
    #     payload = {
    #         "email": "user@sjvair.com",
    #         "code": "123456",
    #         "password": "test11user",
    #     }
    #     request = self.factory.post(url, payload, content_type="application/json")
    #     response = password_reset_confirm(request)
    #     data = get_response_data(response)

    #     assert response.status_code == 200
    #     assert data["message"] == "Password successfully updated."

    # def test_reset_password_invalid_code(self):
    #     """
    #     Ensure a user can't reset a password using an invalid code
    #     """
    #     code = "123456"
    #     cache_key = f"pwr|user:user@sjvair.com"
    #     cache.set(cache_key, code, 60 * 30)
    #     url = reverse("api:v1:password-reset-confirm")
    #     payload = {
    #         "email": "user@sjvair.com",
    #         "code": "987654",
    #         "password": "test11user",
    #     }
    #     request = self.factory.post(url, payload, content_type="application/json")
    #     response = password_reset_confirm(request)
    #     data = get_response_data(response)

    #     assert response.status_code == 400
    #     assert data["errors"]["__all__"][0]["code"] == "invalid_code"

    # def test_reset_password_invalid_email(self):
    #     """
    #     Ensure a user can't reset a password using an invalid code
    #     """
    #     code = "123456"
    #     cache_key = f"pwr|user:user@sjvair.com"
    #     cache.set(cache_key, code, 60 * 30)
    #     url = reverse("api:v1:password-reset-confirm")
    #     payload = {
    #         "email": "notauser@sjvair.com",
    #         "code": code,
    #         "password": "test11user",
    #     }
    #     request = self.factory.post(url, payload, content_type="application/json")
    #     response = password_reset_confirm(request)
    #     data = get_response_data(response)

    #     assert response.status_code == 400
    #     assert data["errors"]["__all__"][0]["code"] == "invalid_email"

    # def test_reset_password_blank_email(self):
    #     """
    #     Ensure a user can't reset a password using an invalid code
    #     """
    #     code = "123456"
    #     cache_key = f"pwr|user:user@sjvair.com"
    #     cache.set(cache_key, code, 60 * 30)
    #     url = reverse("api:v1:password-reset-confirm")
    #     payload = {
    #         "email": "",
    #         "code": code,
    #         "password": "test11user",
    #     }
    #     request = self.factory.post(url, payload, content_type="application/json")
    #     response = password_reset_confirm(request)
    #     data = get_response_data(response)

    #     assert response.status_code == 400
    #     assert data["errors"]["__all__"][0]["code"] == "missing_email"

    # def test_reset_password_too_common(self):
    #     """
    #     Ensure a user can't reset a password using common password
    #     """
    #     code = "123456"
    #     cache_key = f"pwr|user:user@sjvair.com"
    #     cache.set(cache_key, code, 60 * 30)
    #     url = reverse("api:v1:password-reset-confirm")
    #     payload = {
    #         "email": "user@sjvair.com",
    #         "code": code,
    #         "password": "password",
    #     }
    #     request = self.factory.post(url, payload, content_type="application/json")
    #     response = password_reset_confirm(request)
    #     data = get_response_data(response)

    #     assert response.status_code == 400
    #     assert data["errors"]["password"][0]["code"] == "password_too_common"

    # def test_reset_password_too_similar(self):
    #     """
    #     Ensure a user can't reset a password using common password
    #     """
    #     code = "123456"
    #     cache_key = f"pwr|user:user@sjvair.com"
    #     cache.set(cache_key, code, 60 * 30)
    #     url = reverse("api:v1:password-reset-confirm")
    #     payload = {
    #         "email": "user@sjvair.com",
    #         "code": code,
    #         "password": "user@sjvair.com",
    #     }
    #     request = self.factory.post(url, payload, content_type="application/json")
    #     response = password_reset_confirm(request)
    #     data = get_response_data(response)

    #     assert response.status_code == 400
    #     assert data["errors"]["password"][0]["code"] == "password_too_similar"
