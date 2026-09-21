from django.contrib.gis.db import models
import re

from django.contrib.postgres.fields import ArrayField
from django.urls import reverse
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from django_sqids import SqidsField, shuffle_alphabet
from model_utils.models import TimeStampedModel

from camp.apps.regions.models import Region
from camp.apps.pesticides.querysets import ChemicalQuerySet, CommodityQuerySet, ProductQuerySet


def _name_key(value):
    """Letters and digits only, lowercased: "2,4-D, SODIUM SALT" and "2,4-D sodium salt" agree."""
    return ''.join(ch for ch in value.lower() if ch.isalnum())


# Short all-caps words in CDPR names that are initialisms, not words, and so
# keep their capitals when the rest of the name is brought down to sentence
# case. Anything with a digit, one or two letters, or no vowel keeps its
# capitals without needing a listing here.
NAME_INITIALISMS = {
    'ABS', 'ADBAC', 'ATMP', 'BAC', 'BHC', 'BIT', 'CMIT', 'DBCP', 'DCNA', 'DCOIT', 'DCPA', 'DDAC', 'DDD',
    'DDE', 'DDT', 'DDVP', 'DEA', 'DEET', 'DEF', 'DMSO', 'DSMA', 'DTPA', 'EBDC', 'EDB', 'EDTA', 'EPTC',
    'HEDP', 'IBA', 'IPBC', 'LAS', 'MCPA', 'MCPB', 'MCPP', 'MEA', 'MGK', 'MIT', 'MITC', 'MSMA', 'NAA',
    'NPE', 'NTA', 'OIT', 'PBO', 'PBTC', 'PCNB', 'PCP', 'TBTO', 'TCMTB', 'TEA',
}
NAME_SMALL_WORDS = {'OF', 'IN', 'AND', 'OR', 'TO', 'AS', 'BY', 'ON', 'IS', 'FOR', 'THE'}
_WORD_RE = re.compile(r'[A-Za-z]+')


def humanize_name(name):
    """
    CDPR's reference names are shouted ("POTASSIUM N-METHYLDITHIOCARBAMATE");
    this brings an all-caps name down to sentence case while leaving
    locants, initialisms and codes alone: "Potassium N-methyldithiocarbamate",
    "2,4-D", "MCPA", "Bacillus thuringiensis, subsp. israelensis, strain AM 65-52".
    A name that isn't all caps is already someone's casing and is returned as is.
    """
    if not name or name != name.upper():
        return name

    def lower_word(match):
        word = match.group(0)
        start, end = match.span()
        # Attached to a digit ("2,4-D", "4E", "65-52A"), or a space away from
        # one ("strain MBI 600", "ATCC 39555"): a locant or a code.
        before = name[:start].rstrip(' ')
        after = name[end:].lstrip(' ')
        if (before and before[-1].isdigit()) or (after and after[0].isdigit()):
            return word
        if word in NAME_SMALL_WORDS:
            return word.lower()
        if len(word) <= 2 or word in NAME_INITIALISMS or not any(ch in 'AEIOUY' for ch in word):
            return word
        return word.lower()

    lowered = _WORD_RE.sub(lower_word, name)
    # Sentence case: the first letter goes back up.
    for i, ch in enumerate(lowered):
        if ch.isalpha():
            return lowered[:i] + ch.upper() + lowered[i + 1:]
    return lowered


def display_chemical_name(name, preferred_name):
    """
    The name the explorer shows for a chemical. CDPR's name is the common
    name and stays (in sentence case, see humanize_name), except that
    CompTox's preferred name replaces it when the two are the same name (so
    "GLYPHOSATE, ISOPROPYLAMINE SALT" reads "Glyphosate isopropylamine
    salt") or when CDPR's has no letters at all ("1080" for sodium
    fluoroacetate).
    """
    if preferred_name:
        if not any(ch.isalpha() for ch in name):
            return preferred_name
        if _name_key(name) == _name_key(preferred_name):
            return preferred_name
    return humanize_name(name)


