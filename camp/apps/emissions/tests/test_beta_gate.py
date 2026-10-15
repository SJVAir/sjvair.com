from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase, override_settings

from camp.utils.beta import BETA_TESTERS_GROUP

User = get_user_model()


@override_settings(BETA_TOOLS_GATE=True)
class EmissionsBetaGateTests(TestCase):
    """The emissions explorer sits under /tools/, behind the `beta_tools` flag (camp.utils.beta)."""

    def setUp(self):
        cache.clear()

    def user(self, phone, **extra):
        return User.objects.create_user(f'{phone}@sjvair.com', 'letmein1', full_name='Tester', phone=phone, **extra)

    def test_anonymous_gets_404_and_no_links(self):
        assert self.client.get('/tools/emissions/').status_code == 404
        assert self.client.get('/tools/emissions/about/').status_code == 404
        assert 'Facility Emissions Explorer' not in self.client.get('/about/').content.decode()

    def test_signed_in_user_without_the_flag_gets_404(self):
        self.client.force_login(self.user('559-555-0111'))
        assert self.client.get('/tools/emissions/about/').status_code == 404

    def test_beta_tester_gets_the_explorer_and_links(self):
        user = self.user('559-555-0112')
        user.groups.add(Group.objects.get(name=BETA_TESTERS_GROUP))
        self.client.force_login(user)
        assert self.client.get('/tools/emissions/about/').status_code == 200
        # The navbar's Data Tools item and the footer.
        assert self.client.get('/about/').content.decode().count('Facility Emissions Explorer') == 2

    def test_the_emissions_api_is_not_gated(self):
        assert self.client.get('/api/2.0/emissions/years/').status_code == 200
