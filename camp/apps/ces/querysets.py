from django.db import models


class CESQuerySet(models.QuerySet):
    def for_version(self, version):
        return self.filter(boundary__version=version)

    def for_tract(self, geoid):
        return self.filter(boundary__region__external_id=geoid)


class CESManager(models.Manager):
    def get_queryset(self):
        return CESQuerySet(self.model, using=self._db).select_related('boundary__region')

    def for_version(self, version):
        return self.get_queryset().for_version(version)

    def for_tract(self, geoid):
        return self.get_queryset().for_tract(geoid)
