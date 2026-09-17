import pytest
from django.db import IntegrityError, transaction
from django.test import TestCase

from camp.apps.pesticides.models import PesticideUseRollup


class RollupModelTests(TestCase):
    fixtures = ['pesticides-explorer']

    def test_key_is_unique(self):
        kwargs = dict(year=2023, month=3, county_id=9001, mtrs_id=9101, chemical_id=1, product_id=1, commodity_id=1)
        PesticideUseRollup.objects.create(lbs_chemical=1, lbs_product=1, acres_treated=1, applications=1, **kwargs)
        with transaction.atomic(), pytest.raises(IntegrityError):
            PesticideUseRollup.objects.create(lbs_chemical=2, lbs_product=2, acres_treated=2, applications=2, **kwargs)

    def test_null_dimensions_are_part_of_the_key(self):
        kwargs = dict(year=2023, month=0, county_id=9001, mtrs=None, chemical=None, product=None, commodity=None)
        PesticideUseRollup.objects.create(applications=1, **kwargs)
        with transaction.atomic(), pytest.raises(IntegrityError):
            PesticideUseRollup.objects.create(applications=2, **kwargs)

    def test_nullable_dimensions(self):
        row = PesticideUseRollup.objects.create(
            year=2023, month=0, county_id=9001, mtrs=None, chemical=None, product=None, commodity=None,
            lbs_chemical=0, lbs_product=0, acres_treated=0, applications=1,
        )
        assert row.pk
