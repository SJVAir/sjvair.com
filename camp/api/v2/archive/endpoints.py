from resticus import generics, http
from resticus.exceptions import NotFound

from django.shortcuts import redirect

from camp.apps.archive.models import EntryArchive

from .serializers import EntryArchiveSerializer


class EntryArchiveMixin:
    model = EntryArchive
    serializer_class = EntryArchiveSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.filter(monitor_id=self.request.monitor.pk)
        return queryset


class ArchiveList(EntryArchiveMixin, generics.ListEndpoint):
    pass


class ArchiveCSV(EntryArchiveMixin, generics.DetailEndpoint):
    def get_object(self):
        return self.get_queryset().get(
            year=self.kwargs['year'],
            month=self.kwargs['month'],
        )

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        return redirect(self.object.data.url)
