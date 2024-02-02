from django import forms
from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string


class ContactForm(forms.Form):
    name = forms.CharField()
    email = forms.EmailField()
    message = forms.CharField(widget=forms.Textarea)

    def send_email(self):
        assert self.is_valid()

        subject = f"SJVAir Contact Form: {self.cleaned_data['name']}"
        message = render_to_string('email/contact-form.md', self.cleaned_data)

        email = EmailMessage(
            subject=subject,
            body=message,
            to=settings.SJVAIR_CONTACT_EMAILS,
            headers={
                'Reply-To': self.cleaned_data['email']
            },
        )

        email.send()
        return email
