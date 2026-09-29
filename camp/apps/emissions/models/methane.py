from django.contrib.gis.db import models
from django.db.models import F
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from django_sqids import SqidsField, shuffle_alphabet


class MethaneSource(models.Model):
    """
    A methane point source in Carbon Mapper's public catalog: the durable
    cluster of plumes seen at one spot across aircraft and satellite passes
    since 2016, with Carbon Mapper's estimate of its emission rate. Each rate
    is an instantaneous estimate with wide uncertainty, not an annual total,
    and a site with no source hasn't been shown to be clean (see the About
    page's Methane section). Refreshed monthly by import_carbon_mapper,
    which links each source to the nearest CADD dairy and the nearest
    CEIDARS facility with a trusted point within 1 km.

    Licence: Carbon Mapper's custom non-commercial terms (LICENSE). The data
    is shown only on our own pages, never re-licensed or offered as a
    download, and every rendering carries ATTRIBUTION.
    """

    ATTRIBUTION = 'Data by Carbon Mapper®'
    LICENSE = 'Carbon Mapper non-commercial terms, https://carbonmapper.org/terms'
    LICENSE_URL = 'https://carbonmapper.org/terms'
    HOME_URL = 'https://carbonmapper.org'
    VIEWER_URL = 'https://data.carbonmapper.org/#{lat:.5f},{lng:.5f}'

    class Gas(models.TextChoices):
        CH4 = 'CH4', _('Methane')
        CO2 = 'CO2', _('Carbon dioxide')

    class Group(models.TextChoices):
        LIVESTOCK = 'livestock', _('Livestock')
        OIL_GAS = 'oil-gas', _('Oil & gas')
        WASTE = 'waste', _('Waste & wastewater')
        OTHER = 'other', _('Other')

    # IPCC 2006 source categories as Carbon Mapper codes them, longest
    # prefix wins: the map's colour group and the label shown for the sector.
    SECTORS = {
        '4B': (Group.LIVESTOCK, 'Livestock'),
        '1B2': (Group.OIL_GAS, 'Oil & gas'),
        '1B1': (Group.OTHER, 'Coal mining'),
        '1A1': (Group.OTHER, 'Energy industries'),
        '1A2': (Group.OTHER, 'Manufacturing & construction'),
        '6A': (Group.WASTE, 'Solid waste'),
        '6B': (Group.WASTE, 'Wastewater'),
        '4C': (Group.OTHER, 'Rice cultivation'),
        # Carbon Mapper's two uncoded values ('Other', and 'NA' for a source
        # it hasn't attributed to a sector), with no IPCC code in parens.
        'OTHER': (Group.OTHER, 'Other'),
        'NA': (Group.OTHER, 'Not attributed'),
    }

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.MethaneSource'))
    source_name = models.CharField(_('Source name'), max_length=64, unique=True)
    gas = models.CharField(_('Gas'), max_length=3, choices=Gas.choices, db_index=True)
    point = models.PointField(_('Point'))
    ipcc_sector = models.CharField(_('IPCC sector'), max_length=8, blank=True)
    sector_label = models.CharField(_('Sector'), max_length=32, blank=True)
    persistence = models.FloatField(_('Persistence'), null=True, blank=True)
    emission_kg_h = models.FloatField(_('Emission rate (kg/h)'), null=True, blank=True)
    uncertainty_kg_h = models.FloatField(_('Emission uncertainty (kg/h)'), null=True, blank=True)
    observations = models.IntegerField(_('Observation dates'), default=0)
    detections = models.IntegerField(_('Detection dates'), default=0)
    county = models.ForeignKey('regions.Region', verbose_name=_('County'), on_delete=models.PROTECT, related_name='methane_sources')
    dairy = models.ForeignKey('emissions.Dairy', verbose_name=_('Nearest dairy'), null=True, blank=True, on_delete=models.SET_NULL, related_name='methane_sources')
    facility = models.ForeignKey('emissions.Facility', verbose_name=_('Nearest facility'), null=True, blank=True, on_delete=models.SET_NULL, related_name='methane_sources')
    distance_m = models.FloatField(_('Distance to the match (m)'), null=True, blank=True)
    fetched_at = models.DateTimeField(_('Fetched at'), auto_now=True)

    class Meta:
        ordering = [F('emission_kg_h').desc(nulls_last=True), 'source_name']
        indexes = [models.Index(fields=['county', 'gas'])]

    def __str__(self):
        return f'{self.source_name} ({self.sector_label or self.ipcc_sector or "?"})'

    @classmethod
    def sector_for(cls, code):
        """(group, label) for an IPCC code: the longest listed prefix, else other with the code itself as the label."""
        code = (code or '').strip().upper()
        if not code:
            return cls.Group.OTHER, 'Unknown sector'
        for prefix in sorted(cls.SECTORS, key=len, reverse=True):
            if code.startswith(prefix):
                return cls.SECTORS[prefix]
        return cls.Group.OTHER, code

    @property
    def group(self):
        return self.sector_for(self.ipcc_sector)[0]

    @property
    def viewer_url(self):
        return self.VIEWER_URL.format(lat=self.point.y, lng=self.point.x)

    @property
    def rate_text(self):
        """`120 ± 40 kg/h`; without an uncertainty `120 kg/h`; without a rate `rate not estimated`. A rate is always shown beside "Carbon Mapper estimate"."""
        if self.emission_kg_h is None:
            return 'rate not estimated'
        text = f'{self.emission_kg_h:,.0f}'
        if self.uncertainty_kg_h is not None:
            text += f' ± {self.uncertainty_kg_h:,.0f}'
        return f'{text} kg/h'


