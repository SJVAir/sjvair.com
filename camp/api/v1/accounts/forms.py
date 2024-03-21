import re

from django import forms
from django.contrib.auth import authenticate, password_validation
from django.core.cache import cache
from django.utils.translation import gettext as _

from camp.apps.accounts.models import User


class UserForm(forms.ModelForm):
    """
    A simple user form that does not include any tenant logic
    """

    password = forms.CharField(strip=False, widget=forms.PasswordInput,)

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

    def save(self, *args, **kwargs):
        commit = kwargs.pop('commit', True)
        user = super().save(commit=False, *args, **kwargs)
        password = self.cleaned_data.get("password")
        if password:
            user.set_password(password)
        if commit:
            user.save()
        return user


class PasswordResetForm(forms.Form):
    email = forms.EmailField()
    code = forms.RegexField(regex=re.compile(r"^[0-9]{6}$"))
    password = forms.CharField(strip=False, widget=forms.PasswordInput)

    error_messages = {
        "invalid_email": _("Please enter a valid email address."),
        "missing_email": _("Email address is required."),
        "invalid_code": _("Password reset code is not valid or has expired."),
    }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = self.data.get("email")
        if not email:
            raise forms.ValidationError(
                self.error_messages["missing_email"], code="missing_email",
            )

        email = User.objects.normalize_email(email)
        if not self.request.tenant.users.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                self.error_messages["invalid_email"], code="invalid_email",
            )
        return email

    def clean(self):
        self.cache_key = (
            f"pwr|tenant:{self.request.tenant.pk}|user:{self.clean_email()}"
        )
        submitted_code = self.cleaned_data.get("code", None)
        cached_code = cache.get(self.cache_key)

        if cached_code is None or cached_code != submitted_code:
            raise forms.ValidationError(
                self.error_messages["invalid_code"], code="invalid_code",
            )

        password = self.cleaned_data.get("password")
        email = self.cleaned_data.get("email")
        if email and password:
            user = self.request.tenant.users.get(email__iexact=email)
            try:
                password_validation.validate_password(password, user=user)
            except forms.ValidationError as error:
                self.add_error("password", error)

    def save(self, commit=True):
        cache.delete(self.cache_key)
        user = self.request.tenant.users.get(email__iexact=self.cleaned_data["email"])
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user


class LoginForm(forms.Form):
    email = forms.EmailField()
    password = forms.CharField(strip=False, widget=forms.PasswordInput)

    error_messages = {
        "invalid_login": _(
            "Please enter a correct email and password. Note that both fields may be case-sensitive."
        ),
        "inactive": _("This account is inactive."),
    }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)

    def clean(self):
        email = self.cleaned_data.get("email")
        password = self.cleaned_data.get("password")

        if email is not None and password:

            self.user = authenticate(
                request=self.request, email=email, password=password
            )

            if self.user is None:
                raise forms.ValidationError(
                    self.error_messages["invalid_login"], code="invalid_login",
                )

            elif not self.user.is_active:
                raise forms.ValidationError(
                    self.error_messages["inactive"], code="inactive",
                )

        return self.cleaned_data


class PhoneVerificatonForm(forms.Form):
    code = forms.RegexField(regex=re.compile(r"^[0-9]{6}$"))
    error_messages = {
        "invalid_code": _("Phone verification code is not valid or has expired."),
    }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

    def clean(self):
        self.cache_key = f"phv|tenant:{self.request.tenant.pk}|user:{self.user.phone}"
        submitted_code = self.cleaned_data.get("code", None)
        cached_code = cache.get(self.cache_key)

        if cached_code is None or cached_code != submitted_code:
            raise forms.ValidationError(
                self.error_messages["invalid_code"], code="invalid_code",
            )

    def save(self, commit=True):
        cache.delete(self.cache_key)
        self.user.phone_validated = True
        if commit:
            self.user.save()

        reward_program = self.user.tenant.reward_programs.filter(
            is_enabled=True
        ).first()
        if reward_program and reward_program.rewards_type == "square_loyalty":
            self.user.tenant.pos().get_or_create_loyalty_account(
                self.user, reward_program
            )

        return self.user
