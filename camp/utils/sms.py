import re
import unicodedata
from contextlib import contextmanager

from django.conf import settings
from django.utils import translation

SMS_CHAR_MAP = str.maketrans({
    '‘': "'", '’': "'", '“': '"', '”': '"',
    '–': '-', '—': '-', '…': '...',
    '\u00bf': '?', '\u00a1': '!',
})


# ASCII printables that are not in the GSM-7 basic set (extension table or absent).
NOT_GSM_7_BASIC = set('[]{}\\^~|`')


def gsm_fold(text):
    '''
    Fold text to plain ASCII that is safe in a GSM-7 SMS: accents are
    stripped, curly quotes and dashes flattened, and anything else dropped.
    Newlines are kept.
    '''
    text = unicodedata.normalize('NFKD', text.translate(SMS_CHAR_MAP))
    return ''.join(
        char for char in text
        if char == '\n' or (ord(char) < 128 and char.isprintable() and char not in NOT_GSM_7_BASIC)
    )


def sms_safe(text, max_length=60):
    '''
    Reduce owner-set text to plain ASCII so one stray character (accent,
    curly quote, emoji) can't force UCS-2 and double the billed segments.
    '''
    text = re.sub(r'\s+', ' ', gsm_fold(text)).strip()
    if len(text) > max_length:
        text = text[:max_length - 3].rstrip() + '...'
    return text


def sms_language(language=None):
    '''
    The language code to render an SMS in: the user's preferred language
    (a variant such as es-mx resolves to a supported one), or
    settings.LANGUAGE_CODE when it is blank or not one we offer.
    '''
    if language:
        try:
            return translation.get_supported_language_variant(language)
        except LookupError:
            pass
    return settings.LANGUAGE_CODE


@contextmanager
def sms_translation(language=None):
    '''Activate the recipient's language while an SMS body is rendered.'''
    with translation.override(sms_language(language)):
        yield
