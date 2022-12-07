from django.db import models

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point


class CalibratorQuerySet(models.QuerySet):
    def closest(self, point):
        '''
            Returns the closest calibrator
        '''
        # point = Point(lon, lat, srid=4326)
        return (self
            .annotate(distance=Distance("reference__position", point, spheroid=True))
            .order_by('distance')
        ).first()
