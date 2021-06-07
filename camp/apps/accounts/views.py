from django.contrib.auth import authenticate, login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy

import vanilla

from .forms import (UserCreationForm, ProfileForm)
from camp.utils.views import RedirectViewMixin


class SignupView(RedirectViewMixin, vanilla.CreateView):
    template_name = 'account/signup.html'
    form_class = UserCreationForm
    redirect_field_name = 'next'
    success_url = 'account:membership'

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
