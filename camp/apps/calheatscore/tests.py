import pytest
from django.test import TestCase

from camp.apps.calheatscore.models import CalHeatScore


class CalHeatScoreModelTests(TestCase):
    fixtures = ['regions', 'calheatscore']

    def test_str(self):
        record = CalHeatScore.objects.get(pk=1)
        assert '93728' in str(record)
        assert '2026-07-11' in str(record)
        assert 'Moderate' in str(record)

    def test_score_display(self):
        record = CalHeatScore.objects.get(pk=1)
        assert record.get_score_display() == 'Moderate'

    def test_region_relation(self):
        record = CalHeatScore.objects.get(pk=1)
        assert record.region.external_id == '93728'

    def test_reverse_related_name(self):
        record = CalHeatScore.objects.get(pk=1)
        assert record in record.region.heat_scores.all()

    def test_unique_region_date_constraint(self):
        from django.db import IntegrityError

        with pytest.raises(IntegrityError):
            CalHeatScore.objects.create(region_id=11, date='2026-07-11', score=0)

    def test_ordering_is_newest_first(self):
        records = list(CalHeatScore.objects.filter(region_id=11))
        dates = [r.date for r in records]
        assert dates == sorted(dates, reverse=True)
