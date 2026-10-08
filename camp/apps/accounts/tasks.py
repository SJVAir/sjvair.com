import logging
from random import choice

from django.conf import settings

import twilio.rest
from twilio.base.exceptions import TwilioRestException

from django_huey import db_task

from camp.apps.accounts import sms_keywords

logger = logging.getLogger(__name__)


def handle_opted_out_number(phone_number):
    '''
    Twilio refused a send because this number opted out: stop texting it.
    '''
    from camp.apps.accounts.models import User

    user = User.objects.filter(phone=phone_number).first()
    if user is None:
        # Only the last four digits: phone numbers shouldn't land in logs.
        logger.warning('Twilio reports ...%s opted out, but no user has that number', str(phone_number)[-4:])
        return
    user.opt_out_of_sms(blocked=True)


@db_task(priority=100)
def send_sms_message(phone_number, message):
    twilio_client = twilio.rest.Client(
        settings.TWILIO_ACCOUNT_SID,
        settings.TWILIO_AUTH_TOKEN
    )
    try:
        return twilio_client.messages.create(
            to=str(phone_number),
            from_=choice(settings.TWILIO_PHONE_NUMBERS),
            body=message,
        )
    except TwilioRestException as exc:
        if exc.code != sms_keywords.OPTED_OUT_ERROR:
            raise
        handle_opted_out_number(phone_number)
