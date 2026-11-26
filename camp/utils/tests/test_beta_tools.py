from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.http import Http404, HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.contrib.auth.models import AnonymousUser
from waffle.models import Flag

from camp.utils.beta import BETA_TESTERS_GROUP, BETA_TOOLS_FLAG, is_beta_path
from camp.utils.middleware import BetaToolsMiddleware

User = get_user_model()


@override_settings(BETA_TOOLS_GATE=True)
class BetaToolsGateTests(TestCase):
    """The data tools under /tools/ are for the `beta_tools` flag only (migration pesticides/0002)."""
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

    def gated(self, path, user=None):
        """Whether the middleware turns `path` away: True for a 404, False for passed through."""
        request = RequestFactory().get(path)
        request.user = user or AnonymousUser()
        try:
            BetaToolsMiddleware(lambda request: HttpResponse('ok'))(request)
        except Http404:
            return True
        return False

    def test_the_explorers_are_public(self):
        assert self.client.get('/tools/pesticides/').status_code == 200
        assert self.client.get('/tools/emissions/about/').status_code == 200
        html = self.client.get('/about/').content.decode()
        assert 'Data Tools' in html
        assert html.count('Pesticides Explorer') == 2  # navbar and footer (the map home has no footer)
        assert html.count('Facility Emissions Explorer') == 2
        # The dashboard is still beta: no link to it.
        assert 'My Dashboard' not in html

    def test_other_tools_are_still_beta(self):
        assert is_beta_path('/tools/other/') and not is_beta_path('/tools/pesticides/records/')
        assert self.gated('/tools/other/')
        assert self.gated('/tools/other/', self.user('559-555-0101'))

    def test_beta_tester_gets_the_beta_tools(self):
        user = self.user('559-555-0102')
        user.groups.add(Group.objects.get(name=BETA_TESTERS_GROUP))
        assert not self.gated('/tools/other/', user)

    def test_staff_get_the_beta_tools(self):
        assert not self.gated('/tools/other/', self.user('559-555-0103', is_staff=True))

    def test_the_data_api_is_not_gated(self):
        assert self.client.get('/api/2.0/pesticides/chemicals/').status_code == 200

    @override_settings(BETA_TOOLS_GATE=False)
    def test_gate_off_opens_the_tools(self):
        assert not self.gated('/tools/other/')
