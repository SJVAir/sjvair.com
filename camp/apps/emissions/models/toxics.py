from django.contrib.gis.db import models
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from django_sqids import SqidsField, shuffle_alphabet


# CARB's toxicity weighting, reverse-engineered from its Pollution Mapping
# Tool and reproduced to within 0.01% on 91 carcinogens (research:
# .superpowers/research/toxics.md, section 2). Cancer weight per pound is
# the inhalation unit risk × the molecular-weight adjustment factor × 7,700;
# chronic and acute weights are a constant over the reference exposure level.
CANCER_SCALE = 7700.0
CHRONIC_SCALE = 0.01712
ACUTE_SCALE = 0.1712
# Ammonia: CARB delivers it in the toxics feed, but it's a PM2.5 precursor,
# not a toxic; stored under kind='precursor', never weighted or listed as one.
PRECURSOR_IDS = frozenset({'7664417'})
# "PAHs, total, with individual components also reported" -- weighting it
# would count the components twice.
UNWEIGHTED_IDS = frozenset({'1150'})
# The toxics picker's own keys; a pollutant slug can't be one of them.
RESERVED_SLUGS = frozenset({'cancer', 'chronic'})


class ToxicPollutant(models.Model):
    """
    A pollutant in CARB's toxics inventory: a CAS number without dashes
    ('71432', benzene) or one of CARB's own 4-digit codes ('9901', diesel
    PM), with the OEHHA health values from the Consolidated Table and the
    per-pound weights derived from them. Rows exist for every table entry
    and for every id a facility has reported, whether or not both.
    """

    class Kind(models.TextChoices):
        TOXIC = 'toxic', _('Toxic air contaminant')
        PRECURSOR = 'precursor', _('Precursor')

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.ToxicPollutant'))
    carb_id = models.CharField(_('CARB pollutant ID'), max_length=12, unique=True)
    cas_number = models.CharField(_('CAS number'), max_length=16, blank=True)
    name = models.CharField(_('Name'), max_length=128)
    # For URLs (?pollutant=diesel-pm). Set when the row is created, never
    # rewritten, so links stay good when a name is corrected.
    slug = models.SlugField(_('Slug'), max_length=140, unique=True)
    kind = models.CharField(_('Kind'), max_length=12, choices=Kind.choices, default=Kind.TOXIC, db_index=True)
    # OEHHA values as the Consolidated Table gives them.
    iur = models.FloatField(_('Inhalation unit risk (µg/m³)⁻¹'), null=True, blank=True)
    chronic_rel = models.FloatField(_('Chronic REL (µg/m³)'), null=True, blank=True)
    acute_rel = models.FloatField(_('Acute REL (µg/m³)'), null=True, blank=True)
    mwaf = models.FloatField(_('Molecular weight adjustment factor'), default=1.0)
    weighted = models.BooleanField(_('Weighted'), default=True)
    # Derived by set_weights(); 0 where there's no value to derive from.
    cancer_weight = models.FloatField(_('Cancer weight per lb'), default=0.0)
    chronic_weight = models.FloatField(_('Chronic hazard weight per lb'), default=0.0)
    acute_weight = models.FloatField(_('Acute hazard weight per lb'), default=0.0)
    health_values_date = models.DateField(_('Health values date'), null=True, blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.carb_id})'

    def set_weights(self):
        """Recompute the three weights from the health values; a precursor or an unweighted id gets none."""
        if self.kind != self.Kind.TOXIC:
            self.cancer_weight = self.chronic_weight = self.acute_weight = 0.0
            return
        self.cancer_weight = self.iur * self.mwaf * CANCER_SCALE if self.weighted and self.iur else 0.0
        self.chronic_weight = CHRONIC_SCALE / self.chronic_rel if self.chronic_rel else 0.0
        self.acute_weight = ACUTE_SCALE / self.acute_rel if self.acute_rel else 0.0

    @staticmethod
    def cas_from_carb_id(carb_id):
        """'71432' -> '71-43-2'; '' for a 4-digit CARB code (a CAS has at least five digits)."""
        carb_id = str(carb_id).strip()
        if len(carb_id) <= 4 or not carb_id.isdigit():
            return ''
        return f'{carb_id[:-3]}-{carb_id[-3:-1]}-{carb_id[-1]}'

    @classmethod
    def unique_slug(cls, name, carb_id):
        """slugify(name), with the CARB id appended when that's taken or reserved."""
        base = slugify(name) or f'pollutant-{carb_id}'
        if base in RESERVED_SLUGS or cls.objects.filter(slug=base).exists():
            # slug's max_length is 140; clip base so 'base-carb_id' still fits.
            clipped = base[:140 - len(carb_id) - 1]
            return f'{clipped}-{carb_id}'
        return base

    @classmethod
    def create_for(cls, carb_id, name):
        """A new row for a CARB id first seen in a facility's CSV: no health values yet."""
        carb_id = str(carb_id).strip()
        return cls.objects.create(
            carb_id=carb_id,
            cas_number=cls.cas_from_carb_id(carb_id),
            name=name,
            slug=cls.unique_slug(name, carb_id),
            kind=cls.Kind.PRECURSOR if carb_id in PRECURSOR_IDS else cls.Kind.TOXIC,
        )


class ToxicEmission(models.Model):
    """One facility's reported pounds of one toxic pollutant in one inventory year (CARB's facdet CSV, EMISSIONS_LBS_YR)."""

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.ToxicEmission'))
    facility = models.ForeignKey('emissions.Facility', verbose_name=_('Facility'), on_delete=models.CASCADE, related_name='toxic_emissions')
    year = models.IntegerField(_('Year'))
    pollutant = models.ForeignKey('emissions.ToxicPollutant', verbose_name=_('Pollutant'), on_delete=models.PROTECT, related_name='emissions')
    lbs = models.DecimalField(_('Emissions (lbs/yr)'), max_digits=25, decimal_places=15)

    class Meta:
        unique_together = [('facility', 'year', 'pollutant')]
        indexes = [
            models.Index(fields=['year', 'pollutant']),
            models.Index(fields=['pollutant', 'year']),
        ]

    def __str__(self):
        return f'{self.facility.name} {self.pollutant.name} ({self.year})'