class Chemical(TimeStampedModel):
    class Category(models.TextChoices):
        BIOPESTICIDE             = 'biopesticide',             _('Biopesticide')
        CARCINOGEN               = 'carcinogen',               _('Carcinogen')
        CHOLINESTERASE_INHIBITOR = 'cholinesterase_inhibitor', _('Cholinesterase Inhibitor')
        DEVELOPMENTAL_TOXIN      = 'developmental_toxin',      _('Developmental Toxin')
        FUMIGANT                 = 'fumigant',                 _('Fumigant')
        GROUNDWATER_CONTAMINANT  = 'groundwater_contaminant',  _('Groundwater Contaminant')
        OIL                      = 'oil',                      _('Oil')
        REPRODUCTIVE_TOXIN       = 'reproductive_toxin',       _('Reproductive Toxin')
        TOXIC_AIR_CONTAMINANT    = 'toxic_air_contaminant',    _('Toxic Air Contaminant')

    class IARCGroup(models.TextChoices):
        GROUP_1  = '1',  _('Group 1 – Carcinogenic to humans')
        GROUP_2A = '2A', _('Group 2A – Probably carcinogenic to humans')
        GROUP_2B = '2B', _('Group 2B – Possibly carcinogenic to humans')
        GROUP_3  = '3',  _('Group 3 – Not classifiable as to carcinogenicity')

    PROP65_CATEGORIES = {Category.CARCINOGEN, Category.REPRODUCTIVE_TOXIN, Category.DEVELOPMENTAL_TOXIN}
    IARC_CONCERN_GROUPS = {IARCGroup.GROUP_1, IARCGroup.GROUP_2A, IARCGroup.GROUP_2B}

    objects = ChemicalQuerySet.as_manager()

    sqid = SqidsField(alphabet=shuffle_alphabet('pesticides.Chemical'))

    chem_code = models.IntegerField(_('Chemical Code'), unique=True)
    name = models.CharField(_('Name'), max_length=256)
    # CompTox's preferred name for the matched DTXSID. Shown in place of
    # CDPR's name only when it's the same name in better casing, or when
    # CDPR's is a bare code like "1080" (see display_name): CompTox often
    # prefers the systematic name where CDPR uses the ISO common name, and a
    # mismatched DTXSID would otherwise put the wrong name on the page.
    preferred_name = models.CharField(_('Preferred Name'), max_length=256, blank=True)
    cas_number = models.CharField(_('CAS Number'), max_length=32, blank=True)
    dtxsid = models.CharField(_('DTXSID'), max_length=20, blank=True, db_index=True)
    iarc_group = models.CharField(_('IARC Group'), max_length=2, blank=True, choices=IARCGroup.choices)
    categories = ArrayField(
        models.CharField(max_length=32, choices=Category.choices),
        verbose_name=_('Categories'),
        default=list,
        blank=True,
    )
    commodities = models.ManyToManyField(
        'pesticides.Commodity',
        through='pesticides.PesticideUse',
        through_fields=('chemical', 'commodity'),
        related_name='chemicals',
        verbose_name=_('Commodities'),
        blank=True,
    )

    class Meta:
        ordering = ['name']
        verbose_name = _('pesticides.Chemical')
        verbose_name_plural = _('Chemicals')

    # CDPR's stand-ins for an ingredient it doesn't name: -2 "AI IS
    # CONFIDENTIAL" (a confidential active ingredient) and -1 "UNKNOWN".
    # Their use records are real applications, but they carry no pounds and
    # aren't a chemical, so they stay out of chemical rankings and counts.
    PLACEHOLDER_CODES = (-1, -2)

    def __str__(self):
        return self.display_name

    @property
    def is_placeholder(self):
        return self.chem_code in self.PLACEHOLDER_CODES

    @property
    def display_name(self):
        return display_chemical_name(self.name, self.preferred_name)

    @property
    def cdpr_alias(self):
        """CDPR's name when it's a different name from the one shown, not just a different casing."""
        return self.name if _name_key(self.display_name) != _name_key(self.name) else ''

    @property
    def slug(self):
        return slugify(self.display_name) or 'chemical'

    def get_absolute_url(self):
        return reverse('pesticides:chemical-detail', kwargs={'sqid': self.sqid, 'slug': self.slug})

    @property
    def is_prop65(self):
        return bool(self.PROP65_CATEGORIES & set(self.categories or []))

    @property
    def is_tac(self):
        return self.Category.TOXIC_AIR_CONTAMINANT in (self.categories or [])

    @property
    def other_categories(self):
        """Categories not already expressed by the Prop 65 / CARB TAC badges."""
        implied = self.PROP65_CATEGORIES | {self.Category.TOXIC_AIR_CONTAMINANT}
        return [c for c in (self.categories or []) if c not in implied]

    @property
    def is_iarc_concern(self):
        return self.iarc_group in self.IARC_CONCERN_GROUPS

    @property
    def is_of_concern(self):
        return self.is_prop65 or self.is_tac or self.is_iarc_concern

    @property
    def comptox_url(self):
        if not self.dtxsid:
            return None
        return f'https://comptox.epa.gov/dashboard/chemical/details/{self.dtxsid}'


