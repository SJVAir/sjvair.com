from django.contrib.auth import authenticate, login, views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.tokens import default_token_generator as token_generator
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.http import urlsafe_base64_decode
from django.views import View
from django.views.decorators.csrf import csrf_exempt

import vanilla

from twilio.twiml.messaging_response import MessagingResponse

from camp.utils.twilio_signature import is_valid_twilio_request
from camp.utils.views import RedirectViewMixin

from . import forms, sms_keywords
from .models import User


class SignupView(RedirectViewMixin, vanilla.CreateView):
    template_name = 'registration/signup.html'
    form_class = forms.UserCreationForm
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
    form_class = forms.ProfileForm
    template_name = 'account/profile.html'
    success_url = reverse_lazy('account:profile')

    def get_object(self):
        return self.request.user

    def form_valid(self, form):
        self.phone_changed = self.object.tracker.has_changed('phone')
        return super().form_valid(form)

    def get_success_url(self):
        if self.phone_changed:
            return reverse_lazy('account:phone-verify-send')
        return reverse_lazy('account:profile')


class SendPhoneVerification(LoginRequiredMixin, vanilla.FormView):
    form_class = forms.SendPhoneVerificationForm
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
    form_class = forms.SubmitPhoneVerificationForm
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


class PasswordReset(vanilla.FormView):
    form_class = forms.PasswordResetForm
    success_url = reverse_lazy('account:password-reset-confirm')
    template_name = 'registration/password_reset.html'

    def form_valid(self, form):
        options = form.save()
        self.request.session['_password-reset'] = options
        return redirect(self.get_success_url())


class PasswordResetConfirm(vanilla.FormView):
    form_class = forms.SetPasswordForm
    success_url = reverse_lazy('account:password-reset-complete')
    template_name = 'registration/password_reset_confirm.html'

    def dispatch(self, *args, **kwargs):
        options = self.request.session.get('_password-reset')

        try:
            uidb64 = options['uidb64']
            token = options['token']
        except (KeyError, TypeError):
            return self.invalid_token()

        self.user = self.get_user(uidb64)
        if self.user and token_generator.check_token(self.user, token):
            return super().dispatch(*args, **kwargs)
        return self.invalid_token()

    def invalid_token(self):
        self.user = None
        form = self.get_form()
        context = self.get_context_data(form=form)
        return self.render_to_response(context)

    def get_user(self, uidb64):
        try:
            user_id = urlsafe_base64_decode(uidb64).decode()
            return User._default_manager.get(pk=user_id)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist, ValidationError):
            return None

    def get_form(self, *args, **kwargs):
        return super().get_form(user=self.user, *args, **kwargs)

    def form_valid(self, form):
        form.save()
        del self.request.session['_password-reset']
        return super().form_valid(form)


@method_decorator(csrf_exempt, name='dispatch')
class TwilioInboundSMS(View):
    '''
    Twilio forwards every text sent to our number here. Opt-out keywords
    mark the phone unverified; START clears a Twilio-enforced block.
    '''
    def post(self, request, *args, **kwargs):
        if not is_valid_twilio_request(request):
            return HttpResponseForbidden()

        reply = MessagingResponse()
        kind = sms_keywords.classify(request.POST.get('Body', ''))
        sender = request.POST.get('From', '')
        user = User.objects.filter(phone=sender).first() if (kind and sender) else None

        if user is not None:
            if kind == sms_keywords.TWILIO_OPT_OUT_KIND:
                # Twilio sends its own confirmation for these.
                user.opt_out_of_sms(blocked=True)
            elif kind == sms_keywords.OPT_OUT_KIND:
                user.opt_out_of_sms(blocked=False)
                reply.message(sms_keywords.get_opt_out_reply(user.language))
            elif kind == sms_keywords.TWILIO_OPT_IN_KIND:
                user.clear_sms_block()
                if not user.phone_verified:
                    reply.message(sms_keywords.get_opt_in_reply(user.language))

        return HttpResponse(str(reply), content_type='text/xml')
