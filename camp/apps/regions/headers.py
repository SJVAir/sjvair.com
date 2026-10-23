"""
The area page header both explorers share (regions/includes/area-header.html):
the gray line beside a region's name and the links that go with it. Built
here so the pesticides and emissions headers always read the same; each
explorer passes the `Region` method that links to its own pages.
"""
from camp.apps.regions import nearby
from camp.apps.regions.models import Region

# The switch to the same town on its other layer (nearby.counterpart), by that layer.
COUNTERPART_LABELS = {
    Region.Type.CITY: 'Switch to city limits',
    Region.Type.CDP: 'Switch to community',
    Region.Type.URBAN_AREA: 'Switch to urban area',
}


def region_header(region, *, url_method, tab='overview', scope_qs=''):
    """
    {'kind', 'header_links', 'county'} for a region's page:

    kind          the gray line: its type (not for a county, whose name says
                  so), an AB 617 community's CARB selection year, the county
                  it sits in, its population
    header_links  an AB 617 community's own page and story map (new tab), and
                  the switch to the same town on its other layer (`internal`,
                  same tab), on `tab` with `scope_qs` ('?year=2022' or '')
    county        the county it sits in, for the breadcrumb; None for a county

    `url_method` names the `Region` method taking a tab that links to the
    explorer's own pages ('get_pesticides_tab_url', 'get_emissions_tab_url').
    """
    metadata = region.metadata or {}
    is_county = region.type == Region.Type.COUNTY
    county = None if is_county else Region.objects.get_county_region(region)
    kind = [] if is_county else [region.type_label]
    if region.type == Region.Type.AB617_COMMUNITY and metadata.get('cerp_selected_year'):
        kind.append(f"selected by CARB in {metadata['cerp_selected_year']}")
    if county is not None:
        kind.append(county.name)
    if metadata.get('population'):
        kind.append(f"{round(float(metadata['population'])):,} people")

    links = []
    if region.type == Region.Type.AB617_COMMUNITY:
        if metadata.get('community_url'):
            links.append({'label': 'Community page', 'url': metadata['community_url']})
        if metadata.get('storymaps_url'):
            links.append({'label': 'CARB story map', 'url': metadata['storymaps_url']})
    other = nearby.counterpart(region)
    if other is not None:
        links.append({
            'label': COUNTERPART_LABELS[other.type],
            'url': getattr(other, url_method)(tab) + scope_qs,
            'internal': True,
        })
    return {'kind': ' · '.join(kind), 'header_links': links, 'county': county}


def point_kind(radius):
    """The gray line for a near-me page: 'Within 3 miles'."""
    return f'Within {radius} mile{"" if radius == 1 else "s"}'
