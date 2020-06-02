from resticus import generics

from django.http import Http404
from django.utils.functional import cached_property

from camp.apps.monitors.models import Entry, Monitor
from .filters import EntryFilter, MonitorFilter
from .serializers import EntrySerializer, MonitorSerializer


class EntryMixin:
    model = Entry
    filter_class = EntryFilter
    serializer_class = EntrySerializer

    paginate = True
    page_size = 10080

    @cached_property
    def monitor(self):
        try:
            return Monitor.objects.get(pk=self.kwargs['monitor_id'])
        except Monitor.DoesNotExist:
            raise Http404

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.filter(monitor_id=self.monitor.pk)
        return queryset


class EntryList(EntryMixin, generics.ListEndpoint):
    def serialize(self, queryset, **kwargs):
        fields = ['id', 'timestamp']
        if self.request.GET.get('field') in EntrySerializer.value_fields:
            fields.append(self.request.GET['field'])
        else:
            fields.extend(EntrySerializer.value_fields)
        return (entry for entry in queryset.values(*fields))


class MonitorMixin:
    model = Monitor
    filter_class = MonitorFilter
    serializer_class = MonitorSerializer


class MonitorList(MonitorMixin, generics.ListEndpoint):
    paginate = False


class MonitorDetail(MonitorMixin, generics.DetailEndpoint):
    lookup_field = 'pk'
    lookup_url_kwarg = 'monitor_id'
