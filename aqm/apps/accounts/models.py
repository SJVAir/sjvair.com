from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.translation import ugettext_lazy as _

from django_smalluuid.models import SmallUUIDField, uuid_default
from nameparser.parser import HumanName

from aqm.apps.accounts import managers


class User(AbstractBaseUser, PermissionsMixin, models.Model):
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )
    full_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True, db_index=True)

    # Normally provided by auth.AbstractUser, but we're not using that here.
    date_joined = models.DateTimeField(_('date joined'), default=timezone.now, editable=False)
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
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['full_name']

    objects = managers.UserManager()

    class Meta:
        ordering = ('-date_joined',)

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
