from django import forms
from django.contrib.auth import authenticate, forms as auth_forms
from django.core import validators
from django.core.cache import cache
from django.utils.translation import gettext_lazy as _

from phonenumber_field.validators import validate_international_phonenumber

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
        
        queryset = User.objects.filter(email__iexact=email)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        
        if queryset.exists():
            raise forms.ValidationError(self.error_messages['duplicate_email'])

        return email

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
    password1 = forms.CharField(label=_('Password'), widget=forms.PasswordInput)
    password2 = forms.CharField(label=_('Password confirmation'),
        widget=forms.PasswordInput,
        help_text=_('Enter the same password as above, for verification.'))

    class Meta:
        model = User
        fields = ('full_name', 'phone', 'email', 'language')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data['email'])
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(self.error_messages['duplicate_email'])
        return email

    def clean_phone(self):
        phone = self.cleaned_data['phone']
        if User.objects.filter(phone=phone).exists():
            raise forms.ValidationError(self.error_messages['duplicate_phone'])
        return phone

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
    RATE_LIMIT = 2  # Number of minutes between sending
    CODE_EXPIRES = 5  # Number of minutes until the code expires

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user')
        super().__init__(*args, **kwargs)

    def clean(self):
        self.check_rate_limit()
        return self.cleaned_data

    def check_rate_limit(self):
        cache_key = self.user.phone_verification_rate_limit_key
        if cache.get(cache_key):
            error = _('You have recently been sent a verification code. Please try again shortly.')
            raise forms.ValidationError(error)
        cache.set(cache_key, True, self.RATE_LIMIT * 60)


class SubmitPhoneVerificationForm(forms.Form):
    CODE_EXPIRES = SendPhoneVerificationForm.CODE_EXPIRES # hack

    code = forms.CharField(max_length=4, min_length=4)

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user')
        super().__init__(*args, **kwargs)

    def clean_code(self):
        code = self.cleaned_data.get('code')
        verified = self.user.check_phone_verification_code(code)
        if not verified:
            raise forms.ValidationError(_('Invalid verification code, please try again.'))

        return code

