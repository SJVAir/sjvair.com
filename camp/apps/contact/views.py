from urllib.parse import urlsplit

import vanilla

from django.shortcuts import redirect
from django.urls import reverse_lazy

from .forms import ContactForm


class ContactFormView(vanilla.FormView):
    form_class = ContactForm
    template_name = 'contact/contact_form.html'
    success_url = reverse_lazy('contact:done')

    REPORT_PATH = '/workspace/shared/'
    REPORT_PAGE_MAX = 500

    def report_page(self):
        """The `page` query value when it is a shared-dashboard URL on this site, else None."""
        page = self.request.GET.get('page', '')
        if not page or len(page) > self.REPORT_PAGE_MAX:
            return None
        try:
            parts = urlsplit(page)
        except ValueError:
            return None
        if parts.scheme not in ('', 'http', 'https'):
            return None
        if parts.netloc and parts.netloc != self.request.get_host():
            return None
        if not parts.path.startswith(self.REPORT_PATH):
            return None
        return page

    def get_form(self, data=None, files=None, **kwargs):
        if data is None and self.request.GET.get('topic') == 'Report':
            page = self.report_page()
            if page:
                kwargs.setdefault('initial', {
                    'topic': 'Report',
                    'subject': 'Report a shared dashboard',
                    'message': f'Page: {page}\n\n',
                })
        return super().get_form(data=data, files=files, **kwargs)

    def form_valid(self, form):
        form.send_email()
        return super().form_valid(form)


class ContactDoneView(vanilla.TemplateView):
    template_name = 'contact/contact_done.html'