def methane_plume_upload_to(instance, filename):
    # Partitioned by year/month, matching tempo's granule_preview_upload_to
    # precedent -- otherwise a monthly, indefinite-retention import piles
    # everything into one flat, ever-growing S3 prefix.
    return '/'.join([
        'emissions', 'methane-plumes',
        f'{instance.observed_at.year}',
        f'{instance.observed_at.month:02d}',
        filename,
    ])


class MethanePlume(models.Model):
    """
    One detection behind a MethaneSource, from Carbon Mapper's public plume
    catalog (`/catalog/plumes/annotated`): a single aircraft/satellite pass's
    view of a release, with the small plume image Carbon Mapper renders for
    it. A source's plumes are what its emission rate is estimated from.

    The catalog's plume payload carries no source id, so `source` is set by
    import_carbon_mapper the same way a MethaneSource is matched to a dairy
    or facility: the nearest MethaneSource within MATCH_METERS of the
    plume's point (carbonmapper.py's `nearest`). A plume can be left
    unmatched (source NULL) when nothing is that close.

    Licence: Carbon Mapper's custom non-commercial terms, same as
    MethaneSource (see its docstring) -- every rendering carries
    MethaneSource.ATTRIBUTION.
    """

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.MethanePlume'))
    plume_id = models.CharField(_('Plume id'), max_length=64, unique=True)
    source = models.ForeignKey(
        'emissions.MethaneSource', verbose_name=_('Source'), null=True, blank=True,
        on_delete=models.SET_NULL, related_name='plumes',
    )
    observed_at = models.DateTimeField(_('Observed at'))
    platform = models.CharField(_('Platform'), max_length=32, blank=True)
    instrument = models.CharField(_('Instrument'), max_length=16, blank=True)
    point = models.PointField(_('Point'))
    # Carbon Mapper's plume_bounds, the box a MapLibre image source uses to
    # place the PNG on the map.
    bounds = models.PolygonField(_('Bounds'), srid=4326)
    emission_kg_h = models.FloatField(_('Emission rate (kg/h)'), null=True, blank=True)
    uncertainty_kg_h = models.FloatField(_('Emission uncertainty (kg/h)'), null=True, blank=True)
    wind_speed = models.FloatField(_('Wind speed'), null=True, blank=True)
    wind_direction = models.FloatField(_('Wind direction'), null=True, blank=True)
    image = models.ImageField(_('Plume image'), upload_to=methane_plume_upload_to, blank=True)
    fetched_at = models.DateTimeField(_('Fetched at'), auto_now=True)

    class Meta:
        ordering = ['-observed_at']
        indexes = [models.Index(fields=['source', '-observed_at'])]

    def __str__(self):
        return self.plume_id

    @property
    def bounds_bbox(self):
        """[west, south, east, north], as Carbon Mapper's plume_bounds gives it."""
        west, south, east, north = self.bounds.extent
        return [west, south, east, north]
