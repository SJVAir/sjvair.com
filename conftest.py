from unittest import mock
from zoneinfo import ZoneInfo

import pytest

from django.conf import settings
from django.core.management import call_command
from django.utils import timezone

from camp.apps.monitors.purpleair.models import PurpleAir
from camp.utils.test.helpers import create_hourly_data_for_monitor
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


@pytest.fixture(scope='module')
def purpleair_monitor(django_db_setup, django_db_blocker):
    print('[fixture] Loading purple-air.yaml and getting PurpleAir(8892)')
    with django_db_blocker.unblock():
        call_command('loaddata', 'purple-air.yaml', verbosity=0)
        call_command('loaddata', 'bam1022.yaml', verbosity=0)
        monitor = PurpleAir.objects.get(purple_id=8892)
        create_hourly_data_for_monitor(monitor)
        try:
            yield
        finally:
            monitor.delete()
