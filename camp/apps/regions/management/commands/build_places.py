from django.contrib.gis.geos import GEOSGeometry
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from camp.apps.regions.models import Boundary, Region
from camp.utils.gis import to_multipolygon


SOURCE_TYPES = [Region.Type.CITY, Region.Type.CDP]


def geom_area(geom):
    clone = geom.clone()
    clone.transform(3310)
    return clone.area


class Command(BaseCommand):
    help = 'Build synthetic Place regions from Urban Areas, Cities, and CDPs'

    def handle(self, *args, **options):
        uas = list(Region.objects.filter(type=Region.Type.URBAN_AREA, boundary__isnull=False))
        cities = list(Region.objects.filter(type__in=SOURCE_TYPES, boundary__isnull=False))

        self.stdout.write(f'Processing {len(uas)} urban areas and {len(cities)} cities/CDPs...\n')

        # For each city/CDP, find all UAs it overlaps and determine the dominant one
        city_dominant_ua = {}  # city pk -> dominant UA region
        city_other_uas = {}    # city pk -> list of non-dominant UA regions

        for city in cities:
            overlapping_uas = [
                ua for ua in uas
                if ua.boundary.geometry.intersects(city.boundary.geometry)
            ]
            if not overlapping_uas:
                continue
            if len(overlapping_uas) == 1:
                city_dominant_ua[city.pk] = overlapping_uas[0]
                city_other_uas[city.pk] = []
            else:
                # Dominant = UA with greatest overlap area
                def overlap_area(ua):
                    return geom_area(ua.boundary.geometry.intersection(city.boundary.geometry))
                overlapping_uas.sort(key=overlap_area, reverse=True)
                city_dominant_ua[city.pk] = overlapping_uas[0]
                city_other_uas[city.pk] = overlapping_uas[1:]

        with transaction.atomic():
            # Build a place for each UA
            for ua in uas:
                ua_geom = ua.boundary.geometry
                components = [{'type': 'urban_area', 'id': ua.pk, 'name': ua.name}]

                # Collect cities/CDPs assigned to this UA
                assigned_cities = [
                    city for city in cities
                    if city_dominant_ua.get(city.pk) == ua
                ]

                place_geom = ua_geom
                for city in assigned_cities:
                    city_geom = city.boundary.geometry
                    others = city_other_uas.get(city.pk, [])
                    if others:
                        # Clip out portions inside other UAs
                        for other_ua in others:
                            city_geom = city_geom.difference(other_ua.boundary.geometry)
                    place_geom = place_geom.union(city_geom)
                    components.append({
                        'type': city.type,
                        'id': city.pk,
                        'name': city.name,
                        'clipped': bool(others),
                    })

                self._upsert_place(ua.name, place_geom, components)

            # Build standalone places for cities/CDPs with no UA
            standalone = [c for c in cities if c.pk not in city_dominant_ua]
            self.stdout.write(f'\nBuilding {len(standalone)} standalone places (no UA)...')
            for city in standalone:
                self._upsert_place(
                    city.name,
                    city.boundary.geometry,
                    [{'type': city.type, 'id': city.pk, 'name': city.name}],
                )

        self.stdout.write(self.style.SUCCESS('\nDone.'))

    def _upsert_place(self, name, geometry, components):
        place, created = Region.objects.update_or_create(
            slug=slugify(name),
            type=Region.Type.PLACE,
            defaults={'name': name},
        )

        boundary, _ = Boundary.objects.update_or_create(
            region=place,
            version='2020',
            defaults={
                'geometry': to_multipolygon(geometry),
                'metadata': {'components': components},
            },
        )

        place.boundary = boundary
        place.save(update_fields=['boundary'])

        status = 'Created' if created else 'Updated'
        self.stdout.write(f'  {status}: {name} ({len(components)} components)')
