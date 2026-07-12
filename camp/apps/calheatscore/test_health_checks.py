from datetime import timedelta
from unittest.mock import patch

import pytest
from django.test import TestCase
from django.utils import timezone

from health_check.exceptions import ServiceWarning

from camp.apps.calheatscore.health_checks import CalHeatScoreHealthCheck
from camp.apps.calheatscore.models import CalHeatScore


class CalHeatScoreHealthCheckTests(TestCase):
    fixtures = ['regions']

    def test_raises_when_no_entries_exist(self):
        check = CalHeatScoreHealthCheck()

        with pytest.raises(ServiceWarning):
            check.run()

    def test_passes_when_recently_updated(self):
        CalHeatScore.objects.create(region_id=11, date=timezone.now().date(), score=2)

        check = CalHeatScoreHealthCheck()
        check.run()

    def test_raises_when_stale(self):
        record = CalHeatScore.objects.create(region_id=11, date=timezone.now().date(), score=2)
        stale = timezone.now() - timedelta(hours=28)
        CalHeatScore.objects.filter(pk=record.pk).update(updated_at=stale)

        check = CalHeatScoreHealthCheck()
        with pytest.raises(ServiceWarning):
            check.run()

    def test_labels_identify_the_check(self):
        check = CalHeatScoreHealthCheck()
        assert check.labels == {'check': 'CalHeatScore'}

    def test_repr_identifies_the_check(self):
        check = CalHeatScoreHealthCheck()
        assert repr(check) == 'CalHeatScore'
