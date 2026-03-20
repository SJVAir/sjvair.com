from django.contrib.gis.db import models

from django_sqids import SqidsField, shuffle_alphabet
from model_utils.models import TimeStampedModel

from camp.utils import geocode as _geocode


class FacilityManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().select_related('county', 'zipcode', 'city')


class Facility(TimeStampedModel):
    objects = FacilityManager()
    sqid = SqidsField(alphabet=shuffle_alphabet('ceidars.Facility'))

    county_code = models.IntegerField()
    facid = models.IntegerField()

    metadata_year = models.IntegerField(null=True, blank=True)
    name = models.CharField(max_length=60)
    sic_code = models.IntegerField(null=True, blank=True)

    # Raw address fields from CEIDARS — preserved as-is for reference.
    # City names in particular are noisy (typos, non-city strings, county
    # names) so matching against Region is handled separately via the FKs.
    address = models.JSONField(default=dict, blank=True)

    # Region FKs — populated at import time from address data.
    # county is always set (deterministic from county_code).
    # zipcode and city may be null for PO Box ZIPs (no ZCTA polygon exists)
    # or unresolvable city strings.
    county = models.ForeignKey(
        'regions.Region',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='county_facilities',
    )
    zipcode = models.ForeignKey(
        'regions.Region',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='zipcode_facilities',
    )
    city = models.ForeignKey(
        'regions.Region',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='city_facilities',
    )

    point = models.PointField(null=True, blank=True)

    class Meta:
        unique_together = [('county_code', 'facid')]

    def __str__(self):
        return f'{self.name} ({self.address.get("city", "")})'

    def get_county(self):
        return self.county.name if self.county_id else None

    def get_city(self):
        return self.city.name if self.city_id else self.address.get('city', '')

    def get_zipcode(self):
        return self.zipcode.name if self.zipcode_id else self.address.get('zipcode', '')

    def geocode(self):
        """
        Geocodes the facility address, trying Census first then MapTiler.
        Sets self.point on success. Returns True/False. Does not save.
        """
        street = self.address.get('street', '')
        city = self.address.get('city', '')
        zipcode = self.address.get('zipcode', '')
        point = _geocode.resolve(f'{street}, {city}, CA {zipcode}')
        if point:
            self.point = point
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
