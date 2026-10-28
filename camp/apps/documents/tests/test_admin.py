from django.contrib import admin
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from camp.api.v2.documents.tests.helpers import make_user, save
from camp.apps.documents.models import (
    BlockedBuild,
    DocumentChange,
    DocumentProfile,
    DocumentSnapshot,
    PurgedDocument,
    SavedDocument,
)

MARKER = 'PRIVATE-MARKER-7f3a9c'


class AdminTests(TestCase):
    def setUp(self):
        cache.clear()
        self.alice = make_user(1)
        self.staff = make_user(2)
        self.staff.is_staff = True
        self.staff.is_superuser = True
        self.staff.save()
        self.client = Client()
        self.client.force_login(self.alice)
        response = save(
            self.client,
            'doc',
            name='Alice board',
            body={'note': MARKER},
            changes=[{'schema_version': 1, 'change': {'text': MARKER}}],
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.doc = SavedDocument.objects.get(pk='doc')
        DocumentSnapshot.objects.create(
            document=self.doc,
            owner=self.alice,
            version=1,
            schema_version=1,
            body={'note': MARKER},
            size=10,
            reason='daily',
        )
        self.admin = Client()
        self.admin.force_login(self.staff)

    def url(self, name, *args, model='saveddocument'):
        return reverse(f'admin:documents_{model}_{name}', args=args)

    def test_change_page_never_shows_body(self):
        assert DocumentChange.objects.filter(document=self.doc).exists()
        urls = [
            self.url('changelist'),
            self.url('changelist') + '?q=doc',
            self.url('change', 'doc'),
            self.url('history', 'doc'),
            self.url('delete', 'doc'),
        ]
        for url in urls:
            response = self.admin.get(url)
            self.assertNotIn(MARKER, response.content.decode(), url)
        self.assertEqual(self.admin.get(self.url('change', 'doc')).status_code, 200)
        self.assertEqual(self.admin.get(self.url('changelist')).status_code, 200)
        self.assertNotEqual(self.admin.get(self.url('delete', 'doc')).status_code, 200)
        self.assertIn('Alice board', self.admin.get(self.url('changelist')).content.decode())

    def test_no_add_or_delete(self):
        self.assertEqual(self.admin.get(self.url('add')).status_code, 403)
        response = self.admin.post(
            self.url('changelist'),
            {'action': 'delete_selected', '_selected_action': ['doc'], 'post': 'yes'},
        )
        self.assertTrue(SavedDocument.objects.filter(pk='doc').exists())
        self.assertNotIn(MARKER, response.content.decode())
        model_admin = admin.site._registry[SavedDocument]
        self.assertNotIn('delete_selected', model_admin.get_actions(response.wsgi_request))

    def test_delete_view_refused_and_link_hidden(self):
        self.assertEqual(self.admin.get(self.url('delete', 'doc')).status_code, 403)
        self.assertEqual(self.admin.post(self.url('delete', 'doc'), {'post': 'yes'}).status_code, 403)
        self.assertTrue(SavedDocument.objects.filter(pk='doc').exists())
        change = self.admin.get(self.url('change', 'doc')).content.decode()
        self.assertNotIn(self.url('delete', 'doc'), change)

    def test_staff_can_delete_user_with_dashboards(self):
        url = reverse('admin:accounts_user_delete', args=[self.alice.pk])
        confirm = self.admin.get(url)
        self.assertEqual(confirm.status_code, 200)
        self.assertNotIn(MARKER, confirm.content.decode())
        self.assertFalse(confirm.context['perms_lacking'])
        response = self.admin.post(url, {'post': 'yes'})
        self.assertEqual(response.status_code, 302, response.content)
        self.assertFalse(type(self.alice).objects.filter(pk=self.alice.pk).exists())
        self.assertFalse(SavedDocument.objects.filter(pk='doc').exists())
        self.assertFalse(DocumentChange.objects.exists())
        self.assertFalse(DocumentSnapshot.objects.exists())

    def test_only_sharing_disabled_is_editable(self):
        response = self.admin.get(self.url('change', 'doc'))
        self.assertEqual(list(response.context['adminform'].form.fields), ['sharing_disabled'])
        self.admin.post(self.url('change', 'doc'), {'sharing_disabled': 'on', 'name': 'Hacked'})
        self.doc.refresh_from_db()
        self.assertTrue(self.doc.sharing_disabled)
        self.assertEqual(self.doc.name, 'Alice board')

    def test_search_fields_are_id_and_owner_email_only(self):
        self.assertEqual(
            list(admin.site._registry[SavedDocument].search_fields), ['id', 'owner__email']
        )

    def test_disable_share_link_action_stops_shared_read(self):
        SavedDocument.objects.filter(pk='doc').update(visibility='link', share_token='tok-abc')
        shared = f'/api/2.0/documents/shared/tok-abc/'
        self.assertEqual(Client().get(shared).status_code, 200)
        self.admin.post(
            self.url('changelist'),
            {'action': 'disable_share_links', '_selected_action': ['doc']},
        )
        self.doc.refresh_from_db()
        self.assertTrue(self.doc.sharing_disabled)
        self.assertEqual(Client().get(shared).status_code, 404)
        self.admin.post(
            self.url('changelist'),
            {'action': 'enable_share_links', '_selected_action': ['doc']},
        )
        self.assertEqual(Client().get(shared).status_code, 200)

    def test_snapshot_and_change_models_not_registered(self):
        for model in (DocumentChange, DocumentSnapshot, PurgedDocument):
            self.assertFalse(admin.site.is_registered(model), model)

    def test_profile_admin_edits_sharing_blocked(self):
        profile = DocumentProfile.objects.create(user=self.alice, display_name='Al')
        response = self.admin.post(
            self.url('change', profile.pk, model='documentprofile'),
            {'user': self.alice.pk, 'display_name': 'Al', 'sharing_blocked': 'on'},
        )
        self.assertEqual(response.status_code, 302, response.content)
        profile.refresh_from_db()
        self.assertTrue(profile.sharing_blocked)

    def test_blocked_build_editable(self):
        response = self.admin.post(
            self.url('add', model='blockedbuild'), {'build_id': 'bad-sha', 'note': 'broken'}
        )
        self.assertEqual(response.status_code, 302, response.content)
        self.assertTrue(BlockedBuild.objects.filter(build_id='bad-sha').exists())