class Commodity(TimeStampedModel):
    objects = CommodityQuerySet.as_manager()

    sqid = SqidsField(alphabet=shuffle_alphabet('pesticides.Commodity'))

    site_code = models.CharField(_('Site Code'), max_length=8, unique=True)
    name = models.CharField(_('Name'), max_length=128)

    class Meta:
        ordering = ['name']
        verbose_name = _('pesticides.Commodity')
        verbose_name_plural = _('Commodities')

    def __str__(self):
        return self.name

    @property
    def display_name(self):
        return humanize_name(self.name)

    @property
    def slug(self):
        return slugify(self.name) or 'commodity'

    def get_absolute_url(self):
        return reverse('pesticides:commodity-detail', kwargs={'sqid': self.sqid, 'slug': self.slug})


class Product(TimeStampedModel):
    objects = ProductQuerySet.as_manager()

    sqid = SqidsField(alphabet=shuffle_alphabet('pesticides.Product'))

    prodno = models.IntegerField(_('Product Number'), unique=True)
    reg_number = models.CharField(_('Registration Number'), max_length=64, unique=True)
    name = models.CharField(_('Name'), max_length=256)
    fumigant = models.BooleanField(_('Fumigant'), default=False)
    california_restricted = models.BooleanField(_('California Restricted'), default=False)
    chemicals = models.ManyToManyField(
        'pesticides.Chemical',
        through='ProductChemical',
        related_name='products',
        verbose_name=_('Chemicals'),
    )
    commodities = models.ManyToManyField(
        'pesticides.Commodity',
        through='pesticides.PesticideUse',
        through_fields=('product', 'commodity'),
        related_name='products',
        verbose_name=_('Commodities'),
        blank=True,
    )

    class Meta:
        ordering = ['name']
        verbose_name = _('pesticides.Product')
        verbose_name_plural = _('Products')

    def __str__(self):
        return self.name

    @property
    def display_name(self):
        return self.name

    @property
    def slug(self):
        return slugify(self.name) or 'product'

    def get_absolute_url(self):
        return reverse('pesticides:product-detail', kwargs={'sqid': self.sqid, 'slug': self.slug})

    def _chemical_list(self):
        # Uses the prefetch cache when the view prefetched 'chemicals'; otherwise one query.
        return list(self.chemicals.all())

    @property
    def contains_prop65(self):
        return any(c.is_prop65 for c in self._chemical_list())

    @property
    def contains_tac(self):
        return any(c.is_tac for c in self._chemical_list())

    @property
    def contains_iarc(self):
        return any(c.is_iarc_concern for c in self._chemical_list())

    @property
    def is_of_concern(self):
        return any(c.is_of_concern for c in self._chemical_list())


class ProductChemical(models.Model):
    product = models.ForeignKey('pesticides.Product', on_delete=models.CASCADE, related_name='product_chemicals')
    chemical = models.ForeignKey('pesticides.Chemical', on_delete=models.CASCADE, related_name='product_chemicals')
    pct_active = models.FloatField(_('Percent Active'), null=True, blank=True)

    class Meta:
        unique_together = ('product', 'chemical')

    def __str__(self):
        return f'{self.product} / {self.chemical}'


