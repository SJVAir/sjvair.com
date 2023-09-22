from random import choice

from django.conf import settings

import twilio.rest
from twilio.base.exceptions import TwilioRestException

from django_huey import db_task


@db_task(priority=100)
def send_sms_message(phone_number, message):
    twilio_client = twilio.rest.Client(
        settings.TWILIO_ACCOUNT_SID,
        settings.TWILIO_AUTH_TOKEN
    )
    return twilio_client.messages.create(
        to=str(phone_number),
        from_=choice(settings.TWILIO_PHONE_NUMBERS),
        body=message,
    )
