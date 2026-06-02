import json

from shapely.geometry import shape


class CountyFilterMixin:
    """
    Mixin for region import commands that should support filtering by county.

    Adds a --county argument (repeatable). When provided, the import is spatially
    filtered to the union of those county boundaries. When omitted, commands fall
    back to limit_to_region=True (SJV counties only).

    Usage in a command:
        class Command(CountyFilterMixin, BaseCommand):
            def add_arguments(self, parser):
                self.add_county_arguments(parser)

            def handle(self, *args, **options):
                region_geometry = self.get_region_geometry(options.get('counties'))
                gdf = geodata.gdf_from_ckan(
                    ...,
                    limit_to_region=(region_geometry is None),
                    region_geometry=region_geometry,
                )
    """

    def add_county_arguments(self, parser):
        parser.add_argument(
            '--county',
            action='append',
            dest='counties',
            metavar='NAME',
            help='County name to filter import by (can be used multiple times). '
                 'Defaults to SJV counties.',
        )

    def get_region_geometry(self, county_names):
        """
        Returns a combined Shapely geometry for the given county names, or None
        if no counties were specified (caller should use limit_to_region=True).
        """
        if not county_names:
            return None

        from camp.apps.regions.models import Region

        counties = Region.objects.filter(
            type=Region.Type.COUNTY,
            name__in=county_names,
        ).select_related('boundary')

        if not counties.filter(boundary__isnull=False).exists():
            raise LookupError(
                f'No counties with boundaries found matching: {county_names}\n'
                'Run import_counties first.'
            )

        return shape(json.loads(counties.combined_geometry().geojson))
