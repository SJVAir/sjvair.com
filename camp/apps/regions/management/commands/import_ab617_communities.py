from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from camp.apps.regions import ab617
from camp.apps.regions.models import Boundary, Region
from camp.utils.gis import to_multipolygon


class Command(BaseCommand):
    help = (
        'Import CARB AB 617 community boundaries covering the counties in '
        'settings.SJVAIR_COUNTIES as Region(type=ab617) + Boundary records.'
    )

    def handle(self, *args, **options):
        self.stdout.write('Fetching CARB AB 617 community boundaries...')
        features = ab617.fetch_features()
        communities = ab617.group_by_community(features)

        imported = 0
        for code, entry in sorted(communities.items()):
            props = entry['properties']
            if props.get('COUNTY') not in settings.SJVAIR_COUNTIES:
                continue

            boundaries = entry['boundaries']
            boundary_type = ab617.primary_boundary_type(boundaries)
            if boundary_type is None:
                # Only an Emission Study Area row, no community-specific
                # geometry -- nothing worth publishing as a region.
                continue

            name = props.get('COMMUNITY') or code
            metadata = {
                'community_code': code,
                'community_url': props.get('DIS_OCAP_WEB') or '',
                'county': props.get('COUNTY') or '',
                'air_district': props.get('AIR_DISTRICT') or '',
                'cerp_selected_year': props.get('CERPSLCTDYR') or '',
                'camp_selected_year': props.get('CAMPSLCTDYR') or '',
                'boundary_type': boundary_type,
                'storymaps_url': props.get('STORYMAPS') or '',
            }

            region, created = Region.objects.import_or_update(
                name=name,
                slug=slugify(name),
                type=Region.Type.AB617_COMMUNITY,
                external_id=code,
                geometry=to_multipolygon(boundaries[boundary_type]),
                version=ab617.BOUNDARY_VERSIONS[boundary_type],
                metadata=metadata,
                boundary_metadata={'boundary_type': boundary_type},
            )

            # Shafter-style communities carry a separate, larger Emission
            # Study Area Boundary alongside the Community Boundary used
            # above. Keep it too, as a second Boundary version -- it's just
            # not the one region.boundary points at.
            if boundary_type == ab617.COMMUNITY_BOUNDARY and ab617.EMISSION_STUDY_BOUNDARY in boundaries:
                Boundary.objects.update_or_create(
                    region=region,
                    version=ab617.BOUNDARY_VERSIONS[ab617.EMISSION_STUDY_BOUNDARY],
                    defaults={
                        'geometry': to_multipolygon(boundaries[ab617.EMISSION_STUDY_BOUNDARY]),
                        'metadata': {'boundary_type': ab617.EMISSION_STUDY_BOUNDARY},
                    },
                )

            imported += 1
            verb = 'Imported' if created else 'Updated'
            self.stdout.write(self.style.SUCCESS(f'{verb}: {region.name} ({code})'))

        self.stdout.write(f'{imported} AB 617 communities cover the configured counties.')
