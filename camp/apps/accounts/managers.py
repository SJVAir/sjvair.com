from django.contrib.auth.models import BaseUserManager
from django.utils import timezone


class UserManager(BaseUserManager):
    def create_user(self, email, password, **extra_fields):
        """
        Creates and saves a User with the given username, email and password.
        """
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        now = timezone.now()
        email = UserManager.normalize_email(email)
        user = self.model(email=email, date_joined=now, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.update(
            is_active=True,
            is_staff=True,
            is_superuser=True,
        )
        user = self.create_user(email, password, **extra_fields)
        return user

    def get_by_natural_key(self, username):
        return self.get(**{self.model.USERNAME_FIELD: username})
