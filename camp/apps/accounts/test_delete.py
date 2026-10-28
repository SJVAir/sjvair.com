from django.contrib.messages import get_messages
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from camp.api.v2.documents.tests.helpers import make_user, save
from camp.apps.accounts.models import User
from camp.apps.alerts.models import Subscription
from camp.apps.documents.models import SavedDocument
from camp.apps.monitors.purpleair.models import PurpleAir

PASSWORD = 'letmein1'


class DeleteAccountTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        cache.clear()
        self.user = make_user(1)
        self.client = Client()
        self.client.force_login(self.user)
        self.profile_url = reverse('account:profile')
        self.delete_url = reverse('account:delete')

    def make_docs(self):
        for id in ('one', 'two', 'three'):
            self.assertEqual(save(self.client, id).status_code, 200)
        token = self.client.post('/api/2.0/documents/one/share/').json()['data']['share_token']
        self.client.post('/api/2.0/documents/two/share/')
        # A deleted document still counts as a dashboard, but is not a share link.
        self.assertEqual(save(
            self.client, 'two', base_version=1, deleted_at='2026-10-28T00:00:00Z',
        ).status_code, 200)
        return token

    def delete(self, **data):
        data.setdefault('password', PASSWORD)
        data.setdefault('confirm', 'on')
        return self.client.post(self.delete_url, data)

    def test_profile_shows_counts_and_delete_form(self):
        self.make_docs()
        monitor = PurpleAir.objects.get(sensor_id=8892)
        Subscription.objects.create(user=self.user, monitor=monitor, level='unhealthy_sensitive')
        response = self.client.get(self.profile_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context['deletion_counts'],
            {'dashboards': 3, 'share_links': 1, 'subscriptions': 1},
        )
        self.assertIn('password', response.context['delete_form'].fields)
        self.assertContains(response, f'action="{self.delete_url}"')
        self.assertContains(response, 'Delete my account')

    def test_download_link_only_with_dashboards(self):
        export = reverse('api:v2:documents:export')
        response = self.client.get(self.profile_url)
        self.assertNotContains(response, export)
        self.make_docs()
        response = self.client.get(self.profile_url)
        self.assertContains(response, export)
        self.assertContains(response, 'Download my dashboards')

    def test_wrong_password_keeps_account(self):
        response = self.delete(password='nope')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'account/profile.html')
        self.assertIn('password', response.context['delete_form'].errors)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_unchecked_confirmation_keeps_account(self):
        response = self.client.post(self.delete_url, {'password': PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.assertIn('confirm', response.context['delete_form'].errors)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_delete_removes_documents_and_logs_out(self):
        token = self.make_docs()
        response = self.delete()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/')
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        self.assertFalse(SavedDocument.objects.filter(pk__in=['one', 'two', 'three']).exists())
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertIn(
            'Your account was deleted', [str(m) for m in get_messages(response.wsgi_request)]
        )
        self.assertEqual(Client().get(f'/api/2.0/documents/shared/{token}/').status_code, 404)

    def test_get_delete_url_redirects_to_profile(self):
        response = self.client.get(self.delete_url)
        self.assertRedirects(response, self.profile_url)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_profile_post_never_deletes(self):
        response = self.client.post(self.profile_url, {
            'full_name': 'Renamed', 'email': self.user.email, 'phone': str(self.user.phone),
            'language': 'en', 'password': PASSWORD, 'confirm': 'on',
        })
        self.assertIn(response.status_code, (200, 302))
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_delete_requires_login(self):
        response = Client().post(self.delete_url, {'password': PASSWORD, 'confirm': 'on'})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/account/login/', response['Location'])
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())
