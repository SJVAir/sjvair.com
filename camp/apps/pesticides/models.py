from django.contrib.gis.db import models
from django.contrib.postgres.fields import ArrayField
from django.utils.translation import gettext_lazy as _

from django_sqids import SqidsField, shuffle_alphabet
from model_utils.models import TimeStampedModel

from camp.apps.regions.models import Region
from camp.apps.pesticides.querysets import ChemicalQuerySet, CommodityQuerySet, ProductQuerySet


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

    objects = ChemicalQuerySet.as_manager()

    sqid = SqidsField(alphabet=shuffle_alphabet('pesticides.Chemical'))

    chem_code = models.IntegerField(_('Chemical Code'), unique=True)
    name = models.CharField(_('Name'), max_length=256)
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

    def __str__(self):
        return self.name


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
        related_name='pesticide_usess_mtrs',
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
        indexes = [
            models.Index(fields=['year', 'county']),
            models.Index(fields=['year', 'use_no']),
            models.Index(fields=['mtrs']),
            models.Index(fields=['product']),
            models.Index(fields=['chemical']),
            models.Index(fields=['commodity']),
            models.Index(fields=['application_date']),
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
