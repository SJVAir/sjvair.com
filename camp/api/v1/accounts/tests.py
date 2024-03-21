import json
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.test import Client
from django.test import TestCase, RequestFactory
from django.urls import reverse

from camp.apps.accounts.backends import AuthenticationBackend
from camp.apps.accounts.models import User
from camp.utils.test import get_response_data

from . import endpoints

client = Client()

login = endpoints.LoginEndpoint.as_view()
register = endpoints.RegisterEndpoint.as_view()
password_reset = endpoints.PasswordResetEndpoint.as_view()
password_reset_confirm = endpoints.PasswordResetConfirmEndpoint.as_view()
phone_validation = endpoints.PhoneValidationEndpoint.as_view()
phone_validation_confirm = endpoints.PhoneValidationConfirmEndpoint.as_view()


class AuthenticationTests(TestCase):
    fixtures = ['users']

    def setUp(self):
        self.user = User.objects.get(email="user@sjvair.com")
        self.factory = RequestFactory()
        self.login_url = reverse("api:v1:account:login")
        self.register_url = reverse("api:v1:account:register")

    def test_authentication_backend(self):
        backend = AuthenticationBackend()
        request = self.factory.post(
            self.login_url,
            {"email": "user@sjvair.com", "password": "letmein"},
            content_type="application/json",
        )
        user = backend.authenticate(
            request=request, email=self.user.email, password="letmein",
        )
        import code
        code.interact(local=locals())
        assert user is not None
        assert user.pk == self.user.pk

    # def test_valid_login(self):
    #     request = self.factory.post(
    #         self.login_url,
    #         {"email": "user@sjvair.com", "password": "letmein"},
    #         content_type="application/json",
    #     )
    #     response = login(request)
    #     data = json.loads(response.content)

    #     assert response.status_code == 200
    #     assert "api_token" in data["data"]
    #     assert "id" in data["data"]
    #     assert data["data"]["id"] == str(self.user.pk)

    # def test_invalid_login(self):
    #     request = self.factory.post(
    #         self.login_url,
    #         {"email": "user@sjvair.com", "password": "lolnope"},
    #         content_type="application/json",
    #     )
    #     response = login(request)
    #     data = json.loads(response.content)

    #     assert response.status_code == 401
    #     assert "errors" in data

    # @patch("camp.apps.accounts.tasks.send_sms_message")
    # def test_validate_phone(self, mock_send_sms_message):
    #     self.user.phone = "+15595555555"
    #     self.user.save()

    #     url = reverse(
    #         "api:v1:phone-validation",
    #         kwargs={"user_id": self.user.pk},
    #     )
    #     request = self.factory.get(url)
    #     request.user = self.user
    #     response = phone_validation(
    #         request, user_id=self.user.pk
    #     )

    #     assert response.status_code == 200
    #     assert mock_send_sms_message.called

    # def test_register_new_user(self):
    #     payload = {
    #         "full_name": "Alice Test",
    #         "email": "alice.test@sjvair.com",
    #         "phone": "+15595555555",
    #         "password": "t0kenize th!s",
    #         "confirm_password": "t0kenize th!s",
    #     }
    #     request = self.factory.post(
    #         self.register_url, payload, content_type="application/json"
    #     )
    #     response = register(request)
    #     data = json.loads(response.content)

    #     assert response.status_code == 201
    #     assert "api_token" in data["data"]
    #     assert "id" in data["data"]
    #     assert data["data"]["email"] == payload["email"]

    #     user = User.objects.get(pk=data["data"]["id"])
    #     assert user.check_password(payload["password"])
    #     assert user.role == Role.ROLES.user

    # def test_validate_phone_confirm(self):
    #     """
    #     Ensure a user can validate their phone number with the code
    #     """
    #     code = "123456"
    #     cache_key = f"phv|user:+15005550006"
    #     cache.set(cache_key, code, 60 * 15)
    #     url = reverse("api:v1:phone-validation-confirm")
    #     payload = {"code": "123456"}
    #     request = self.factory.post(url, payload, content_type="application/json")
    #     response = phone_validation_confirm(request)
    #     data = json.loads(response.content)

    #     assert response.status_code == 200
    #     assert data["message"] == "Phone number was successfully confirmed."

    # def test_register_invalid_password(self):
    #     payload = {
    #         "full_name": "Bob Test",
    #         "email": "bob.test@sjvair.com",
    #         "password": "password",
    #     }
    #     request = self.factory.post(
    #         self.register_url, payload, content_type="application/json"
    #     )
    #     response = register(request)
    #     data = json.loads(response.content)

    #     assert response.status_code == 400
    #     assert data["errors"]["password"][0]["code"] == "password_too_common"

    # def test_register_duplicate_email(self):
    #     payload = {
    #         "full_name": "Duplicate User",
    #         "email": "user@sjvair.com",
    #         "password": "t0kenize th!s",
    #         "confirm_password": "t0kenize th!s",
    #     }
    #     request = self.factory.post(
    #         self.register_url, payload, content_type="application/json"
    #     )
    #     response = register(request)
    #     data = json.loads(response.content)

    #     assert response.status_code == 400
    #     assert data["errors"]["email"][0]["code"] == "duplicate_email"

    # def test_register_duplicate_email_case_sensitive(self):
    #     payload = {
    #         "full_name": "Duplicate User",
    #         "email": "User@sjvair.com",
    #         "password": "t0kenize th!s",
    #         "confirm_password": "t0kenize th!s",
    #     }
    #     request = self.factory.post(
    #         self.register_url, payload, content_type="application/json"
    #     )
    #     response = register(request)
    #     data = json.loads(response.content)

    #     assert response.status_code == 400
    #     assert data["errors"]["email"][0]["code"] == "duplicate_email"

    # def test_register_invalid_email_domain(self):
    #     """
    #     Ensure that the form raises an error if a user tries to register an email with invalid domain
    #     """
    #     payload = {
    #         "full_name": "InvalidEmail User",
    #         "email": "invalidemail@sjvair.con",
    #         "password": "t0kenize th!s",
    #         "confirm_password": "t0kenize th!s",
    #     }
    #     request = self.factory.post(
    #         self.register_url, payload, content_type="application/json"
    #     )
    #     response = register(request)
    #     data = json.loads(response.content)

    #     assert response.status_code == 400
    #     assert data["errors"]["email"][0]["code"] == "invalid_email_domain"

    # def test_get_password_reset_code(self):
    #     """
    #     Ensure a user can request a reset password code
    #     """
    #     url = reverse("api:v1:password-reset")
    #     payload = {"email": "user@sjvair.com"}
    #     request = self.factory.post(url, payload, content_type="application/json")
    #     response = password_reset(request)
    #     json.loads(response.content)

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
    #     data = json.loads(response.content)

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
    #     data = json.loads(response.content)

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
    #     data = json.loads(response.content)

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
    #     data = json.loads(response.content)

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
    #     data = json.loads(response.content)

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
    #     data = json.loads(response.content)

    #     assert response.status_code == 400
    #     assert data["errors"]["password"][0]["code"] == "password_too_similar"