class PesticideUse(TimeStampedModel):
    class AerialGround(models.TextChoices):
        AERIAL      = 'A', _('Aerial')
        FUMIGATION  = 'F', _('Fumigation')
        GROUND      = 'G', _('Ground')
        OTHER       = 'O', _('Other')

    sqid = SqidsField(alphabet=shuffle_alphabet('pesticides.PesticideUse'))

    year = models.IntegerField(_('Year'))
    use_no = models.IntegerField(_('Use Number'))
    county = models.ForeignKey(
        'regions.Region',
        on_delete=models.PROTECT,
        related_name='pesticide_uses',
        verbose_name=_('County'),
        limit_choices_to={'type': Region.Type.COUNTY},
    )
    mtrs = models.ForeignKey(
        'regions.Region',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pesticide_uses_mtrs',
        verbose_name=_('MTRS Section'),
        limit_choices_to={'type': Region.Type.MTRS},
    )
    comtrs = models.CharField(_('COMTRS'), max_length=11, blank=True)
    product = models.ForeignKey(
        'pesticides.Product',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pesticide_uses',
        verbose_name=_('pesticides.Product'),
    )
    chemical = models.ForeignKey(
        'pesticides.Chemical',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pesticide_uses',
        verbose_name=_('pesticides.Chemical'),
    )
    commodity = models.ForeignKey(
        'pesticides.Commodity',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pesticide_uses',
        verbose_name=_('pesticides.Commodity'),
    )
    site_code = models.CharField(_('Site Code'), max_length=8, blank=True)
    pct_active = models.FloatField(_('Percent Active'), null=True, blank=True)
    lbs_chemical = models.FloatField(_('Pounds of Chemical Used'), null=True, blank=True)
    lbs_product = models.FloatField(_('Pounds of Product Used'), null=True, blank=True)
    amount_product = models.FloatField(_('Amount of Product Used'), null=True, blank=True)
    unit_product = models.CharField(_('Unit of Measure'), max_length=8, blank=True)
    acres_planted = models.FloatField(_('Acres Planted'), null=True, blank=True)
    unit_planted = models.CharField(_('Unit Planted'), max_length=4, blank=True)
    acres_treated = models.FloatField(_('Acres Treated'), null=True, blank=True)
    unit_treated = models.CharField(_('Unit Treated'), max_length=4, blank=True)
    application_count = models.IntegerField(_('Application Count'), null=True, blank=True)
    application_date = models.DateField(_('Application Date'), null=True, blank=True)
    aerial_ground = models.CharField(_('Aerial/Ground'), max_length=1, blank=True, choices=AerialGround.choices)
    record_id = models.CharField(_('Record ID'), max_length=4, blank=True)

    class Meta:
        ordering = ['-application_date', '-year']
        indexes = [
            models.Index(fields=['year', 'county']),
            models.Index(fields=['year', 'use_no']),
            models.Index(fields=['mtrs']),
            models.Index(fields=['product']),
            models.Index(fields=['chemical']),
            models.Index(fields=['commodity']),
            models.Index(fields=['application_date']),
            models.Index(fields=['chemical', 'year']),
            models.Index(fields=['product', 'year']),
            models.Index(fields=['commodity', 'year']),
        ]
        verbose_name = _('Pesticide Use')
        verbose_name_plural = _('Pesticide Uses')

    def __str__(self):
        return f'{self.year} / {self.use_no}'


class PesticideNotice(TimeStampedModel):
    sqid = SqidsField(alphabet=shuffle_alphabet('pesticides.PesticideNotice'))

    application_id = models.IntegerField(_('Application ID'), unique=True)
    comtrs = models.CharField(_('COMTRS'), max_length=11, db_index=True)
    mtrs = models.ForeignKey(
        'regions.Region',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pesticide_notices',
        verbose_name=_('MTRS Section'),
        limit_choices_to={'type': 'mtrs'},
    )
    county = models.ForeignKey(
        'regions.Region',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='county_pesticide_notices',
        verbose_name=_('County'),
        limit_choices_to={'type': 'county'},
    )
    point = models.PointField(_('Point'), null=True, blank=True, srid=4326)
    scheduled_application = models.DateTimeField(_('Scheduled Application'), db_index=True)
    treated_amount = models.FloatField(_('Treated Amount'), null=True, blank=True)
    treated_units = models.CharField(_('Treated Units'), max_length=32, blank=True)
    application_method = models.CharField(_('Application Method'), max_length=128, blank=True)
    products = models.ManyToManyField('pesticides.Product', blank=True,
        related_name='pesticide_notices', verbose_name=_('Products'))
    chemicals = models.ManyToManyField(
        'pesticides.Chemical',
        blank=True,
        related_name='pesticide_notices',
        verbose_name=_('Chemicals'),
    )

    class Meta:
        ordering = ['scheduled_application']
        verbose_name = _('Pesticide Notice')
        verbose_name_plural = _('Pesticide Notices')

    def __str__(self):
        return f'{self.application_id} / {self.comtrs}'


