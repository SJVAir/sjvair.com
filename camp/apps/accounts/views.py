import random
import string

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
    success_url = reverse_lazy('account:phone-verify-send')

    def get_context_data(self, **kwargs):
        context = super(SignupView, self).get_context_data(**kwargs)
        context[self.redirect_field_name] = self.get_redirect_url()
        return context

    def form_valid(self, form):
        response = super(SignupView, self).form_valid(form)
        user = authenticate(self.request,
            username=form.cleaned_data['email'],
            password=form.cleaned_data['password1']
        )
        login(self.request, user)
        return response


class ProfileView(LoginRequiredMixin, vanilla.UpdateView):
    form_class = ProfileForm
    template_name = 'account/profile.html'
    success_url = reverse_lazy('account:profile')

    def get_object(self):
        return self.request.user


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

    def generate_verification_code(self, expires=5):
        code = ''.join([random.choice(string.digits) for x in range(4)])
        cache_key = self.request.user.verify_phone_code_key
        cache.set(cache_key, code, expires)
        return code

    def form_valid(self, form):
        code = self.generate_verification_code(form.CODE_EXPIRES * 60)
        message = f'SJVAir.com – Verification Code: {code}'
        self.request.user.send_sms(message, verify=False)  # Don't do a verification check
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
        cache.delete(self.request.user.verify_phone_code_key)
        cache.delete(self.request.user.verify_phone_rate_limit_key)
        return super().form_valid(form)
