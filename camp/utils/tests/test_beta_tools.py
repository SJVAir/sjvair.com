from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase, override_settings
from waffle.models import Flag

from camp.utils.beta import BETA_TESTERS_GROUP, BETA_TOOLS_FLAG

User = get_user_model()


@override_settings(BETA_TOOLS_GATE=True)
class BetaToolsGateTests(TestCase):
    """The data tools under /tools/ are for the `beta_tools` flag only (migration pesticides/0020)."""
    fixtures = ['pesticides-explorer']

    def setUp(self):
        cache.clear()

    def user(self, phone, **extra):
        return User.objects.create_user(f'{phone}@sjvair.com', 'letmein1', full_name='Tester', phone=phone, **extra)

    def test_migration_creates_the_flag_and_group(self):
        flag = Flag.objects.get(name=BETA_TOOLS_FLAG)
        assert flag.everyone is None
        assert flag.staff and flag.superusers
        assert list(flag.groups.values_list('name', flat=True)) == [BETA_TESTERS_GROUP]

    def test_anonymous_gets_404_and_no_nav(self):
        assert self.client.get('/tools/pesticides/').status_code == 404
        assert self.client.get('/tools/pesticides/records/').status_code == 404
        html = self.client.get('/about/').content.decode()
        assert 'Data Tools' not in html
        assert 'Pesticides Explorer' not in html

    def test_signed_in_user_without_the_flag_gets_404(self):
        self.client.force_login(self.user('559-555-0101'))
        assert self.client.get('/tools/pesticides/').status_code == 404

    def test_beta_tester_gets_the_tools_and_nav(self):
        user = self.user('559-555-0102')
        user.groups.add(Group.objects.get(name=BETA_TESTERS_GROUP))
        self.client.force_login(user)
        assert self.client.get('/tools/pesticides/').status_code == 200
        html = self.client.get('/about/').content.decode()
        assert 'Data Tools' in html
        assert html.count('Pesticides Explorer') == 2  # navbar and footer (the map home has no footer)

    def test_staff_get_the_tools(self):
        self.client.force_login(self.user('559-555-0103', is_staff=True))
        assert self.client.get('/tools/pesticides/').status_code == 200

    def test_the_data_api_is_not_gated(self):
        assert self.client.get('/api/2.0/pesticides/chemicals/').status_code == 200

    @override_settings(BETA_TOOLS_GATE=False)
    def test_gate_off_opens_the_tools(self):
        assert self.client.get('/tools/pesticides/').status_code == 200
        assert 'Data Tools' in self.client.get('/about/').content.decode()
