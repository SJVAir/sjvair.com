from django.conf import settings

from twilio.request_validator import RequestValidator


def is_valid_twilio_request(request):
    '''
    True if the request carries a valid X-Twilio-Signature for its URL and
    POST body. Always False without a configured auth token, since an empty
    key makes signatures trivially forgeable.
    '''
    if not settings.TWILIO_AUTH_TOKEN:
        return False
    validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
    signature = request.META.get('HTTP_X_TWILIO_SIGNATURE', '')
    return validator.validate(request.build_absolute_uri(), request.POST, signature)
