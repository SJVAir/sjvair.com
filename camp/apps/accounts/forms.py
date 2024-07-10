from django import forms
from django.contrib.auth import authenticate, forms as auth_forms, password_validation
from django.contrib.auth.tokens import default_token_generator as token_generator
from django.core import validators
from django.core.cache import cache
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils.translation import gettext_lazy as _

from django_recaptcha.fields import ReCaptchaField
from django_recaptcha.widgets import ReCaptchaV2Checkbox
from phonenumber_field.formfields import PhoneNumberField
from phonenumber_field.validators import validate_international_phonenumber
from phonenumber_field.widgets import RegionalPhoneNumberWidget

from .models import User


def phone_or_email_validator(value):
    '''
        Validate that a value is either an email address or phone number.
    '''
    try:
        validators.validate_email(value)
    except validators.ValidationError:
        try:
            validate_international_phonenumber(value)
        except (TypeError, validators.ValidationError):
            raise validators.ValidationError('Invalid email address or phone number')


class AuthenticationForm(forms.Form):
    identifier = forms.CharField(
        label=_("Email or Phone"),
        help_text=_("You can login with your email address or phone number."),
        validators=[phone_or_email_validator],
    )
    password = forms.CharField(strip=False, widget=forms.PasswordInput)

    error_messages = {
        "invalid_login": _(
            "Please enter a correct email/phone and password. Note that both fields may be case-sensitive."
        ),
        "inactive": _("This account is inactive."),
    }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)

    def clean(self):
        identifier = self.cleaned_data.get("identifier")
        password = self.cleaned_data.get("password")

        if identifier is not None and password:
            self.user = authenticate(
                request=self.request, identifier=identifier, password=password
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

    def get_user(self):
        return self.user


class ProfileForm(forms.ModelForm):
    error_messages = {
        'duplicate_email': _("A user with that email address already exists."),
        'duplicate_phone': _("A user with that phone number already exists."),
    }

    class Meta:
        fields = ('full_name', 'email', 'phone', 'language')
        model = User

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data['email'])

        if email:
            queryset = User.objects.filter(email__iexact=email)
            if self.instance:
                queryset = queryset.exclude(pk=self.instance.pk)

            if queryset.exists():
                raise forms.ValidationError(self.error_messages['duplicate_email'])

        return email or None

    def clean_phone(self):
        phone = self.cleaned_data['phone']

        queryset = User.objects.filter(phone=phone)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise forms.ValidationError(self.error_messages['duplicate_phone'])

        return phone


class UserCreationForm(forms.ModelForm):
    error_messages = {
        'duplicate_email': _("A user with that email address already exists."),
        'duplicate_phone': _("A user with that phone number already exists."),
        'password_mismatch': _("The two password fields didn't match."),
    }

    password1 = forms.CharField(
        label=_('Password'),
        help_text=password_validation.password_validators_help_text_html(),
        widget=forms.PasswordInput,
    )

    password2 = forms.CharField(
        label=_('Password confirmation'),
        help_text=_('Enter the same password as before, for verification.'),
        widget=forms.PasswordInput,
    )

    captcha = ReCaptchaField(label='')

    class Meta:
        model = User
        fields = ('full_name', 'phone', 'email', 'language')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data['email'])
        if email and User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(self.error_messages['duplicate_email'])
        return email or None

    def clean_phone(self):
        phone = self.cleaned_data['phone']
        if User.objects.filter(phone=phone).exists():
            raise forms.ValidationError(self.error_messages['duplicate_phone'])
        return phone

        def clean_password(self):
            password = self.cleaned_data['password']
            try:
                password_validation.validate_password(password)
            except forms.ValidationError as error:
                self.add_error("password", error)

    def clean_password2(self):
        password1 = self.cleaned_data.get('password1')
        password2 = self.cleaned_data.get('password2')
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError(self.error_messages['password_mismatch'])
        return password2

    def save(self, **params):
        user = super(UserCreationForm, self).save(commit=False)
        for key, value in params.items():
            setattr(user, key, value)
        user.set_password(self.cleaned_data['password1'])
        user.save()
        return user


class UserChangeForm(forms.ModelForm):
    password = auth_forms.ReadOnlyPasswordHashField(label=_("Password"),
        help_text=_("Raw passwords are not stored, so there is no way to see "
                    "this user's password, but you can change the password "
                    "using <a href=\"password/\">this form</a>."))

    class Meta:
        fields = ('full_name', 'email', 'phone', 'password')
        model = User

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        f = self.fields.get('user_permissions', None)
        if f is not None:
            f.queryset = f.queryset.select_related('content_type')

    def clean_password(self):
        # Regardless of what the user provides, return the initial value.
        # This is done here, rather than on the field, because the
        # field does not have access to the initial value
        return self.initial['password']


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


class PhoneVerificationCodeForm(forms.Form):
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
            raise forms.ValidationError(_('Invalid verification code, please try again.'))
        return code


class SubmitPhoneVerificationForm(PhoneVerificationCodeForm, forms.Form):
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user')
        super().__init__(*args, **kwargs)


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


class SetPasswordForm(PhoneVerificationCodeForm, auth_forms.SetPasswordForm):
    def save(self, *args, **kwargs):
        # The user has defacto verified their phone number, so mark it.
        self.user.phone_verified = True
        return super().save(*args, **kwargs)
