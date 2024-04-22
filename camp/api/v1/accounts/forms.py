import re

from django import forms
from django.contrib.auth import authenticate, password_validation
from django.contrib.auth.tokens import default_token_generator as token_generator
from django.core.cache import cache
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils.translation import gettext as _

from phonenumber_field.formfields import PhoneNumberField
from phonenumber_field.validators import validate_international_phonenumber
from phonenumber_field.widgets import RegionalPhoneNumberWidget
from resticus.auth import TokenAuth

from camp.apps.accounts.models import User


class UserForm(forms.ModelForm):
    password = forms.CharField(strip=False, widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ("full_name", "email", "phone", "password")

    def clean_password(self):
        password = self.cleaned_data.get("password")
        if password:
            try:
                password_validation.validate_password(password, user=self.instance)
            except forms.ValidationError as error:
                self.add_error("password", error)
        return password

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data.get("email"))
        if email.endswith(".con"):
            raise forms.ValidationError(
                "Did you mean .com?", code="invalid_email_domain",
            )
        return email

    def create_token(self, user):
        TokenModel = TokenAuth.get_token_model()
        token, created = TokenModel.objects.get_or_create(user=user)
        return token

    def save(self, *args, **kwargs):
        commit = kwargs.pop('commit', True)
        user = super().save(commit=False, *args, **kwargs)
        password = self.cleaned_data.get("password")
        if password:
            user.set_password(password)
        if commit:
            is_created = user._state.adding
            user.save()
            if is_created:
                self.create_token(user)
                user.send_phone_verification_code()
        return user


class SendPhoneVerificationForm(forms.Form):
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user')
        super().__init__(*args, **kwargs)

    def clean(self):
        self.check_rate_limit()
        return self.cleaned_data

    def check_rate_limit(self):
        if self.user.check_phone_verification_rate_limit():
            error = _('You have recently been sent a verification code. Please try again in a few minutes.')
            raise forms.ValidationError(error)
        self.user.set_phone_verification_rate_limit()


class PhoneVerificationMixin(forms.Form):
    code = forms.CharField(
        label=_('Verification code'),
        help_text=_("Check your phone for a verification text from SJVAir."),
        max_length=6,
        min_length=6
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user')
        super().__init__(*args, **kwargs)

    def clean_code(self):
        code = self.cleaned_data.get('code')
        verified = self.user.check_phone_verification_code(code)
        if not verified:
            raise forms.ValidationError(_('Invalid verification code, please try again.'))
        return code


class ConfirmPhoneVerificationForm(PhoneVerificationMixin, forms.Form):
    def save(self):
        self.user.phone_verified = True
        self.user.save()
        cache.delete(self.user.phone_verification_code_key)
        cache.delete(self.user.phone_verification_rate_limit_key)
        return self.user


class PasswordResetForm(forms.Form):
    phone = PhoneNumberField(
        label=_('Phone number'),
        widget=RegionalPhoneNumberWidget(attrs={
            "autocomplete": "phone"
        })
    )

    def clean_phone(self):
        phone = self.cleaned_data['phone']
        self.user = self.get_user(phone)
        if self.user is not None:
            if self.user.check_phone_verification_rate_limit():
                error = _('You have recently been sent a verification code. Please try again in a few minutes.')
                raise forms.ValidationError(error)
            self.user.set_phone_verification_rate_limit()
        return phone

    def get_user(self, phone):
        try:
            return User.objects.get(
                phone=phone,
                is_active=True,
            )
        except User.DoesNotExist:
            return None
        
    def save(self, **opts):
        if self.user:
            self.user.send_phone_verification_code()
            return {
                'uidb64': urlsafe_base64_encode(force_bytes(self.user.pk)),
                'token': token_generator.make_token(self.user),
            }
