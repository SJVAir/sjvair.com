"""
School-district helpers shared by the explorers' Schools tabs.

A place's Schools tab names the district that runs each school, links it, and
lists the districts the place overlaps. Every explorer draws that the same
way; what differs is only which of its pages a district links to, so the
helpers take the name of the `Region` URL method to use (`'get_pesticides_url'`,
`'get_emissions_url'`) rather than importing an explorer.
"""
import re

from django.core.cache import cache

from camp.apps.regions.models import Region

# The "School districts here" box: this many of the largest by enrollment,
# the rest a click away.
DISTRICTS_VISIBLE = 5
# ...and a district counts as "here" once this share of it is inside.
DISTRICT_MIN_OVERLAP = 0.05
AREA_DISTRICTS_TTL = 60 * 60 * 24


def district_urls(*, url_method):
    """
    Each school district, by its seven-digit CDE code (the start of its CDS
    code, which is how a public school names the district that runs it) and
    by name as `name:<name>` (all a private school's record gives):
    {key: {'url', 'sqid', 'name'}}. `url_method` names the Region method that
    gives the district's page in the calling explorer.
    """
    districts = {}
    regions = Region.objects.filter(type=Region.Type.SCHOOL_DISTRICT, boundary__isnull=False)
    for region in regions.only('external_id', 'name', 'sqid', 'slug'):
        entry = {'url': getattr(region, url_method)(), 'sqid': region.sqid, 'name': region.name}
        if region.external_id:
            districts[region.external_id[:7]] = entry
        districts.setdefault(f'name:{region.name}', entry)
    return districts


def area_districts(geometry, *, cache_key, url_method):
    """
    The school districts a place's `geometry` (EPSG:4326) overlaps, for its
    Schools tab's "School districts here" box: [{name, url, sqid, enrollment,
    is_collapsed}] in name order, with all but the DISTRICTS_VISIBLE largest
    by enrollment collapsed (shown on "Show all"). A district counts once a
    real part of it is inside (DISTRICT_MIN_OVERLAP of its area): Kern High
    slivers into Tulare County along the line, and by enrollment would be one
    of its five. Cached a day under the caller's `cache_key`, which must say
    which explorer asked (the URLs differ).
    """
    def build():
        candidates = (
            Region.objects
            .filter(type=Region.Type.SCHOOL_DISTRICT, boundary__geometry__intersects=geometry)
            .exclude(boundary__geometry__touches=geometry)
            .select_related('boundary')
        )
        districts = []
        for region in candidates:
            shape = region.boundary.geometry
            if shape.area and shape.intersection(geometry).area / shape.area >= DISTRICT_MIN_OVERLAP:
                districts.append({
                    'name': region.name,
                    'url': getattr(region, url_method)(),
                    'sqid': region.sqid,
                    'enrollment': ((region.metadata or {}).get('enrollment') or {}).get('total') or 0,
                })
        largest = {d['sqid'] for d in sorted(districts, key=lambda d: -d['enrollment'])[:DISTRICTS_VISIBLE]}
        for d in districts:
            d['is_collapsed'] = d['sqid'] not in largest
        return sorted(districts, key=lambda d: d['name'].lower())

    value = cache.get(cache_key)
    if value is None:
        value = build()
        cache.set(cache_key, value, AREA_DISTRICTS_TTL)
    return value


def district_fields(location, districts, *, url_method):
    """
    `run_by_url`, the page of the district a site names -- by its CDE code (a
    public school's), else the district it was resolved into when the names
    agree (a private school carries its district's name but no code), else by
    name (it may have resolved into an overlapping one); none for a county
    office of education. And `district_sqid`/`district_name`, the district the
    district filter files it under: the one it names, else -- child care
    names none -- the one it sits in. `districts` is `district_urls()`.
    """
    metadata = location.metadata or {}
    name = metadata.get('district_name')
    named = districts.get(metadata.get('district_code') or '')
    containing = location.school_district
    if named is None and containing is not None and containing.name == name:
        named = {'url': getattr(containing, url_method)(), 'sqid': containing.sqid, 'name': containing.name}
    if named is None and name:
        named = districts.get(f'name:{name}')
    if named is not None:
        return {'run_by_url': named['url'], 'district_sqid': named['sqid'], 'district_name': named['name']}
    return {
        'run_by_url': None,
        'district_sqid': containing.sqid if containing is not None else None,
        'district_name': containing.name if containing is not None else '',
    }


# A word, with an apostrophe inside it kept ("CHILDREN'S" -> "Children's").
# Letters rather than [A-Za-z] so an accented name ("CANADA" with a tilde)
# doesn't come back out half-shouted.
WORD_RE = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)*")


# Tokens a source shouts that should stay shouted: district and agency
# initialisms, and roman numerals ("SITE III").
NAME_ACRONYMS = {
    'USD', 'EOC', 'YMCA', 'YWCA', 'CDC', 'CDCC', 'CCC', 'LLC', 'INC', 'KCAO', 'CSU', 'CSUF', 'UC', 'UCSF',
    'SJV', 'CA', 'PS', 'HS', 'JHS', 'MS', 'ES', 'MLK', 'JFK', 'ABC', 'HSA', 'ROP', 'STEM', 'STEAM', 'TK',
}
NAME_ACRONYM_RE = re.compile(r'^(?:[A-Z]{1,5}USD|[IVX]{2,4})$')


def _case_word(word):
    upper = word.upper()
    if upper in NAME_ACRONYMS or NAME_ACRONYM_RE.match(upper):
        return upper
    return word[:1].upper() + word[1:].lower()


def title_case_name(value):
    """
    A shouted source name as a readable one: "SELMA  HIGH" -> "Selma High",
    "FUSD-STOREY" -> "FUSD-Storey", "CAMPUS CENTER - SITE III" keeps its
    numeral, "LEARNING EXPERIENCE THE" -> "The Learning Experience". Runs of
    spaces collapse either way. A name that isn't entirely upper case was
    cased deliberately (McKinley, de Anza) and is left alone. The source names
    stay as imported; this is display only.
    """
    text = ' '.join(str(value or '').split())
    if not text or text != text.upper():
        return text
    # A listing-style trailing article ("... THE", "... A") goes back to the front.
    parts = text.split(' ')
    if len(parts) > 1 and parts[-1] in ('THE', 'A', 'AN'):
        parts = [parts[-1]] + parts[:-1]
    text = ' '.join(parts)
    return WORD_RE.sub(lambda match: _case_word(match.group(0)), text)


def display_name(location, text):
    """
    A name or city as the table should print it. Only the CDSS child care
    directory shouts its text -- drive it off the source rather than the
    text's own case, so a school CDE deliberately wrote in capitals keeps it.
    """
    if location.source != 'cdss-ccl':
        return text
    return title_case_name(text)
