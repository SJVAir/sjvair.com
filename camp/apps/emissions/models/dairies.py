from django.contrib.gis.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from django_sqids import SqidsField, shuffle_alphabet
from model_utils.models import TimeStampedModel


# CADD's reference code for a count that was reported; every other code
# (2a-2f, 3a-3g) marks one of CARB's estimates or gap fills.
REPORTED_REF_CODE = '1'

MATURE_DAIRY_FIELDS = ('milk_cows', 'dry_cows')
OTHER_CATTLE_FIELDS = ('old_heifers', 'young_heifers', 'old_calves', 'young_calves', 'beef_cattle')
HERD_FIELDS = MATURE_DAIRY_FIELDS + OTHER_CATTLE_FIELDS

# EPA's CAFO size thresholds for dairy cattle, in head (40 CFR 122.23(b)(4),(6)):
# a Large CAFO has 700 or more mature dairy cows (milking or dry) or 1,000 or
# more other cattle (heifers, calves, beef); a Medium one 200-699 mature dairy
# cows or 300-999 other cattle. The larger class wins.
LARGE_MATURE_COWS = 700
LARGE_OTHER_CATTLE = 1000
MEDIUM_MATURE_COWS = 200
MEDIUM_OTHER_CATTLE = 300


class SizeClass(models.TextChoices):
    """A dairy's EPA size class in one year (40 CFR 122.23(b)(4),(6))."""
    LARGE = 'large', _('Large')
    MEDIUM = 'medium', _('Medium')
    SMALL = 'small', _('Small')


def size_class(mature_cows, other_cattle):
    """
    The EPA size class of a herd of `mature_cows` and `other_cattle`, the
    larger of the two counts' classes; '' for a herd with no cattle.
    """
    if mature_cows >= LARGE_MATURE_COWS or other_cattle >= LARGE_OTHER_CATTLE:
        return SizeClass.LARGE
    if mature_cows >= MEDIUM_MATURE_COWS or other_cattle >= MEDIUM_OTHER_CATTLE:
        return SizeClass.MEDIUM
    if mature_cows + other_cattle > 0:
        return SizeClass.SMALL
    return ''


def herd_totals(counts):
    """
    {mature_cows, other_cattle, size_class} from {herd field: count}; a blank
    (None) count is unknown and left out of the sums.
    """
    mature = sum(counts.get(field) or 0 for field in MATURE_DAIRY_FIELDS)
    other = sum(counts.get(field) or 0 for field in OTHER_CATTLE_FIELDS)
    return {'mature_cows': mature, 'other_cattle': other, 'size_class': size_class(mature, other)}


class Dairy(TimeStampedModel):
    """
    A dairy in CARB's California Dairy & Livestock Database (CADD): where it
    is. Its herd by year is DairyHerd, its anaerobic digesters Digester.
    Nothing here is an emission estimate.
    """

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.Dairy'))
    cadd_id = models.IntegerField(_('CADD ID'), unique=True)
    place_id = models.IntegerField(_('Place ID'))
    name = models.CharField(_('Name'), max_length=128)
    # As CADD gives it: street, zipcode. address['city'] is normalized at
    # import: known misspellings/non-city values fixed, then matched against
    # a CITY or CDP Region's name case-insensitively, else title-cased
    # (see camp.apps.emissions.cities).
    address = models.JSONField(_('Address'), default=dict, blank=True)
    point = models.PointField(_('Point'))
    # Resolved from CADD's county name at import.
    county = models.ForeignKey(
        'regions.Region',
        verbose_name=_('County'),
        on_delete=models.PROTECT,
        related_name='dairies',
    )
    water_board = models.CharField(_('Regional water board'), max_length=8, blank=True)
    cadd_version = models.CharField(_('CADD version'), max_length=16)

    class Meta:
        verbose_name_plural = 'dairies'

    def __str__(self):
        return f'{self.name} ({self.address.get("city", "")})'


