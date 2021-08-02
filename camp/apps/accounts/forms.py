from django import forms
from django.contrib.auth import forms as auth_forms
from django.utils.translation import ugettext_lazy as _

from .models import User


class ProfileForm(forms.ModelForm):
    class Meta:
        fields = ('full_name', 'email', 'phone')
        model = User


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
        fields = ('email', 'full_name', 'phone')

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
        fields = ('email', 'full_name', 'password')
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


class PhoneVerificationForm(forms.Form):
    code = forms.CharField(max_length=4, min_length=4)
