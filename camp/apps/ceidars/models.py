import time

import requests

from django.conf import settings
from django.contrib.gis.db import models
from django.contrib.gis.geos import Point

from django_sqids import SqidsField, shuffle_alphabet
from model_utils.models import TimeStampedModel

from camp.utils.geocoding import clean_address


class Facility(TimeStampedModel):
    sqid = SqidsField(alphabet=shuffle_alphabet('ceidars.Facility'))

    county_code = models.IntegerField()
    facid = models.IntegerField()

    metadata_year = models.IntegerField(null=True, blank=True)
    name = models.CharField(max_length=60)
    street = models.CharField(max_length=60, blank=True, default='')
    city = models.CharField(max_length=20, blank=True, default='')
    zipcode = models.CharField(max_length=5, blank=True, default='')
    sic_code = models.IntegerField(null=True, blank=True)

    position = models.PointField(null=True, blank=True)

    class Meta:
        unique_together = [('county_code', 'facid')]

    def __str__(self):
        return f'{self.name} ({self.city})'

    def geocode(self):
        """
        Geocodes the facility address via MapTiler and sets self.position.
        Returns True on success, False if all retries are exhausted.
        Does not save — caller is responsible for saving.

        Uses exponential backoff (up to 5 retries). Sleeps 100ms after a
        successful call to respect MapTiler rate limits during bulk imports.
        """
        query = clean_address(f'{self.street}, {self.city}, CA {self.zipcode}')
        url = f'https://api.maptiler.com/geocoding/{query}.json'
        params = {'key': settings.MAPTILER_API_KEY}

        for attempt in range(5):
            try:
                response = requests.get(url, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()
                if data.get('features'):
                    lon, lat = data['features'][0]['geometry']['coordinates']
                    self.position = Point(lon, lat, srid=4326)
                    time.sleep(0.1)
                    return True
                return False
            except requests.RequestException:
                wait = (2 ** attempt) * 0.5
                time.sleep(wait)

        return False


class EmissionsRecord(TimeStampedModel):
    sqid = SqidsField(alphabet=shuffle_alphabet('ceidars.EmissionsRecord'))
    facility = models.ForeignKey(
        Facility,
        related_name='emissions',
        on_delete=models.CASCADE,
    )
    year = models.IntegerField()

    # Criteria pollutants (tons/yr)
    tog = models.DecimalField(max_digits=25, decimal_places=15, null=True, blank=True)
    rog = models.DecimalField(max_digits=25, decimal_places=15, null=True, blank=True)
    co = models.DecimalField(max_digits=25, decimal_places=15, null=True, blank=True)
    nox = models.DecimalField(max_digits=25, decimal_places=15, null=True, blank=True)
    sox = models.DecimalField(max_digits=25, decimal_places=15, null=True, blank=True)
    pm25 = models.DecimalField(max_digits=25, decimal_places=15, null=True, blank=True)
    pm10 = models.DecimalField(max_digits=25, decimal_places=15, null=True, blank=True)

    # Toxics summary (lbs/yr — blank for all SJV facilities in current CARB exports)
    total_score = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    hra = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    chindex = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    ahindex = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        unique_together = [('facility', 'year')]

    def __str__(self):
        return f'{self.facility.name} ({self.year})'
