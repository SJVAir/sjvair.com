from django.contrib.gis.db import models as gis_models
from django.db import models
from django_smalluuid.models import SmallUUIDField, uuid_default


class Smoke(models.Model):
    class Density(models.TextChoices):
        LIGHT = 'light', 'Light'
        MEDIUM = 'medium', 'Medium'
        HEAVY = 'heavy', 'Heavy'

    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )
    date = models.DateField(null=True)
    satellite = models.CharField(max_length=20)
    start = models.DateTimeField(null=True)
    end = models.DateTimeField(null=True)
    density = models.CharField(max_length=10, choices=Density.choices, default=Density.LIGHT)
    geometry = gis_models.MultiPolygonField(srid=4326)

    class Meta:
        ordering = ('-date',)


class Fire(models.Model):
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID',
    )
    # date is the file date (which day's snapshot this record came from).
    # timestamp is the actual observation time of the individual fire point.
    # These can differ — a single day's file may contain points observed across midnight.
    date = models.DateField(null=True)
    satellite = models.CharField(max_length=20)
    timestamp = models.DateTimeField(null=True)
    frp = models.DecimalField(max_digits=10, decimal_places=3)
    ecosystem = models.IntegerField()
    method = models.CharField(max_length=10)
    geometry = gis_models.PointField(srid=4326)

    class Meta:
        ordering = ('-date',)
