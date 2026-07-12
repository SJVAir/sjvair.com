import json

from django.test import RequestFactory, TestCase
from django.urls import resolve


class OpenAPISchemaTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        request = self.factory.get('/api/2.0/openapi.json')
        match = resolve('/api/2.0/openapi.json')
        response = match.func(request, **match.kwargs)
        self.schema = json.loads(response.content)
        self.paths = self.schema['paths']

    def test_schema_is_openapi_3_1(self):
        assert self.schema['openapi'] == '3.1.0'

    def test_schema_has_info(self):
        assert self.schema['info']['title'] == 'SJVAir API'
        assert self.schema['info']['version'] == '2.0'

    def test_schema_has_servers(self):
        assert self.schema['servers'] == [{'url': '/api/2.0/'}]

    def test_schema_has_security_schemes(self):
        assert 'sessionAuth' in self.schema['components']['securitySchemes']

    def test_monitor_list_is_documented(self):
        assert any('monitors' in p and p.endswith('monitors/') for p in self.paths)

    def test_monitor_detail_is_documented(self):
        assert any('{monitor_id}' in p and p.endswith('{monitor_id}/') for p in self.paths)

    def test_entry_list_is_documented(self):
        assert any('{entry_type}' in p and 'entries' in p for p in self.paths)

    def test_monitor_current_is_documented(self):
        assert any(p.endswith('{entry_type}/current/') for p in self.paths)

    def test_monitor_at_is_documented(self):
        assert any(p.endswith('{entry_type}/at/') for p in self.paths)
        description = self.paths['/monitors/{entry_type}/at/']['get']['description']
        assert 'timestamp' in description
        assert 'region' in description
        assert 'bbox' in description

    def test_task_status_is_not_documented(self):
        assert not any('task' in p for p in self.paths)

    def test_create_entry_path_not_documented(self):
        # CreateEntry is documented=False; its path ends in /entries/ with no {entry_type}
        assert not any(
            p.endswith('/entries/') and '{entry_type}' not in p
            for p in self.paths
        )

    def test_subscription_list_is_not_documented(self):
        assert not any('subscriptions' in p for p in self.paths)

    def test_account_endpoints_are_not_documented(self):
        assert not any('account' in p for p in self.paths)

    def test_pesticides_endpoints_are_documented(self):
        assert any('pesticides' in p and p.endswith('chemicals/') for p in self.paths)
        assert any('pesticides' in p and p.endswith('commodities/') for p in self.paths)
        assert any('pesticides' in p and p.endswith('products/') for p in self.paths)
        assert any('pesticides' in p and p.endswith('use/') for p in self.paths)
        assert any('pesticides' in p and p.endswith('notice/') for p in self.paths)
        assert any('pesticides' in p and 'summary' in p for p in self.paths)

    def test_ces4_paths_are_documented(self):
        assert any(p.endswith('calenviroscreen/4.0/') for p in self.paths)
        assert any(p.endswith('calenviroscreen/4.0/{tract}/') for p in self.paths)

    def test_ces4_year_query_param_is_documented(self):
        list_params = self.paths['/calenviroscreen/4.0/']['get']['parameters']
        assert any(p['name'] == 'year' for p in list_params)
        detail_params = self.paths['/calenviroscreen/4.0/{tract}/']['get']['parameters']
        assert any(p['name'] == 'year' for p in detail_params)
