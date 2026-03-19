from django.contrib.gis.db import models

from django_sqids import SqidsField, shuffle_alphabet
from model_utils.models import TimeStampedModel

from camp.utils import geocode as _geocode


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
        Geocodes the facility address, trying Census first then MapTiler.
        Sets self.position on success. Returns True/False. Does not save.
        """
        address = f'{self.street}, {self.city}, CA {self.zipcode}'
        position = _geocode.census(address) or _geocode.maptiler(address)
        if position:
            self.position = position
            return True
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
