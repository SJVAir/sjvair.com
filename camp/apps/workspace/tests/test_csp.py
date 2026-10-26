import json
from pathlib import Path

from django.test import TestCase, override_settings

from camp.apps.workspace.csp import build_policy

HOSTS = json.loads((Path(__file__).parent.parent / 'csp-hosts.json').read_text())
ENFORCED = 'Content-Security-Policy'
REPORT_ONLY = 'Content-Security-Policy-Report-Only'


def parse(policy):
    return {
        name: sources
        for name, *sources in (part.split() for part in policy.split(';') if part.strip())
    }


class BuildPolicyTests(TestCase):
    def test_policy_matches_the_host_list(self):
        static = 'https://bucket.example/static/workspace/'
        expected = {k: [static if s == '{static}' else s for s in v] for k, v in HOSTS.items()}
        parsed = parse(build_policy('https://bucket.example/static/'))
        assert parsed == expected
        assert list(parsed) == list(HOSTS)

    def test_bare_static_path_is_dropped(self):
        policy = build_policy('/static/')
        assert '/static/' not in policy
        assert '{static}' not in policy
        assert parse(policy)['script-src'] == ["'self'"]
        assert parse(policy)['font-src'] == ["'self'"]

    def test_report_uri_only_when_set(self):
        assert build_policy('/static/', 'https://r.example/x').endswith('report-uri https://r.example/x')
        assert 'report-uri' not in build_policy('/static/', '')


class WorkspaceCspHeaderTests(TestCase):
    @override_settings(WORKSPACE_CSP_ENFORCE=True)
    def test_view_enforces_when_set(self):
        response = self.client.get('/workspace/')
        assert "default-src 'none'" in response[ENFORCED]
        assert REPORT_ONLY not in response

    @override_settings(WORKSPACE_CSP_ENFORCE=False)
    def test_view_reports_only_when_off(self):
        response = self.client.get('/workspace/')
        assert "default-src 'none'" in response[REPORT_ONLY]
        assert ENFORCED not in response

    @override_settings(WORKSPACE_CSP_REPORT_URI='https://r.example/x')
    def test_view_adds_the_report_uri(self):
        response = self.client.get('/workspace/')
        assert 'report-uri https://r.example/x' in (response.get(ENFORCED) or response[REPORT_ONLY])

    def test_no_csp_outside_workspace(self):
        response = self.client.get('/about/')
        assert ENFORCED not in response and REPORT_ONLY not in response
