from resticus import serializers

from camp.apps.regions.models import Region


class RegionSerializer(serializers.Serializer):
    fields = ['id', 'name', 'type']


class RegionDetailSerializer(serializers.Serializer):
    fields = ['id', 'name', 'type']

    def fixup(self, instance, data):
        data['geometry'] = (
            instance.boundary.geometry.geojson
            if instance.boundary
            else None
        )
        return data
