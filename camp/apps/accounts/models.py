import random
import string

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.cache import cache
from django.db import models
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

from dirtyfields import DirtyFieldsMixin
from django_smalluuid.models import SmallUUIDField, uuid_default
from model_utils import Choices
from nameparser.parser import HumanName
from phonenumber_field.modelfields import PhoneNumberField

from camp.apps.accounts import managers
from camp.apps.accounts.tasks import send_sms_message
from camp.utils.fields import NullEmailField


class User(AbstractBaseUser, PermissionsMixin, DirtyFieldsMixin, models.Model):
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
    )  # Required for Django Admin, for tenant staff/admin see role

    EMAIL_FIELD = 'email'
    USERNAME_FIELD = 'phone'
    REQUIRED_FIELDS = ['full_name']

    objects = managers.UserManager()

    class Meta:
        ordering = ('-date_joined',)

    def __str__(self):
        return str(self.name)

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
        return f'phone-rate-limit:{self.phone}'

    @property
    def phone_verification_code_key(self):
        return f'phone-code:{self.phone}'

    def send_phone_verification_code(self, expires=300):
        code = ''.join([random.choice(string.digits) for x in range(6)])
        cache.set(self.phone_verification_code_key, code, expires)
        message = f'SJVAir – Verification Code: {code}'
        self.send_sms(message, verify=False)  # Don't do a verification check

    def check_phone_verification_code(self, code):
        cached_code = cache.get(self.phone_verification_code_key)
        print(code, cached_code)
        return code == cached_code

    def send_sms(self, message, verify=True):
        if self.phone and (self.phone_verified or not verify):
            return send_sms_message(self.phone, message)
        return False
