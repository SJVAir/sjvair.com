from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase, override_settings
from waffle.models import Flag

from camp.utils.beta import BETA_TESTERS_GROUP, BETA_TOOLS_FLAG, is_beta_path

User = get_user_model()

GATED = ['/workspace', '/workspace/', '/workspace/shared/x', '/workspace/manifest.webmanifest']


@override_settings(BETA_TOOLS_GATE=True)
class WorkspaceGateTests(TestCase):
    """/workspace is in the private preview: the `beta_tools` flag only, like /tools/."""

    def setUp(self):
        cache.clear()

    def user(self, phone, **extra):
        return User.objects.create_user(f'{phone}@sjvair.com', 'letmein1', full_name='Tester', phone=phone, **extra)

    def beta_tester(self, phone):
        user = self.user(phone)
        user.groups.add(Group.objects.get(name=BETA_TESTERS_GROUP))
        return user

    def test_anonymous_gets_404(self):
        for url in GATED:
            assert self.client.get(url).status_code == 404, url

    def test_signed_in_without_flag_gets_404(self):
        self.client.force_login(self.user('559-555-0121'))
        assert self.client.get('/workspace/').status_code == 404
        assert self.client.get('/workspace/manifest.webmanifest').status_code == 404

    def test_beta_tester_gets_the_page(self):
        self.client.force_login(self.beta_tester('559-555-0122'))
        assert self.client.get('/workspace/').status_code == 200

    def test_staff_get_the_page(self):
        self.client.force_login(self.user('559-555-0123', is_staff=True))
        assert self.client.get('/workspace/').status_code == 200

    def test_workspacefoo_is_not_gated(self):
        assert is_beta_path('/workspacefoo') is False
        assert is_beta_path('/workspace') is True
        assert is_beta_path('/workspace/dashboards/x') is True
        assert is_beta_path('/tools/x') is True
        assert is_beta_path('/about/') is False

    def test_nav_link(self):
        assert 'My Dashboard' not in self.client.get('/about/').content.decode()
        self.client.force_login(self.beta_tester('559-555-0124'))
        html = self.client.get('/about/').content.decode()
        assert 'href="/workspace/"' in html
        assert html.count('My Dashboard') == 2  # navbar and footer

    def test_flag_note_mentions_workspace(self):
        assert '/workspace/' in Flag.objects.get(name=BETA_TOOLS_FLAG).note