class DairyHerd(models.Model):
    """One dairy's herd in one year, as CADD counts it. A blank count is unknown, not zero."""

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.DairyHerd'))
    dairy = models.ForeignKey('emissions.Dairy', verbose_name=_('Dairy'), on_delete=models.CASCADE, related_name='herds')
    year = models.IntegerField(_('Year'))
    milk_cows = models.IntegerField(_('Milk cows'), null=True, blank=True)
    dry_cows = models.IntegerField(_('Dry cows'), null=True, blank=True)
    old_heifers = models.IntegerField(_('Heifers (older)'), null=True, blank=True)
    young_heifers = models.IntegerField(_('Heifers (younger)'), null=True, blank=True)
    old_calves = models.IntegerField(_('Calves (older)'), null=True, blank=True)
    young_calves = models.IntegerField(_('Calves (younger)'), null=True, blank=True)
    beef_cattle = models.IntegerField(_('Beef cattle'), null=True, blank=True)
    # The milk cows' code, and the one for every other class.
    milk_cows_ref_code = models.CharField(_('Milk cows reference code'), max_length=8, blank=True)
    non_milking_ref_code = models.CharField(_('Non-milking cattle reference code'), max_length=8, blank=True)
    labeled_as_dairy = models.BooleanField(_('Labeled as dairy'), default=False)
    # Computed at import from the counts that aren't blank (herd_totals()).
    mature_cows = models.PositiveIntegerField(_('Mature dairy cows'), default=0)
    other_cattle = models.PositiveIntegerField(_('Other cattle'), default=0)
    # Blank for a herd with no cattle counted.
    size_class = models.CharField(_('EPA size class'), max_length=8, choices=SizeClass.choices, blank=True)

    class Meta:
        unique_together = [('dairy', 'year')]
        indexes = [
            models.Index(fields=['year', 'dairy']),
        ]

    def __str__(self):
        return f'{self.dairy.name} ({self.year})'

    def estimated(self, field):
        """Whether CARB estimated this class's count rather than it being reported."""
        code = self.milk_cows_ref_code if field == 'milk_cows' else self.non_milking_ref_code
        return code != REPORTED_REF_CODE


class DigesterQuerySet(models.QuerySet):
    def operating_in(self, year):
        """
        Operating in `year`: started by then, or its start year is unknown,
        and not shut down by then.
        """
        return self.filter(
            Q(operational_year__isnull=True) | Q(operational_year__lte=year)
        ).filter(Q(shutdown_year__isnull=True) | Q(shutdown_year__gt=year))


class Digester(models.Model):
    """An anaerobic digester at a dairy, per CADD."""

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.Digester'))
    dairy = models.ForeignKey('emissions.Dairy', verbose_name=_('Dairy'), on_delete=models.CASCADE, related_name='digesters')
    # Blank for a handful of CADD's AgSTAR rows that carry no start year.
    operational_year = models.IntegerField(_('Operational year'), null=True, blank=True)
    shutdown_year = models.IntegerField(_('Shutdown year'), null=True, blank=True)
    # DDRDP, AgSTAR or LCFS.
    source = models.CharField(_('Data source'), max_length=16, blank=True)

    objects = DigesterQuerySet.as_manager()

    def __str__(self):
        return f'{self.dairy.name} digester ({self.operational_year})'

    def operating_in(self, year):
        return (self.operational_year is None or self.operational_year <= year) \
            and (self.shutdown_year is None or self.shutdown_year > year)


class DigesterGrant(models.Model):
    """
    A CDFA Dairy Digester Research and Development Program (DDRDP) grant,
    from CDFA's project-level PDF: the dairy, the developer, the award, the
    biogas end use and CDFA's estimate of the annual reduction. Matched to a
    Dairy by normalised name and city, then by ddrdp_crosswalk; unmatched
    rows are kept (their county still counts them). The reduction is CDFA's
    claim, shown as such.
    """

    class Match(models.TextChoices):
        AUTO = 'auto', _('Name and city')
        MANUAL = 'manual', _('Crosswalk')

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.DigesterGrant'))
    dairy = models.ForeignKey(
        'emissions.Dairy', verbose_name=_('Dairy'), null=True, blank=True,
        on_delete=models.SET_NULL, related_name='grants',
    )
    project_name = models.CharField(_('Project'), max_length=128)
    dairy_name = models.CharField(_('Dairy name'), max_length=128)
    city = models.CharField(_('City'), max_length=64, blank=True)
    county = models.CharField(_('County'), max_length=32, blank=True)
    developer = models.CharField(_('Developer'), max_length=128, blank=True)
    grant_amount = models.DecimalField(_('Grant amount'), max_digits=12, decimal_places=2, null=True, blank=True)
    end_use = models.CharField(_('Biogas end use'), max_length=64, blank=True)
    est_reduction_tco2e = models.FloatField(_('Estimated reduction (t CO2e/yr)'), null=True, blank=True)
    awarded = models.DateField(_('Awarded'), null=True, blank=True)
    operational = models.DateField(_('Operational'), null=True, blank=True)
    match_method = models.CharField(_('Match method'), max_length=8, choices=Match.choices, blank=True)

    class Meta:
        ordering = ['-awarded', 'dairy_name']

    def __str__(self):
        return f'{self.project_name} ({self.dairy_name})'
