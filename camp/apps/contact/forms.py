from django import forms
from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string

from django_recaptcha.fields import ReCaptchaField
from django_recaptcha.widgets import ReCaptchaV2Checkbox
from model_utils import Choices


class ContactForm(forms.Form):
    TOPICS = Choices(
        ('Bug', 'Bug or Technical Issue'),
        ('Feedback', 'Feature Suggestion or App Feedback'),
        ('Media', 'Media Inquiry'),
        ('General', 'General'),
    )

    name = forms.CharField(max_length=100)
    email = forms.EmailField()
    topic = forms.ChoiceField(choices=TOPICS)
    subject = forms.CharField(max_length=79)
    message = forms.CharField(widget=forms.Textarea)
    captcha = ReCaptchaField(label='')

    def send_email(self):
        assert self.is_valid()

        subject = f"[SJVAir - {self.cleaned_data['topic']}] {self.cleaned_data['subject']}"
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
