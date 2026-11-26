import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError

from camp.utils.beta import BETA_TESTERS_GROUP

User = get_user_model()

# A phone number is required; 555-01xx numbers are reserved for fiction.
PLACEHOLDER_PHONE = '+15595550199'


class Command(BaseCommand):
    help = (
        'Local development only: create or update a non-staff "Beta testers" user, '
        'the account the data dashboard\'s embedding tests sign in as.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--identifier', default=os.environ.get('WORKSPACE_E2E_IDENTIFIER', ''),
                            help='Email or phone (default: $WORKSPACE_E2E_IDENTIFIER)')
        parser.add_argument('--password', default=os.environ.get('WORKSPACE_E2E_PASSWORD', ''),
                            help='Password (default: $WORKSPACE_E2E_PASSWORD)')

    def handle(self, *args, identifier, password, **options):
        if not settings.DEBUG:
            raise CommandError('seed_beta_tester only runs with DEBUG on (local development).')
        if not identifier or not password:
            raise CommandError('Set WORKSPACE_E2E_IDENTIFIER and WORKSPACE_E2E_PASSWORD (or pass --identifier and --password).')

        if '@' in identifier:
            lookup = {'email': User.objects.normalize_email(identifier)}
            defaults = {'phone': PLACEHOLDER_PHONE}
        else:
            lookup = {'phone': identifier}
            defaults = {}

        user = User.objects.filter(**lookup).first() or User(**lookup, **defaults)
        user.full_name = 'Workspace E2E'
        user.is_active = True
        user.is_staff = False
        user.is_superuser = False
        user.set_password(password)
        user.save()
        user.groups.add(Group.objects.get(name=BETA_TESTERS_GROUP))
        self.stdout.write(f'Beta tester ready: {identifier} (user {user.pk})')
