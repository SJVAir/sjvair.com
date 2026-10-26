import json
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import resolve

from camp.apps.workspace import manifest

MANIFEST = {
    'name': 'SJVAir Dashboard',
    'start_url': '/workspace/',
    'scope': '/workspace/',
    'icons': [
        {'src': 'assets/icon-192-abc.png', 'sizes': '192x192', 'type': 'image/png'},
        {'src': 'https://cdn.example/x.png', 'sizes': '512x512', 'type': 'image/png'},
    ],
}
URL = '/workspace/manifest.webmanifest'


class WorkspaceManifestTests(TestCase):
    def setUp(self):
        manifest.clear_cache()
        self.dist = Path(tempfile.mkdtemp())
        self.settings_override = override_settings(WORKSPACE_DIST_DIR=str(self.dist))
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)

    def write(self, content):
        (self.dist / 'manifest.webmanifest').write_text(content)

    def test_serves_manifest_with_static_icon_urls(self):
        self.write(json.dumps(MANIFEST))
        response = self.client.get(URL)
        assert response.status_code == 200
        assert response['Content-Type'] == 'application/manifest+json'
        data = json.loads(response.content)
        assert data['icons'][0]['src'] == '/static/workspace/assets/icon-192-abc.png'
        assert data['icons'][1]['src'] == 'https://cdn.example/x.png'
        assert data['start_url'] == '/workspace/'
        assert data['scope'] == '/workspace/'
        assert data['name'] == 'SJVAir Dashboard'

    def test_missing_manifest_is_404(self):
        with self.assertLogs('camp.apps.workspace.manifest', 'ERROR'):
            assert self.client.get(URL).status_code == 404

    def test_invalid_json_is_404(self):
        self.write('{not json')
        with self.assertLogs('camp.apps.workspace.manifest', 'ERROR'):
            assert self.client.get(URL).status_code == 404

    def test_miss_is_not_cached(self):
        with self.assertLogs('camp.apps.workspace.manifest', 'ERROR'):
            assert self.client.get(URL).status_code == 404
        self.write(json.dumps(MANIFEST))
        assert self.client.get(URL).status_code == 200

    def test_not_shadowed_by_page_route(self):
        assert resolve(URL).url_name == 'workspace-manifest'

    def test_head_and_post(self):
        self.write(json.dumps(MANIFEST))
        assert self.client.head(URL).status_code == 200
        assert self.client.post(URL).status_code == 405
