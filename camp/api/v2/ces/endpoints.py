from django.http import Http404

from resticus import generics, http

from camp.apps.ces.models import CES4, CES5
from camp.apps.regions.querysets import WITHIN_MODES

from .filters import CES4Filter, CES5Filter
from .serializers import CES4Serializer, CES5Serializer


class CES4Mixin:
    model = CES4
    serializer_class = CES4Serializer
    paginate = True
    filter_class = CES4Filter

    def get_queryset(self):
        year = self.request.GET.get('year') or '2020'
        return (
            super().get_queryset()
            .filter(boundary__version=year)
        )


class WithinModeMixin:
    """A 400 for an unknown ?within_mode=, like the regions list."""

    def get(self, request, *args, **kwargs):
        if request.GET.get('within_mode', 'contained') not in WITHIN_MODES:
            return http.Http400({'error': 'within_mode must be contained or overlaps.'})
        return super().get(request, *args, **kwargs)


class CES4List(WithinModeMixin, CES4Mixin, generics.ListEndpoint):
    """List CalEnviroScreen 4.0 scores for all census tracts for a given year (default 2020)."""


class CES4Detail(CES4Mixin, generics.DetailEndpoint):
    """Retrieve the CalEnviroScreen 4.0 score for a specific census tract."""
    def get_object(self):
        try:
            return self.get_queryset().get(
                boundary__region__external_id=self.kwargs['tract']
            )
        except CES4.DoesNotExist:
            raise Http404


class CES5Mixin:
    model = CES5
    serializer_class = CES5Serializer
    paginate = True
    filter_class = CES5Filter


class CES5List(WithinModeMixin, CES5Mixin, generics.ListEndpoint):
    """List CalEnviroScreen 5.0 scores for all census tracts."""


class CES5Detail(CES5Mixin, generics.DetailEndpoint):
    """Retrieve the CalEnviroScreen 5.0 score for a specific census tract."""
    def get_object(self):
        try:
            return self.get_queryset().get(
                boundary__region__external_id=self.kwargs['tract']
            )
        except CES5.DoesNotExist:
            raise Http404
