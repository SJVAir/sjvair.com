from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from camp.utils.text import render_markdown


def send_email(subject, template, context, to, headers=None, from_email=None):
    message = render_to_string(template, context)
    html_message = render_markdown(message)

    email = EmailMultiAlternatives(
        subject=subject,
        body=message,
        to=[to] if isinstance(to, str) else to,
        headers=headers or {},
        from_email=from_email,
    )
    email.attach_alternative(html_message, 'text/html')
    email.send()
    return email
