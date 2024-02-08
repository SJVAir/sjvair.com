from django.contrib.auth import authenticate, login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.shortcuts import redirect
from django.urls import reverse_lazy

import vanilla

from .forms import (UserCreationForm, ProfileForm,
    SendPhoneVerificationForm, SubmitPhoneVerificationForm)
from camp.utils.views import RedirectViewMixin


class SignupView(RedirectViewMixin, vanilla.CreateView):
    template_name = 'registration/signup.html'
    form_class = UserCreationForm
    redirect_field_name = 'next'
    success_url = reverse_lazy('account:phone-verify-submit')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context[self.redirect_field_name] = self.get_redirect_url()
        return context

    def form_valid(self, form):
        response = super().form_valid(form)

        # Authenticate the user and log them in
        user = authenticate(self.request,
            identifier=form.cleaned_data['phone'],
            password=form.cleaned_data['password1']
        )
        login(self.request, user)

        # Send the SMS verification code.
        user.send_phone_verification_code()

        return response


class ProfileView(LoginRequiredMixin, vanilla.UpdateView):
    form_class = ProfileForm
    template_name = 'account/profile.html'
    success_url = reverse_lazy('account:profile')

    def get_object(self):
        return self.request.user

    def form_valid(self, form):
        dirty_fields = self.object.get_dirty_fields()
        
        self.phone_changed = 'phone' in dirty_fields
        if self.phone_changed:
            self.object.phone_verified = False
        
        return super().form_valid(form)

    def get_success_url(self):
        if self.phone_changed:
            return reverse_lazy('account:phone-verify-send')
        return reverse_lazy('account:profile')


class SendPhoneVerification(LoginRequiredMixin, vanilla.FormView):
    form_class = SendPhoneVerificationForm
    template_name = 'account/phone-verify.html'
    success_url = reverse_lazy('account:phone-verify-submit')

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.phone_verified:
            return redirect('account:profile')
        return super().dispatch(request, *args, **kwargs)

    def get_form(self, *args, **kwargs):
        return super().get_form(user=self.request.user, *args, **kwargs)

    def get_object(self):
        return self.request.user

    def form_valid(self, form):
        self.request.user.send_phone_verification_code()
        return super().form_valid(form)

class SubmitPhoneVerification(LoginRequiredMixin, vanilla.FormView):
    form_class = SubmitPhoneVerificationForm
    template_name = 'account/phone-verify-submit.html'
    success_url = reverse_lazy('account:profile')

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.phone_verified:
            return redirect('account:profile')
        return super().dispatch(request, *args, **kwargs)

    def get_form(self, *args, **kwargs):
        return super().get_form(user=self.request.user, *args, **kwargs)

    def get_object(self):
        return self.request.user

    def form_valid(self, form):
        self.request.user.phone_verified = True
        self.request.user.save()
        cache.delete(self.request.user.phone_verification_code_key)
        cache.delete(self.request.user.phone_verification_rate_limit_key)
        return super().form_valid(form)


# Password Reset Views
# - PasswordReset sends the text message
# - PasswordResetConfirm verifies the text code and changes the password

# class PasswordReset(vanilla.FormView):
#     pass

# class PasswordResetConfirm(vanilla.FormView)
