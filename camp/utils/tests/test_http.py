import tempfile

from pathlib import Path
from unittest import mock

import pytest
import requests
from django.test import SimpleTestCase

from camp.utils.http import stream_to_disk


class StreamToDiskTests(SimpleTestCase):
    def setUp(self):
        self.dest = Path(tempfile.mkdtemp()) / 'data.zip'

    def response(self, content_type, body):
        response = requests.Response()
        response.status_code = 200
        response.headers['Content-Type'] = content_type
        response.raw = mock.Mock(stream=mock.Mock(return_value=iter([body])))
        return response

    def test_html_response_is_rejected_and_not_written(self):
        # Census's WAF answers with a 200 "Request Rejected" HTML page, which a
        # CDN can then cache under the dataset's URL.
        page = self.response('text/html; charset=utf-8', b'<html>Request Rejected</html>')
        with mock.patch('requests.Session.get', return_value=page):
            with pytest.raises(ValueError, match='HTML'):
                stream_to_disk('https://example.com/data.zip', self.dest)
        assert not self.dest.exists()
        assert not self.dest.with_suffix('.zip.part').exists()

    def test_file_response_is_written(self):
        page = self.response('application/zip', b'PK\x03\x04')
        with mock.patch('requests.Session.get', return_value=page):
            stream_to_disk('https://example.com/data.zip', self.dest)
        assert self.dest.read_bytes() == b'PK\x03\x04'
