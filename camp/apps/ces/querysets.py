from django.db import models


class CESQuerySet(models.QuerySet):
    def for_version(self, version):
        return self.filter(boundary__version=version)

    def for_tract(self, geoid):
        return self.filter(boundary__region__external_id=geoid)


class CESManager(models.Manager.from_queryset(CESQuerySet)):
    def get_queryset(self):
        return (
            super().get_queryset()
            .select_related('boundary__region')
            .defer('boundary__geometry')
        )
