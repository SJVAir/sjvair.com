from django import forms
from django.contrib.auth import forms as auth_forms
from django.core.cache import cache
from django.utils.translation import ugettext_lazy as _

from .models import User


class ProfileForm(forms.ModelForm):
    class Meta:
        fields = ('full_name', 'email', 'phone')
        model = User

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['phone'].required = True


class UserCreationForm(forms.ModelForm):
    error_messages = {
        'duplicate_email': _("A user with that email address already exists."),
        'password_mismatch': _("The two password fields didn't match."),
    }
    password1 = forms.CharField(label=_('Password'), widget=forms.PasswordInput)
    password2 = forms.CharField(label=_('Password confirmation'),
        widget=forms.PasswordInput,
        help_text=_('Enter the same password as above, for verification.'))

    class Meta:
        model = User
        fields = ('full_name', 'email', 'phone')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['phone'].required = True

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data['email'])
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(self.error_messages['duplicate_email'])
        return email

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

# UserCreationForm.base_fields.keyOrder = [
#     'email', 'full_name', 'password1', 'password2',
# ]


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
    CODE_EXPIRES = 5 # Number of minutes until the code expires

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user')
        super().__init__(*args, **kwargs)

    def clean(self):
        self.check_rate_limit()
        return self.cleaned_data

    def check_rate_limit(self):
        cache_key = self.user.verify_phone_rate_limit_key
        if cache.get(cache_key):
            error = 'You have recently been sent a verification code. Please try again shortly.'
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
        cached_code = cache.get(self.user.verify_phone_code_key)

        if code != cached_code:
            raise forms.ValidationError('Invalid code, please try again.')

        return code

