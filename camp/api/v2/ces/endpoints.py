from django.http import Http404

from resticus import generics

from camp.apps.ces.models import CES4

from .filters import CES4Filter
from .serializers import CES4Serializer


class CES4Mixin:
    model = CES4
    serializer_class = CES4Serializer
    paginate = True

    def get_queryset(self):
        return (
            super().get_queryset()
            .filter(boundary__version=self.kwargs['year'])
        )


class CES4List(CES4Mixin, generics.ListEndpoint):
    filter_class = CES4Filter


class CES4Detail(CES4Mixin, generics.DetailEndpoint):
    def get_object(self):
        try:
            return self.get_queryset().get(
                boundary__region__external_id=self.kwargs['tract']
            )
        except CES4.DoesNotExist:
            raise Http404
