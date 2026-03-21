from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _

from django_sqids import SqidsField, shuffle_alphabet
from model_utils.models import TimeStampedModel

from camp.utils import geocode as _geocode


class FacilityManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().select_related('county', 'zipcode', 'city')


class Facility(TimeStampedModel):
    objects = FacilityManager()
    sqid = SqidsField(alphabet=shuffle_alphabet('ceidars.Facility'))

    county_code = models.IntegerField(_('County code'))
    facid = models.IntegerField(_('Facility ID'))

    metadata_year = models.IntegerField(_('Metadata year'), null=True, blank=True)
    name = models.CharField(_('Name'), max_length=60)
    sic_code = models.IntegerField(_('SIC code'), null=True, blank=True)

    # Raw address fields from CEIDARS — preserved as-is for reference.
    # City names in particular are noisy (typos, non-city strings, county
    # names) so matching against Region is handled separately via the FKs.
    address = models.JSONField(_('Address'), default=dict, blank=True)

    # Region FKs — populated at import time from address data.
    # county is always set (deterministic from county_code).
    # zipcode and city may be null for PO Box ZIPs (no ZCTA polygon exists)
    # or unresolvable city strings.
    county = models.ForeignKey(
        'regions.Region',
        verbose_name=_('County'),
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='county_facilities',
    )
    zipcode = models.ForeignKey(
        'regions.Region',
        verbose_name=_('Zipcode'),
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='zipcode_facilities',
    )
    city = models.ForeignKey(
        'regions.Region',
        verbose_name=_('City'),
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='city_facilities',
    )

    point = models.PointField(_('Point'), null=True, blank=True)

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
    year = models.IntegerField(_('Year'))

    # Criteria pollutants (tons/yr)
    tog = models.DecimalField(_('TOG'), max_digits=25, decimal_places=15, null=True, blank=True)
    rog = models.DecimalField(_('ROG'), max_digits=25, decimal_places=15, null=True, blank=True)
    co = models.DecimalField(_('CO'), max_digits=25, decimal_places=15, null=True, blank=True)
    nox = models.DecimalField(_('NOx'), max_digits=25, decimal_places=15, null=True, blank=True)
    sox = models.DecimalField(_('SOx'), max_digits=25, decimal_places=15, null=True, blank=True)
    pm25 = models.DecimalField(_('PM2.5'), max_digits=25, decimal_places=15, null=True, blank=True)
    pm10 = models.DecimalField(_('PM10'), max_digits=25, decimal_places=15, null=True, blank=True)

    # Toxics summary (blank for all SJV facilities in current CARB exports)
    total_score = models.DecimalField(_('Total score'), max_digits=10, decimal_places=2, null=True, blank=True)
    hra = models.DecimalField(_('HRA'), max_digits=10, decimal_places=2, null=True, blank=True)
    chindex = models.DecimalField(_('Cancer health index'), max_digits=10, decimal_places=2, null=True, blank=True)
    ahindex = models.DecimalField(_('Acute health index'), max_digits=10, decimal_places=2, null=True, blank=True)

    # Named toxic air contaminants (tons/yr)
    acetaldehyde = models.DecimalField(_('Acetaldehyde'), max_digits=25, decimal_places=15, null=True, blank=True)
    benzene = models.DecimalField(_('Benzene'), max_digits=25, decimal_places=15, null=True, blank=True)
    butadiene = models.DecimalField(_('1,3-Butadiene'), max_digits=25, decimal_places=15, null=True, blank=True)
    carbon_tetrachloride = models.DecimalField(_('Carbon tetrachloride'), max_digits=25, decimal_places=15, null=True, blank=True)
    chromium_hexavalent = models.DecimalField(_('Chromium (hexavalent)'), max_digits=25, decimal_places=15, null=True, blank=True)
    dichlorobenzene = models.DecimalField(_('para-Dichlorobenzene'), max_digits=25, decimal_places=15, null=True, blank=True)
    formaldehyde = models.DecimalField(_('Formaldehyde'), max_digits=25, decimal_places=15, null=True, blank=True)
    methylene_chloride = models.DecimalField(_('Methylene chloride'), max_digits=25, decimal_places=15, null=True, blank=True)
    naphthalene = models.DecimalField(_('Naphthalene'), max_digits=25, decimal_places=15, null=True, blank=True)
    perchloroethylene = models.DecimalField(_('Perchloroethylene'), max_digits=25, decimal_places=15, null=True, blank=True)

    class Meta:
        unique_together = [('facility', 'year')]

    def __str__(self):
        return f'{self.facility.name} ({self.year})'
