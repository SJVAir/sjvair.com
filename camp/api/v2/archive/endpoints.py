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
    """List available monthly entry archive files for a monitor."""


class ArchiveCSV(EntryArchiveMixin, generics.DetailEndpoint):
    """Redirect to the download URL for a monitor's monthly entry archive CSV."""
    def get_object(self):
        return self.get_queryset().get(
            year=self.kwargs['year'],
            month=self.kwargs['month'],
        )

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        return redirect(self.object.data.url)
