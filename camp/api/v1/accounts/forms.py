import re

from django import forms
from django.contrib.auth import authenticate, forms as auth_forms, password_validation
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
    error_messages = {
        'duplicate_email': _("A user with that email address already exists."),
        'duplicate_phone': _("A user with that phone number already exists."),
        'invalid_email_domain': _("Did you mean .com?"),
    }

    class Meta:
        model = User
        fields = ["full_name", "email", "phone"]

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data['email'])

        if email:
            # Check for common .com typo
            if email.endswith(".con"):
                raise forms.ValidationError(
                    self.errors['invalid_email_domain'],
                    code='invalid_email_domain'
                )

            # Check for duplicate email
            queryset = User.objects.filter(email__iexact=email)
            if self.instance:
                queryset = queryset.exclude(pk=self.instance.pk)

            if queryset.exists():
                raise forms.ValidationError(
                    self.error_messages['duplicate_email'],
                    code='duplicate_email'
                )

        return email or None

    def clean_phone(self):
        phone = self.cleaned_data['phone']

        # Check for duplicate phone
        queryset = User.objects.filter(phone=phone)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise forms.ValidationError(
                self.error_messages['duplicate_phone'],
                code='duplicate_phone'
            )

        return phone

    def save(self, *args, **kwargs):
        commit = kwargs.pop('commit', True)
        user = super().save(commit=False, *args, **kwargs)
        if commit:
            user.save()
        return user


class UserRegistrationForm(UserForm):
    password = forms.CharField(strip=False, widget=forms.PasswordInput, required=True)

    class Meta(UserForm.Meta):
        fields = UserForm.Meta.fields + ['password']

    def clean_password(self):
        password = self.cleaned_data.get("password")
        if password:
            password_validation.validate_password(password, user=self.instance)
        return password

    def save(self, *args, **kwargs):
        commit = kwargs.pop('commit', True)
        user = super().save(commit=False, *args, **kwargs)
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
            user.send_phone_verification_code()
        return user



class PasswordRequiredActionForm(forms.Form):
    error_messages = {
        "password_incorrect": _(
            "Your password was entered incorrectly. Please try again."
        )
    }

    password = forms.CharField(strip=False, widget=forms.PasswordInput, required=True)

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user')
        super().__init__(*args, **kwargs)

    def clean_password(self):
        password = self.cleaned_data['password']
        if not self.user.check_password(password):
            raise forms.ValidationError(
                self.error_messages['password_incorrect'],
                code='password_incorrect'
            )


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


class PhoneVerificationForm(forms.Form):
    code = forms.CharField(
        label=_('Verification code'),
        help_text=_("Check your phone for a verification text from SJVAir."),
        max_length=6,
        min_length=6
    )

    def clean_code(self):
        code = self.cleaned_data.get('code')
        verified = self.user.check_phone_verification_code(code)
        if not verified:
            raise forms.ValidationError(_('Invalid verification code, please try again.'), code='invalid_code')
        return code


class ConfirmPhoneVerificationForm(PhoneVerificationForm):
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user')
        super().__init__(*args, **kwargs)

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
            return User.objects.get(phone=phone, is_active=True)
        except User.DoesNotExist:
            return None
        
    def save(self, **opts):
        if self.user:
            self.user.send_phone_verification_code()
            return {
                'uidb64': urlsafe_base64_encode(force_bytes(self.user.pk)),
                'token': token_generator.make_token(self.user),
            }


class SetPasswordForm(PhoneVerificationForm, auth_forms.SetPasswordForm):
    def save(self, *args, **kwargs):
        # The user has defacto verified their phone number, so mark it.
        self.user.phone_verified = True
        return super().save(*args, **kwargs)