class PesticideUseRollup(models.Model):
    """
    Per-section, per-month rollup of PesticideUse, rebuilt per year by
    camp.apps.pesticides.rollup. Every explorer aggregate reads this instead
    of the raw records. Never exposed by id, so no sqid.
    """
    year = models.IntegerField(_('Year'))
    month = models.IntegerField(_('Month'), help_text=_('1-12, or 0 when the record has no application date'))
    county = models.ForeignKey(
        'regions.Region',
        on_delete=models.CASCADE,
        related_name='pesticide_rollups',
        verbose_name=_('County'),
        limit_choices_to={'type': Region.Type.COUNTY},
    )
    mtrs = models.ForeignKey(
        'regions.Region',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='pesticide_rollups_mtrs',
        verbose_name=_('MTRS Section'),
        limit_choices_to={'type': Region.Type.MTRS},
    )
    chemical = models.ForeignKey('pesticides.Chemical', on_delete=models.CASCADE, null=True, blank=True, related_name='rollups', verbose_name=_('pesticides.Chemical'))
    product = models.ForeignKey('pesticides.Product', on_delete=models.CASCADE, null=True, blank=True, related_name='rollups', verbose_name=_('pesticides.Product'))
    commodity = models.ForeignKey('pesticides.Commodity', on_delete=models.CASCADE, null=True, blank=True, related_name='rollups', verbose_name=_('pesticides.Commodity'))
    lbs_chemical = models.FloatField(_('Pounds of Chemical'), default=0)
    lbs_product = models.FloatField(_('Pounds of Product'), default=0)
    acres_treated = models.FloatField(_('Acres Treated'), default=0)
    applications = models.IntegerField(_('Applications'), default=0)

    class Meta:
        verbose_name = _('Pesticide Use Rollup')
        verbose_name_plural = _('Pesticide Use Rollups')
        constraints = [
            models.UniqueConstraint(
                fields=['year', 'month', 'county', 'mtrs', 'chemical', 'product', 'commodity'],
                nulls_distinct=False,
                name='pesticides_rollup_key',
            ),
        ]
        indexes = [
            models.Index(fields=['year', 'mtrs']),
            models.Index(fields=['year', 'county']),
            models.Index(fields=['year', 'chemical']),
            models.Index(fields=['year', 'product']),
            models.Index(fields=['year', 'commodity']),
            models.Index(fields=['mtrs', 'year', 'month']),
            # County-filtered entity lists: membership and pounds per entity
            # within one county and year.
            models.Index(fields=['year', 'county', 'chemical']),
            models.Index(fields=['year', 'county', 'product']),
            models.Index(fields=['year', 'county', 'commodity']),
            # Distinct chemicals per commodity -- the one commodity-list
            # aggregate the totals table can't answer. Covering, so the count
            # is an index-only scan instead of a bitmap heap scan over every
            # section row for the commodity.
            models.Index(fields=['year', 'commodity', 'chemical']),
            models.Index(fields=['year', 'county', 'commodity', 'chemical']),
        ]

    def __str__(self):
        return f'{self.year}-{self.month:02d} / {self.mtrs_id or "no section"}'


class PesticideUseTotal(models.Model):
    """
    Per-year, per-county totals for one chemical, product, or commodity --
    what the explorer list pages sort and filter on. Rebuilt from
    PesticideUseRollup by camp.apps.pesticides.rollup. Exactly one of
    chemical/product/commodity is set on each row. Never exposed by id, so no sqid.
    """
    year = models.IntegerField(_('Year'))
    county = models.ForeignKey(
        'regions.Region',
        on_delete=models.CASCADE,
        related_name='pesticide_totals',
        verbose_name=_('County'),
        limit_choices_to={'type': Region.Type.COUNTY},
    )
    chemical = models.ForeignKey('pesticides.Chemical', on_delete=models.CASCADE, null=True, blank=True, related_name='totals', verbose_name=_('pesticides.Chemical'))
    product = models.ForeignKey('pesticides.Product', on_delete=models.CASCADE, null=True, blank=True, related_name='totals', verbose_name=_('pesticides.Product'))
    commodity = models.ForeignKey('pesticides.Commodity', on_delete=models.CASCADE, null=True, blank=True, related_name='totals', verbose_name=_('pesticides.Commodity'))
    lbs_chemical = models.FloatField(_('Pounds of Chemical'), default=0)
    lbs_product = models.FloatField(_('Pounds of Product'), default=0)
    acres_treated = models.FloatField(_('Acres Treated'), default=0)
    applications = models.IntegerField(_('Applications'), default=0)

    class Meta:
        verbose_name = _('Pesticide Use Total')
        verbose_name_plural = _('Pesticide Use Totals')
        constraints = [
            models.UniqueConstraint(
                fields=['year', 'county', 'chemical', 'product', 'commodity'],
                nulls_distinct=False,
                name='pesticides_total_key',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(chemical__isnull=False, product__isnull=True, commodity__isnull=True)
                    | models.Q(chemical__isnull=True, product__isnull=False, commodity__isnull=True)
                    | models.Q(chemical__isnull=True, product__isnull=True, commodity__isnull=False)
                ),
                name='pesticides_total_one_entity',
            ),
        ]
        indexes = [
            models.Index(fields=['year', 'chemical']),
            models.Index(fields=['year', 'product']),
            models.Index(fields=['year', 'commodity']),
            models.Index(fields=['year', 'county']),
        ]

    def __str__(self):
        entity = self.chemical_id or self.product_id or self.commodity_id
        return f'{self.year} / {self.county_id} / {entity}'
