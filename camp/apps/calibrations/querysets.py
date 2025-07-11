from django.db import models

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point


class CalibrationPairQuerySet(models.QuerySet):
    def closest(self, point):
        '''
            Returns the closest calibration pair based on the reference position.
        '''
        return (self
            .annotate(distance=Distance("reference__position", point, spheroid=True))
            .order_by('distance')
        ).first()


class CalibrationQuerySet(models.QuerySet):
    def get_for_entry(self, entry, trainer):
        return self.filter(
            pair__is_enabled=True,
            entry_type=entry.entry_type,
            end_time__lte=entry.timestamp,
            trainer=trainer,
        ).closest(entry.position)

    def closest(self, point):
        '''
        Returns the closest Calibration based on the pair's reference position.
        '''
        return (self
            .annotate(
                distance=Distance("pair__reference__position", point, spheroid=True)
            )
            .order_by('distance', '-created')
            .first()
        )


# Legacy

class CalibratorQuerySet(models.QuerySet):
    def closest(self, point):
        '''
            Returns the closest calibrator based on the reference position.
        '''
        return (self
            .annotate(distance=Distance("reference__position", point, spheroid=True))
            .order_by('distance')
        ).first()
