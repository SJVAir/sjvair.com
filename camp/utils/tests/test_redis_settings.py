from django.conf import settings
from django.test import SimpleTestCase

from camp.settings.base import redis_connection


class RedisConnectionTests(SimpleTestCase):
    def test_no_url_keeps_default_localhost(self):
        assert redis_connection(None) == {'url': None}

    def test_pool_options_for_tls_url(self):
        conn = redis_connection('rediss://u:p@example.com:6380/0?ssl_cert_reqs=none')
        pool = conn['connection_pool']
        kw = pool.connection_kwargs
        assert kw['health_check_interval'] == 30
        assert kw['socket_keepalive'] is True
        assert kw['retry'].get_retries() == 3
        assert kw['db'] == 0

    def test_plain_url(self):
        pool = redis_connection('redis://queue:6379/2')['connection_pool']
        assert pool.connection_kwargs['db'] == 2
        assert pool.connection_kwargs['host'] == 'queue'
