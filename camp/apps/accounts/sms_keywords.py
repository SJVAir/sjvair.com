import re
import unicodedata

import phonenumbers

from django.conf import settings
from django.utils.translation import gettext as _

# Twilio error code for a send to a number that has opted out.
OPTED_OUT_ERROR = 21610

TWILIO_OPT_OUT_KIND = 'twilio_opt_out'
OPT_OUT_KIND = 'opt_out'
TWILIO_OPT_IN_KIND = 'twilio_opt_in'

# Twilio enforces these itself on a plain number: sends afterwards fail
# with OPTED_OUT_ERROR until the person texts an opt-in keyword.
TWILIO_OPT_OUT = {'STOP', 'STOPALL', 'STOP ALL', 'UNSUBSCRIBE', 'CANCEL', 'END', 'QUIT', 'OPTOUT', 'REVOKE'}
TWILIO_OPT_IN = {'START', 'UNSTOP', 'YES'}

# Keywords Twilio doesn't know; we enforce them ourselves. The Filipino and
# Hmong words still need a native-speaker check.
OPT_OUT = {
    'es': {'PARAR', 'PARA', 'ALTO', 'DETENER', 'CANCELAR', 'BAJA', 'DESUSCRIBIR'},
    'tl': {'TIGIL', 'HINTO', 'ITIGIL'},
    'hmn': {'TSEEM', 'NRES'},
}

# ASCII only so the reply stays a GSM-7 SMS. Filipino and Hmong fall back
# to English until there are vetted translations.
OPT_OUT_REPLIES = {
    'en': "SJVAir: You won't get any more texts from us. To get alerts again, verify your phone at https://www.sjvair.com/account/",
    'es': 'SJVAir: Ya no recibira mensajes de nosotros. Para volver a recibir alertas, verifique su telefono en https://www.sjvair.com/account/',
}

OPT_IN_REPLIES = {
    'en': 'SJVAir: To get air quality alerts again, verify your phone at https://www.sjvair.com/account/',
    'es': 'SJVAir: Para volver a recibir alertas de calidad del aire, verifique su telefono en https://www.sjvair.com/account/',
}


def normalize(body):
    text = unicodedata.normalize('NFKD', body or '')
    text = ''.join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r'\s+', ' ', text).strip().upper()
    return text.rstrip('.!?').strip()


def classify(body):
    '''
    Return the opt-out/opt-in kind for an inbound text, or None. Only an
    exact match on the whole message counts, so "please stop by" doesn't.
    '''
    text = normalize(body)
    if text in TWILIO_OPT_OUT:
        return TWILIO_OPT_OUT_KIND
    if text in TWILIO_OPT_IN:
        return TWILIO_OPT_IN_KIND
    if any(text in keywords for keywords in OPT_OUT.values()):
        return OPT_OUT_KIND
    return None


def get_opt_out_reply(language):
    return OPT_OUT_REPLIES.get(language, OPT_OUT_REPLIES['en'])


def get_opt_in_reply(language):
    return OPT_IN_REPLIES.get(language, OPT_IN_REPLIES['en'])


def get_opt_in_instructions():
    try:
        number = phonenumbers.format_number(
            phonenumbers.parse(settings.TWILIO_PHONE_NUMBERS[0], 'US'),
            phonenumbers.PhoneNumberFormat.NATIONAL,
        )
    except (IndexError, phonenumbers.NumberParseException):
        return _('Text START to our number to allow texts from SJVAir again, then request a new code.')
    return _('Text START to {number} to allow texts from SJVAir again, then request a new code.').format(number=number)
