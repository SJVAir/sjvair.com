import json
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase, RequestFactory
from django.urls import reverse

import pytest

from camp.apps.accounts.backends import AuthenticationBackend
from camp.apps.accounts.models import User
from camp.utils.test import debug, get_response_data

from . import endpoints, forms

client = Client()

login = endpoints.LoginEndpoint.as_view()
register = endpoints.RegisterEndpoint.as_view()
user_detail = endpoints.UserDetail.as_view()
change_password = endpoints.ChangePasswordEndpoint.as_view()
password_reset = endpoints.PasswordResetEndpoint.as_view()
password_reset_confirm = endpoints.PasswordResetConfirmEndpoint.as_view()
send_phone_verification = endpoints.SendPhoneVerificationEndpoint.as_view()
confirm_phone_verification = endpoints.ConfirmPhoneVerificationEndpoint.as_view()


class AuthenticationTests(TestCase):
    fixtures = ['users']

    def setUp(self):
        self.user = User.objects.get(email="user@sjvair.com")
        self.factory = RequestFactory()

    def tearDown(self):
        cache.clear()
        return super().tearDown()

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
        }
        request = self.factory.post(url, payload, content_type="application/json")
        response = register(request)
        data = get_response_data(response)

        # Assert we got a valid status code and the correct response data.
        assert response.status_code == 201
        assert "api_token" in data["data"]
        assert data['data']['api_token'] is not None
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
            "phone": "661-555-5555",
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
        self.user.phone_verified = False
        self.user.save()

        url = reverse("api:v1:account:phone-verify-send")
        request = self.factory.post(url)
        request.user = self.user
        response = send_phone_verification(request)
        data = get_response_data(response)

        assert response.status_code == 204
        assert send_sms_message.called

    @patch("camp.apps.accounts.tasks.send_sms_message")
    def test_validate_phone_confirm(self, send_sms_message):
        """
        Ensure a user can validate their phone number with the code
        """
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

    @patch("camp.apps.accounts.tasks.send_sms_message")
    def test_get_password_reset_code(self, send_sms_message):
        """
        Ensure a user can request a reset password code
        """
        url = reverse("api:v1:account:password-reset")
        payload = {"phone": "559-555-5555"}
        request = self.factory.post(url, payload, content_type="application/json")
        response = password_reset(request)
        data = get_response_data(response)

        assert response.status_code == 200
        assert data.get('data') and data['data'].get('token')

    @patch("camp.apps.accounts.tasks.send_sms_message")
    def test_reset_password_confirm(self, send_sms_message):
        """
        Ensure a user can reset password using the code
        """

        form = forms.PasswordResetForm({'phone': self.user.phone})
        assert form.is_valid()
        options = form.save()
        code = cache.get(self.user.phone_verification_code_key)

        url = reverse('api:v1:account:password-reset-confirm', kwargs=options)
        payload = {
            'code': code,
            'new_password1': 'test11user',
            'new_password2': 'test11user',
        }
        request = self.factory.post(url, payload, content_type="application/json")
        response = password_reset_confirm(request=request, **options)
        data = get_response_data(response)

        assert response.status_code == 204

    @patch("camp.apps.accounts.tasks.send_sms_message")
    def test_reset_password_invalid_code(self, send_sms_message):
        """
        Ensure a user can't reset a password using an invalid code
        """
        form = forms.PasswordResetForm({'phone': self.user.phone})
        assert form.is_valid()
        options = form.save()

        # Manually override the verification code.
        cache.set(self.user.phone_verification_code_key, '111111', 30)

        url = reverse('api:v1:account:password-reset-confirm', kwargs=options)
        payload = {
            'code': '123456', # Not the same as above!
            'new_password1': 'test11user',
            'new_password2': 'test11user',
        }
        request = self.factory.post(url, payload, content_type="application/json")
        response = password_reset_confirm(request=request, **options)
        data = get_response_data(response)

        assert response.status_code == 400
        assert data['errors']['code'][0]['code'] == 'invalid_code'

    @patch("camp.apps.accounts.tasks.send_sms_message")
    def test_reset_password_too_common(self, send_sms_message):
        """
        Ensure a user can't reset a password using common password
        """
        form = forms.PasswordResetForm({'phone': self.user.phone})
        assert form.is_valid()
        options = form.save()
        code = cache.get(self.user.phone_verification_code_key)

        url = reverse('api:v1:account:password-reset-confirm', kwargs=options)
        payload = {
            'code': code,
            'new_password1': 'password',
            'new_password2': 'password',
        }
        request = self.factory.post(url, payload, content_type="application/json")
        response = password_reset_confirm(request=request, **options)
        data = get_response_data(response)

        assert response.status_code == 400
        assert data['errors']['new_password2'][0]['code'] == 'password_too_common'

    @patch("camp.apps.accounts.tasks.send_sms_message")
    def test_reset_password_too_similar(self, send_sms_message):
        """
        Ensure a user can't set their password to their email
        """
        form = forms.PasswordResetForm({'phone': self.user.phone})
        assert form.is_valid()
        options = form.save()
        code = cache.get(self.user.phone_verification_code_key)

        url = reverse('api:v1:account:password-reset-confirm', kwargs=options)
        payload = {
            'code': code,
            'new_password1': str(self.user.email),
            'new_password2': str(self.user.email),
        }
        request = self.factory.post(url, payload, content_type="application/json")
        response = password_reset_confirm(request=request, **options)
        data = get_response_data(response)

        assert response.status_code == 400
        assert data['errors']['new_password2'][0]['code'] == 'password_too_similar'

    def test_update_user(self):
        url = reverse('api:v1:account:user-detail')
        payload = {"full_name": "Updated User"}
        request = self.factory.patch(url, payload, content_type='application/json')
        request.user = self.user
        response = user_detail(request)

        data = get_response_data(response)
        assert response.status_code == 200
        user = User.objects.get(pk=self.user.pk)
        assert user.full_name == payload['full_name'] == data['data']['full_name']

    def test_change_password(self):
        url = reverse('api:v1:account:change-password')
        payload = {
            'old_password': 'letmein',
            'new_password1': 't0kenize th!s',
            'new_password2': 't0kenize th!s',
        }
        request = self.factory.put(url, payload, content_type='application/json')
        request.user = self.user
        response = change_password(request)
        data = get_response_data(response)

        # We should have a success response
        assert response.status_code == 200

        # The password should be updated.
        user = User.objects.get(pk=self.user.pk)
        assert user.check_password(payload['old_password']) is False
        assert user.check_password(payload['new_password1']) is True

    def test_change_password_invalid_password(self):
        url = reverse('api:v1:account:change-password')
        payload = {
            'old_password': 'lol nope',
            'new_password1': 't0kenize th!s',
            'new_password2': 't0kenize th!s',
        }
        request = self.factory.put(url, payload, content_type='application/json')
        request.user = self.user
        response = change_password(request)
        data = get_response_data(response)

        # We should have an error response
        assert response.status_code == 400

        # The password should remain unchanged.
        user = User.objects.get(pk=self.user.pk)
        assert user.check_password('letmein') is True
        assert user.check_password(payload['new_password1']) is False

    def test_delete_user(self):
        url = reverse('api:v1:account:user-detail')
        payload = {'password': 'letmein'}
        request = self.factory.delete(url, payload, content_type='application/json')
        request.user = self.user
        response = user_detail(request)
        data = get_response_data(response)

        # We should have an error response
        assert response.status_code == 204

        # The user should be deleted
        with pytest.raises(User.DoesNotExist):
            user = User.objects.get(pk=self.user.pk)

    def test_delete_user_incorrect_password(self):
        url = reverse('api:v1:account:user-detail')
        payload = {'password': 'lol nope'}
        request = self.factory.delete(url, payload, content_type='application/json')
        request.user = self.user
        response = user_detail(request)
        data = get_response_data(response)

        # We should have an error response
        assert response.status_code == 400

        # The user should not be deleted
        assert User.objects.filter(pk=self.user.pk).exists()

