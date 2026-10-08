import random
import string

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.cache import cache
from django.db import models
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

from django_smalluuid.models import SmallUUIDField, uuid_default
from model_utils import Choices, FieldTracker
from nameparser.parser import HumanName
from phonenumber_field.modelfields import PhoneNumberField

from camp.apps.accounts import managers
from camp.apps.accounts import tasks
from camp.utils.fields import NullEmailField


class User(AbstractBaseUser, PermissionsMixin, models.Model):
    LANGUAGES = Choices(*settings.LANGUAGES)

    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )
    full_name = models.CharField(_('Full name'), max_length=100)
    email = NullEmailField(_('Email address'), unique=True, blank=True, null=True, db_index=True)
    phone = PhoneNumberField(_('Phone number'), unique=True, db_index=True, help_text="Your cell phone number for receiving air quality text alerts.")
    phone_verified = models.BooleanField(default=False)
    # Twilio is blocking texts to this number (the person texted an English
    # opt-out keyword, or a send failed with error 21610). Cleared when they
    # text START.
    sms_blocked = models.BooleanField(_('SMS blocked by carrier opt-out'), default=False, db_default=False)
    language = models.CharField(_('Preferred Language'), max_length=5, choices=LANGUAGES, default=LANGUAGES.en)

    # Normally provided by auth.AbstractUser, but we're not using that here.
    date_joined = models.DateTimeField(_('Date joined'), default=timezone.now, editable=False)
    is_active = models.BooleanField(
        _('active'),
        default=True,
        help_text=_(
            'Designates whether this user should be treated as '
            'active. Unselect this instead of deleting accounts.'
        )
    )
    is_staff = models.BooleanField(
        _('staff status'),
        default=False,
        help_text=_(
            'Designates whether the user can log into this admin site.'
        )
    )

    EMAIL_FIELD = 'email'
    USERNAME_FIELD = 'phone'
    REQUIRED_FIELDS = ['full_name']

    objects = managers.UserManager()

    tracker = FieldTracker(fields=['phone'])

    class Meta:
        ordering = ('-date_joined',)

    def __str__(self):
        return str(self.name)

    def save(self, *args, **kwargs):
        # A carrier opt-out and a verification both belong to the number,
        # not the person: a new number is unverified and unblocked.
        if not self._state.adding and self.tracker.has_changed('phone'):
            self.sms_blocked = False
            self.phone_verified = False
            update_fields = kwargs.get('update_fields')
            if update_fields is not None:
                kwargs['update_fields'] = {*update_fields, 'sms_blocked', 'phone_verified'}
        super().save(*args, **kwargs)

    def get_name(self):
        name = HumanName(self.full_name)
        name.capitalize()
        return name

    def set_name(self, value):
        self.full_name = value
        del self.name

    name = cached_property(get_name)
    name.setter = set_name

    def get_short_name(self):
        return self.name.first

    def get_full_name(self):
        return self.name

    @property
    def phone_verification_rate_limit_key(self):
        return f'phone-rate-limit:{self.pk}'

    @property
    def phone_verification_code_key(self):
        return f'phone-code:{self.phone}'

    def check_phone_verification_rate_limit(self):
        cache_key = self.phone_verification_rate_limit_key
        return cache.get(cache_key, default=False)

    def claim_phone_verification_slot(self):
        '''
        Atomically claim the user's phone verification send slot. Keyed on the
        user (not the number) so changing phone can't buy extra texts.
        Returns True if claimed, False if a code was sent recently.
        '''
        cache_key = self.phone_verification_rate_limit_key
        expires = settings.PHONE_VERIFICATION_RATE_LIMIT * 60
        return cache.add(cache_key, True, expires)

    def send_phone_verification_code(self):
        expires = settings.PHONE_VERIFICATION_CODE_EXPIRES * 60
        code = ''.join([
            random.choice(string.digits) for x
            in range(settings.PHONE_VERIFICATION_CODE_DIGITS)
        ])
        cache.set(self.phone_verification_code_key, code, expires)
        message = f'SJVAir – Verification Code: {code}'
        self.send_sms(message, verify=False)  # Don't do a verification check

    def check_phone_verification_code(self, code):
        cached_code = cache.get(self.phone_verification_code_key)
        return code == cached_code

    def send_sms(self, message, verify=True):
        if self.sms_blocked:
            return False
        if self.phone and (self.phone_verified or not verify):
            return tasks.send_sms_message(self.phone, message)
        return False

    def opt_out_of_sms(self, blocked):
        '''
        Stop all texts to this user. Resuming means verifying the phone again.
        '''
        self.phone_verified = False
        self.sms_blocked = self.sms_blocked or blocked
        cache.delete(self.phone_verification_code_key)
        self.save(update_fields=['phone_verified', 'sms_blocked'])

    def clear_sms_block(self):
        self.sms_blocked = False
        self.save(update_fields=['sms_blocked'])
