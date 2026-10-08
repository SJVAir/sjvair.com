import re
import unicodedata

import phonenumbers

from django.conf import settings
from django.utils.translation import gettext

from camp.utils.sms import gsm_fold, sms_translation

# Twilio error code for a send to a number that has opted out.
OPTED_OUT_ERROR = 21610

TWILIO_OPT_OUT_KIND = 'twilio_opt_out'
OPT_OUT_KIND = 'opt_out'
TWILIO_OPT_IN_KIND = 'twilio_opt_in'

# Twilio enforces these itself on a plain number: sends afterwards fail
# with OPTED_OUT_ERROR until the person texts an opt-in keyword.
TWILIO_OPT_OUT = {'STOP', 'STOPALL', 'UNSUBSCRIBE', 'CANCEL', 'END', 'QUIT', 'OPTOUT', 'REVOKE'}
TWILIO_OPT_IN = {'START', 'UNSTOP', 'YES'}

# Keywords Twilio doesn't act on; we enforce them ourselves. Twilio only
# blocks on single-word messages, so 'STOP ALL' (two words) is ours. The
# Filipino and Hmong words still need a native-speaker check.
OPT_OUT = {
    'en': {'STOP ALL'},
    'es': {'PARAR', 'PARA', 'ALTO', 'DETENER', 'CANCELAR', 'BAJA', 'DESUSCRIBIR'},
    'tl': {'TIGIL', 'HINTO', 'ITIGIL'},
    'hmn': {'TSEEM', 'NRES'},
}


def normalize(body):
    text = unicodedata.normalize('NFKD', body or '')
    text = ''.join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r'\s+', ' ', text).strip().upper()
    # Punctuation either side: "Stop!", "¡Alto!", "¿Parar?"
    return re.sub(r'^[\W_]+|[\W_]+$', '', text)


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
    '''
    The reply to an opt-out keyword, in the user's language. Anything
    without a translation in the catalogs comes back in English. Folded to
    ASCII so the reply stays a GSM-7 SMS.
    '''
    with sms_translation(language):
        return gsm_fold(gettext(
            "SJVAir: You won't get any more texts from us. "
            'To get alerts again, verify your phone at https://www.sjvair.com/account/'
        ))


def get_opt_in_reply(language):
    with sms_translation(language):
        return gsm_fold(gettext(
            'SJVAir: To get air quality alerts again, '
            'verify your phone at https://www.sjvair.com/account/'
        ))


def get_opt_in_instructions():
    try:
        number = phonenumbers.format_number(
            phonenumbers.parse(settings.TWILIO_PHONE_NUMBERS[0], 'US'),
            phonenumbers.PhoneNumberFormat.NATIONAL,
        )
    except (IndexError, phonenumbers.NumberParseException):
        return gettext('Text START to our number to allow texts from SJVAir again, then request a new code.')
    return gettext('Text START to {number} to allow texts from SJVAir again, then request a new code.').format(number=number)
