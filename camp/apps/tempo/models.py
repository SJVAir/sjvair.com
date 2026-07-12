from django.contrib.gis.db import models as gis_models
from django.db import models
from django.utils.translation import gettext_lazy as _

from django_sqids import SqidsField, shuffle_alphabet


class Granule(models.Model):
    """
    One row per (product, timestamp) -- the SJV-clipped hourly grid for one
    TEMPO product, at whatever is currently the best-available NASA version.
    Named after NASA's own term for one hourly, per-product L3 file.
    """

    class Product(models.TextChoices):
        NO2 = 'no2', _('Nitrogen Dioxide')
        O3TOT = 'o3tot', _('Total Ozone')
        HCHO = 'hcho', _('Formaldehyde')
        CLDO4 = 'cldo4', _('Cloud Fraction')

    sqid = SqidsField(alphabet=shuffle_alphabet('tempo.Granule'))

    product = models.CharField(_('product'), max_length=10, choices=Product.choices)
    timestamp = models.DateTimeField(_('timestamp'))
    version = models.CharField(_('version'), max_length=10)
    is_final = models.BooleanField(_('is final'), default=False)

    raster = gis_models.RasterField(_('raster'), srid=4326)
    preview = models.ImageField(_('preview'), upload_to='tempo/previews/')
    bounds = gis_models.PolygonField(_('bounds'), srid=4326)

    class Meta:
        unique_together = ('product', 'timestamp')
        indexes = [
            models.Index(fields=['product', 'timestamp']),
        ]
        ordering = ('-timestamp',)

    def __str__(self):
        return f'{self.get_product_display()} @ {self.timestamp:%Y-%m-%d %H:%M}'
