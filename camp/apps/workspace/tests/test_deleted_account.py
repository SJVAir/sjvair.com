from django.test import Client, TestCase
from django.urls import reverse

from camp.api.v2.documents.tests.helpers import make_user

from .test_page import identity_of

PASSWORD = 'letmein1'


class DeletedAccountSignalTests(TestCase):
    """
    After an account is deleted, the next /workspace/ page in that browser
    names it once as `deletedAccount`, so the dashboard can drop its space.
    """

    def setUp(self):
        self.user = make_user(1)
        self.client = Client()
        self.client.force_login(self.user)
        self.old_id = identity_of(self.client.get('/workspace/'))['user']['id']

    def delete_account(self):
        response = self.client.post(reverse('account:delete'), {'password': PASSWORD, 'confirm': 'on'})
        assert response.status_code == 302

    def test_first_page_after_deletion_names_the_account_once(self):
        self.delete_account()
        assert identity_of(self.client.get('/workspace/')) == {
            'v': 1, 'user': None, 'deletedAccount': self.old_id,
        }
        assert identity_of(self.client.get('/workspace/')) == {'v': 1, 'user': None}

    def test_signing_in_as_someone_else_keeps_the_signal(self):
        other = make_user(2)
        self.delete_account()
        response = self.client.post(reverse('account:login'), {
            'identifier': other.email, 'password': PASSWORD,
        })
        assert response.status_code == 302
        identity = identity_of(self.client.get('/workspace/'))
        assert set(identity) == {'v', 'user', 'deletedAccount'}
        assert identity['deletedAccount'] == self.old_id
        assert identity['user']['id'] != self.old_id

    def test_normal_sign_out_never_sets_it(self):
        self.client.post(reverse('account:logout'))
        assert identity_of(self.client.get('/workspace/')) == {'v': 1, 'user': None}

    def test_signed_in_page_has_no_signal(self):
        assert 'deletedAccount' not in identity_of(self.client.get('/workspace/'))

    def test_head_request_leaves_the_signal(self):
        # Django routes HEAD to get(); it must not use the flag up.
        self.delete_account()
        assert self.client.head('/workspace/').status_code == 200
        assert identity_of(self.client.get('/workspace/'))['deletedAccount'] == self.old_id

    def test_prefetch_leaves_the_signal(self):
        self.delete_account()
        for headers in (
            {'HTTP_SEC_PURPOSE': 'prefetch'},
            {'HTTP_SEC_PURPOSE': 'prefetch;prerender'},
            {'HTTP_PURPOSE': 'prefetch'},
            {'HTTP_X_MOZ': 'prefetch'},
        ):
            prefetched = identity_of(self.client.get('/workspace/', **headers))
            assert prefetched['deletedAccount'] == self.old_id, headers
        assert identity_of(self.client.get('/workspace/'))['deletedAccount'] == self.old_id
        assert 'deletedAccount' not in identity_of(self.client.get('/workspace/'))
