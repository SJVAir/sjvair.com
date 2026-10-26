from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from camp.utils.beta import BETA_TESTERS_GROUP

User = get_user_model()


class SeedBetaTesterTests(TestCase):
    """Dev-only: a non-staff beta tester the dashboard's embedding suite signs in as."""

    def setUp(self):
        cache.clear()

    def seed(self, identifier, password='letmein-e2e'):
        call_command('seed_beta_tester', identifier=identifier, password=password)

    def test_refuses_without_debug(self):
        with self.assertRaises(CommandError):
            self.seed('e2e@example.com')
        assert not User.objects.filter(email='e2e@example.com').exists()

    @override_settings(DEBUG=True)
    def test_creates_non_staff_beta_tester_by_email(self):
        self.seed('e2e@example.com')
        user = User.objects.get(email='e2e@example.com')
        assert user.is_staff is False
        assert user.is_superuser is False
        assert user.is_active is True
        assert user.groups.filter(name=BETA_TESTERS_GROUP).exists()
        assert user.check_password('letmein-e2e')

    @override_settings(DEBUG=True)
    def test_creates_by_phone(self):
        self.seed('559-555-0198')
        user = User.objects.get(phone='+15595550198')
        assert User.objects.filter(pk=user.pk, email__isnull=True).exists()  # NullEmailField reads NULL as ''
        assert user.groups.filter(name=BETA_TESTERS_GROUP).exists()

    @override_settings(DEBUG=True)
    def test_is_idempotent(self):
        self.seed('e2e@example.com')
        User.objects.filter(email='e2e@example.com').update(is_staff=True)
        self.seed('e2e@example.com', password='new-password-1')
        assert User.objects.filter(email='e2e@example.com').count() == 1
        user = User.objects.get(email='e2e@example.com')
        assert user.check_password('new-password-1')
        assert user.is_staff is False

    @override_settings(DEBUG=True)
    def test_missing_values_error(self):
        with self.assertRaises(CommandError):
            call_command('seed_beta_tester', identifier='', password='x')
        with self.assertRaises(CommandError):
            call_command('seed_beta_tester', identifier='e2e@example.com', password='')

    @override_settings(BETA_TOOLS_GATE=True)
    def test_seeded_user_can_open_workspace(self):
        with override_settings(DEBUG=True):  # only for the command; requests under DEBUG trip the toolbar
            self.seed('e2e@example.com')
        assert self.client.get('/workspace/').status_code == 404
        self.client.post('/account/login/', {'identifier': 'e2e@example.com', 'password': 'letmein-e2e'})
        assert self.client.get('/workspace/').status_code == 200
