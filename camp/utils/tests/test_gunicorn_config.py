import sys

from unittest import mock

import pytest

from django.test import SimpleTestCase
from gunicorn.app.wsgiapp import run


class GunicornConfigTests(SimpleTestCase):
    def test_config(self):
        argv = [
            'gunicorn',
            '--check-config',
            '--config',
            'gunicorn-config.py',
            'camp.wsgi:application',
        ]
        mock_argv = mock.patch.object(sys, 'argv', argv)

        with pytest.raises(SystemExit) as excinfo, mock_argv:
            run()

        exit_code = excinfo.value.args[0]
        assert exit_code == 0
