import json
import re

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import resolve

from camp.api.v2.accounts.serializers import get_token

User = get_user_model()

IDENTITY_RE = re.compile(r'<script id="sjvair-identity" type="application/json">(.*?)</script>', re.S)


def identity_of(response):
    return json.loads(IDENTITY_RE.search(response.content.decode()).group(1))


class WorkspacePageTests(TestCase):
    """The dashboard page at /workspace/* (test settings run with the beta gate off)."""

    def test_both_slash_forms_and_deep_paths_render(self):
        for url in ['/workspace', '/workspace/', '/workspace/dashboards/abc',
                    '/workspace/dashboards/a%20b', '/workspace?x=1']:
            response = self.client.get(url)
            assert response.status_code == 200, url
            assert 'Location' not in response, url

    def test_workspacefoo_is_not_the_workspace(self):
        from camp.apps.workspace.views import WorkspacePage
        assert resolve('/workspace').func.view_class is WorkspacePage
        assert getattr(resolve('/workspacefoo').func, 'view_class', None) is not WorkspacePage

    def test_template_is_bare(self):
        html = self.client.get('/workspace/').content.decode()
        assert '<div id="SJVAirDataDashboard"></div>' in html
        assert 'id="sjvair-identity"' in html
        assert '<script type="module" src="/static/workspace/app.js">' in html
        assert 'href="/static/workspace/app.css"' in html
        assert 'href="/workspace/manifest.webmanifest"' in html
        assert '<title>SJVAir Dashboard</title>' in html
        assert 'favicon.ico' in html
        for chrome in ['googletagmanager', 'gtag', 'bulma', 'navbar']:
            assert chrome not in html.lower(), chrome
        for tag in re.findall(r'<script[^>]*>', html):
            assert ('type="module"' in tag and 'src=' in tag) or 'type="application/json"' in tag, tag

    def test_headers(self):
        response = Client().get('/workspace/')
        assert 'no-store' in response['Cache-Control']
        assert response['X-Frame-Options'] == 'DENY'
        assert 'csrftoken' in response.cookies
        assert 'X-Robots-Tag' not in response

    def test_shared_pages_are_noindex(self):
        for url in ['/workspace/shared', '/workspace/shared/abc']:
            assert self.client.get(url)['X-Robots-Tag'] == 'noindex', url
        assert 'X-Robots-Tag' not in self.client.get('/workspace/sharedx')

    def test_methods(self):
        assert self.client.head('/workspace/').status_code == 200
        assert self.client.post('/workspace/').status_code == 405

    def test_identity_anonymous(self):
        assert identity_of(self.client.get('/workspace/')) == {'v': 1, 'user': None}

    def test_identity_signed_in(self):
        user = User.objects.create_user(
            None, 'letmein1', full_name='Ana </script> B', phone='559-555-0111', phone_verified=True,
        )
        token = get_token(user)
        self.client.force_login(user)
        response = self.client.get('/workspace/')
        assert identity_of(response) == {'v': 1, 'user': {
            'id': str(user.pk),
            'name': 'Ana </script> B',
            'email': None,
            'emailVerified': False,
            'phoneVerified': True,
        }}
        html = response.content.decode()
        assert token and token not in html
        assert '5550111' not in html and '555-0111' not in html
        assert '\\u003C/script\\u003E' in html
