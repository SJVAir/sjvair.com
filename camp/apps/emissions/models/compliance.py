from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _

from django_sqids import SqidsField, shuffle_alphabet


class AirComplianceFacility(models.Model):
    """
    A Clean Air Act source in EPA's ICIS-Air, as its bulk files describe it.
    `facility` is the CEIDARS facility it was matched to (see icis.parse_pgm_sys_id);
    unmatched rows are kept but never shown.
    """

    class MatchMethod(models.TextChoices):
        PARSED = 'parsed', _('Parsed from the ICIS id')
        MANUAL = 'manual', _('Hand-kept crosswalk')

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.AirComplianceFacility'))
    facility = models.ForeignKey(
        'emissions.Facility', verbose_name=_('Facility'), null=True, blank=True,
        on_delete=models.SET_NULL, related_name='icis_facilities',
    )
    pgm_sys_id = models.CharField(_('ICIS-Air id'), max_length=20, unique=True)
    registry_id = models.CharField(_('FRS registry id'), max_length=12, blank=True)
    name = models.CharField(_('Name'), max_length=128)
    # street, city, county, zip as ICIS gives them.
    address = models.JSONField(_('Address'), default=dict, blank=True)
    pollutant_class = models.CharField(_('Pollutant class'), max_length=32, blank=True)
    operating_status = models.CharField(_('Operating status'), max_length=40, blank=True)
    title_v = models.BooleanField(_('Title V'), default=False)
    current_hpv = models.CharField(_('Current HPV status'), max_length=40, blank=True)
    local_region = models.CharField(_('Local control region'), max_length=8, blank=True)
    match_method = models.CharField(_('Match method'), max_length=8, choices=MatchMethod.choices, blank=True)
    # The newest event date for this facility; the card's five-year window ends here.
    reported_through = models.DateField(_('Reported through'), null=True, blank=True)

    class Meta:
        verbose_name_plural = 'air compliance facilities'

    def __str__(self):
        return f'{self.name} ({self.pgm_sys_id})'

    @property
    def hpv_status(self):
        """'unaddressed', 'addressed' or 'none', from ICIS's CURRENT_HPV text ("Unaddressed-Local", "No Violation Identified")."""
        status = self.current_hpv.lower()
        if status.startswith('unaddressed'):
            return 'unaddressed'
        if status.startswith('addressed'):
            return 'addressed'
        return 'none'

    @property
    def dfr_url(self):
        return f'https://echo.epa.gov/detailed-facility-report?fid={self.registry_id}'


class ComplianceEvent(models.Model):
    """One ICIS-Air event: an inspection, a notice of violation, a formal action or an HPV determination."""

    class Kind(models.TextChoices):
        INSPECTION = 'inspection', _('Inspection')
        NOV = 'nov', _('Notice of violation')
        FORMAL = 'formal', _('Formal action')
        HPV = 'hpv', _('High-priority violation')

    class Agency(models.TextChoices):
        LOCAL = 'L', _('Air district')
        STATE = 'S', _('State')
        EPA = 'E', _('EPA')

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.ComplianceEvent'))
    icis_facility = models.ForeignKey('emissions.AirComplianceFacility', verbose_name=_('ICIS facility'), on_delete=models.CASCADE, related_name='events')
    kind = models.CharField(_('Kind'), max_length=12, choices=Kind.choices)
    date = models.DateField(_('Date'))
    agency = models.CharField(_('Agency'), max_length=1, choices=Agency.choices, blank=True)
    action_type = models.CharField(_('Action type'), max_length=80, blank=True)
    description = models.TextField(_('Description'), blank=True)
    penalty = models.DecimalField(_('Penalty'), max_digits=12, decimal_places=2, null=True, blank=True)
    program = models.CharField(_('Program'), max_length=40, blank=True)
    pollutant = models.CharField(_('Pollutant'), max_length=40, blank=True)
    # HPV only: the day the violation was resolved.
    resolved = models.DateField(_('Resolved'), null=True, blank=True)
    external_id = models.CharField(_('ICIS activity id'), max_length=40)

    class Meta:
        unique_together = [('icis_facility', 'kind', 'external_id')]
        indexes = [models.Index(fields=['icis_facility', 'kind', 'date'])]

    def __str__(self):
        return f'{self.get_kind_display()} {self.date} ({self.icis_facility.pgm_sys_id})'
