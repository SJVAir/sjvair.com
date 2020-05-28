from resticus import generics

from camp.apps.monitors.models import Monitor
from .serializers import MonitorSerializer

class MonitorMixin:
    model = Monitor
    serializer_class = MonitorSerializer


class MonitorList(MonitorMixin, generics.ListEndpoint):
    paginate = False
