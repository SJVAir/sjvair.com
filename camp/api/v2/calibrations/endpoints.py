from resticus import generics

from camp.apps.calibrations.models import Calibrator

from .serializers import CalibratorSerializer


class CalibratorList(generics.ListEndpoint):
    model = Calibrator
    serializer_class = CalibratorSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.filter(is_enabled=True)
        queryset = queryset.select_related('reference')
        return queryset
