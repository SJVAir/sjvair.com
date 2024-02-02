import vanilla

from django.shortcuts import redirect
from django.urls import reverse_lazy

from .forms import ContactForm


class ContactFormView(vanilla.FormView):
    form_class = ContactForm
    template_name = 'contact/contact_form.html'
    success_url = reverse_lazy('contact:done')

    def form_valid(self, form):
        form.send_email()
        return super().form_valid(form)


class ContactDoneView(vanilla.TemplateView):
    template_name = 'contact/contact_done.html'
