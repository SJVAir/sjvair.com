from unittest import mock
from zoneinfo import ZoneInfo

import pytest

from django.conf import settings
from django.utils import timezone

from camp.utils.test.twilio_test_client import TwilioTestClient


@pytest.fixture(autouse=True)
def set_timezone_pacific():
    timezone.activate(settings.DEFAULT_TIMEZONE)
    yield
    timezone.deactivate()


@pytest.fixture(scope='session', autouse=True)
def default_session_fixture(request):
    patches = [
        mock.patch('twilio.rest.Client', TwilioTestClient),
    ]

    for patch in patches:
        patch.start()

    request.addfinalizer(mock.patch.stopall)
