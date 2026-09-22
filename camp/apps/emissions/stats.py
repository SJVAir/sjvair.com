"""
Aggregates for the Facility Emissions Explorer.

About 6,500 facilities x 15 years, so everything is computed per request from
EmissionsRecord and cached per scope for a day; no rollup tables. Values are
tons/yr (CEIDARS) unless a name says otherwise; templates convert toxics to
lbs with Pollutant.display().
"""

from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlencode

from django.core.cache import cache
from django.db.models import Count, F, Sum

from camp.apps.emissions import cepam
from camp.apps.emissions.models import MINOR_SOURCE_SIC_CODES, CountyInventory, EmissionsRecord, Facility
from camp.apps.emissions.pollutants import CRITERIA, DEFAULT_CRITERIA, DEFAULT_TOXIC, TOXICS, Pollutant, get_pollutant
from camp.apps.regions.models import Region

# Bump when the shape of anything cached here changes.
CACHE_VERSION = 1
CACHE_TIMEOUT = 60 * 60 * 24
# A year-over-year change larger than this gets the "may reflect estimation
# methods" note on a facility page.
LARGE_CHANGE = 0.5
SORTS = ('-value', 'value', 'name', '-name', 'county', '-county')
SORT_FIELDS = {'name': 'facility__name', 'county': 'facility__county__name'}


def _float(value):
    return None if value is None else float(value)


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def available_years():
    def compute():
        return sorted(EmissionsRecord.objects.values_list('year', flat=True).distinct())
    return cache.get_or_set(f'emissions:v{CACHE_VERSION}:years', compute, 60 * 60)


def latest_year():
    years = available_years()
    return years[-1] if years else None


@dataclass(frozen=True)
class Scope:
    year: Optional[int]
    county: Optional[Region]
    pollutant: Pollutant
    minor: bool = False

    @property
    def toxics(self):
        return self.pollutant.toxic

    def key(self, name, *extra):
        parts = [
            f'emissions:v{CACHE_VERSION}', name, self.year,
            self.county.pk if self.county else 'all',
            self.pollutant.key, int(self.minor), *extra,
        ]
        return ':'.join(str(part) for part in parts)

    def params(self, **overrides):
        """The scope as query parameters, leaving out every default."""
        values = {
            'year': self.year,
            'county': self.county.slug if self.county else None,
            'pollutant': self.pollutant.key,
            'toxics': '1' if self.toxics else None,
            'minor': '1' if self.minor else None,
        }
        values.update(overrides)
        if values.get('year') == latest_year():
            values['year'] = None
        default = DEFAULT_TOXIC if values.get('toxics') else DEFAULT_CRITERIA
        if values.get('pollutant') == default:
            values['pollutant'] = None
        return {key: value for key, value in values.items() if value not in (None, '')}

    def query(self, **overrides):
        params = self.params(**overrides)
        return f'?{urlencode(params)}' if params else ''


def resolve_scope(params):
    """Scope from a request's GET; anything unknown falls back to its default."""
    years = available_years()
    year = _int(params.get('year'))
    if year not in years:
        year = years[-1] if years else None
    county = None
    if params.get('county'):
        county = Region.objects.counties().filter(slug=params['county']).first()
    toxics = params.get('toxics') == '1'
    return Scope(
        year=year,
        county=county,
        pollutant=get_pollutant(params.get('pollutant'), toxic=toxics),
        minor=params.get('minor') == '1',
    )


def records(scope, *, all_years=False):
    queryset = EmissionsRecord.objects.all()
    if not all_years:
        queryset = queryset.filter(year=scope.year)
    if scope.county is not None:
        queryset = queryset.filter(facility__county=scope.county)
    if not scope.minor:
        queryset = queryset.exclude(facility__sic_code__in=MINOR_SOURCE_SIC_CODES)
    return queryset


def totals(scope):
    def compute():
        fields = [pollutant.key for pollutant in CRITERIA + TOXICS]
        row = records(scope).aggregate(
            facilities=Count('facility', distinct=True),
            **{field: Sum(field) for field in fields},
        )
        return {key: (value if key == 'facilities' else _float(value)) for key, value in row.items()}
    return cache.get_or_set(scope.key('totals'), compute, CACHE_TIMEOUT)


def _competition_ranks(pairs):
    """[(key, value), ...] sorted by value descending -> {key: rank}; ties share a rank."""
    result = {}
    previous = object()
    rank = 0
    for position, (key, value) in enumerate(pairs, 1):
        if value != previous:
            rank = position
            previous = value
        result[key] = rank
    return result


def ranks(scope):
    field = scope.pollutant.key

    def compute():
        pairs = (
            records(scope)
            .filter(**{f'{field}__gt': 0})
            .order_by(f'-{field}')
            .values_list('facility_id', field)
        )
        return _competition_ranks(pairs)
    return cache.get_or_set(scope.key('ranks'), compute, CACHE_TIMEOUT)


def with_ranks(rows, rank_map):
    return [(rank_map.get(record.facility_id), record) for record in rows]


def facility_table(scope, *, sector=None, district=None, city=None, q=None, sort='-value'):
    field = scope.pollutant.key
    queryset = (
        records(scope)
        .select_related('facility', 'facility__county', 'facility__city', 'facility__air_district')
        .annotate(value=F(field))
    )
    if sector:
        queryset = queryset.filter(facility__sector=sector)
    if district:
        queryset = queryset.filter(facility__air_district__external_id=district)
    if city:
        queryset = queryset.filter(facility__city__slug=city)
    if q:
        queryset = queryset.filter(facility__name__icontains=q)
    sort = sort if sort in SORTS else '-value'
    key = sort.lstrip('-')
    descending = sort.startswith('-')
    if key == 'value':
        order = F(field).desc(nulls_last=True) if descending else F(field).asc(nulls_last=True)
    else:
        order = F(SORT_FIELDS[key]).desc() if descending else F(SORT_FIELDS[key]).asc()
    return queryset.order_by(order, 'facility__name')


def sector_breakdown(scope):
    field = scope.pollutant.key

    def compute():
        rows = list(
            records(scope)
            .values('facility__sector')
            .annotate(facilities=Count('facility', distinct=True), value=Sum(field))
        )
        total = sum(float(row['value'] or 0) for row in rows)
        result = [{
            'sector': Facility.Sector(row['facility__sector']),
            'label': Facility.Sector(row['facility__sector']).label,
            'facilities': row['facilities'],
            'value': float(row['value'] or 0),
            'share': float(row['value'] or 0) / total if total else None,
        } for row in rows]
        result.sort(key=lambda row: (-row['value'], row['label']))
        return result
    return cache.get_or_set(scope.key('sectors'), compute, CACHE_TIMEOUT)


def county_breakdown(scope, *, sector=None):
    field = scope.pollutant.key
    everywhere = Scope(year=scope.year, county=None, pollutant=scope.pollutant, minor=scope.minor)

    def compute():
        queryset = records(everywhere)
        if sector:
            queryset = queryset.filter(facility__sector=sector)
        rows = list(
            queryset.values('facility__county')
            .annotate(facilities=Count('facility', distinct=True), value=Sum(field))
        )
        counties = Region.objects.in_bulk([row['facility__county'] for row in rows if row['facility__county']])
        total = sum(float(row['value'] or 0) for row in rows)
        result = [{
            'county': counties[row['facility__county']],
            'facilities': row['facilities'],
            'value': float(row['value'] or 0),
            'share': float(row['value'] or 0) / total if total else None,
        } for row in rows if row['facility__county'] in counties]
        result.sort(key=lambda row: (-row['value'], row['county'].name))
        return result
    return cache.get_or_set(everywhere.key('counties', sector or ''), compute, CACHE_TIMEOUT)


def by_year(scope, *, facility=None, sector=None):
    field = scope.pollutant.key

    def compute():
        if facility is not None:
            queryset = EmissionsRecord.objects.filter(facility=facility)
        else:
            queryset = records(scope, all_years=True)
            if sector:
                queryset = queryset.filter(facility__sector=sector)
        rows = queryset.values('year').annotate(value=Sum(field)).order_by('year')
        return [{'year': row['year'], 'value': float(row['value'] or 0)} for row in rows]
    extra = f'facility-{facility.pk}' if facility is not None else f'sector-{sector or ""}'
    return cache.get_or_set(scope.key('by-year', extra), compute, CACHE_TIMEOUT)


def sector_trends(scope):
    field = scope.pollutant.key

    def compute():
        rows = (
            records(scope, all_years=True)
            .values('facility__sector', 'year')
            .annotate(value=Sum(field))
            .order_by('facility__sector', 'year')
        )
        result = {}
        for row in rows:
            result.setdefault(row['facility__sector'], []).append(
                {'year': row['year'], 'value': float(row['value'] or 0)}
            )
        return result
    return cache.get_or_set(scope.key('sector-trends'), compute, CACHE_TIMEOUT)


def county_context(scope):
    """
    CARB's estimate of every source in the scope's counties, by source type,
    beside the permitted-facility total; None for toxics (CEPAM has none) or
    a year CEPAM hasn't been imported for.
    """
    if scope.toxics or scope.year is None:
        return None
    field = scope.pollutant.key

    def compute():
        counties = [scope.county] if scope.county else list(Region.objects.counties())
        sums = dict(
            CountyInventory.objects
            .filter(county__in=counties, year=scope.year, inventory=cepam.INVENTORY)
            .values_list('source_type')
            .annotate(total=Sum(field))
        )
        if not sums:
            return None
        parts = [{
            'source_type': source_type,
            'label': source_type.label,
            'tons': (sums.get(source_type) or 0) * 365,
        } for source_type in CountyInventory.SourceType]
        total = sum(part['tons'] for part in parts)
        if not total:
            return None
        for part in parts:
            part['share'] = part['tons'] / total
        facilities = totals(scope)[field] or 0
        return {
            'parts': parts,
            'total': total,
            'facilities': facilities,
            'facility_share': facilities / total,
            'base_year': cepam.BASE_YEAR,
            'inventory': cepam.INVENTORY,
            'counties': counties,
        }
    return cache.get_or_set(scope.key('context'), compute, CACHE_TIMEOUT)


def _rank_of(value, values):
    return 1 + sum(1 for other in values if other > value)


def facility_ranks(facility, year):
    """Criteria pollutants for one facility-year, ranked among its county's and its sector's facilities."""
    record = facility.emissions.filter(year=year).first()
    if record is None:
        return []
    fields = [pollutant.key for pollutant in CRITERIA]
    peers = EmissionsRecord.objects.filter(year=year)
    if not facility.is_minor_source:
        peers = peers.exclude(facility__sic_code__in=MINOR_SOURCE_SIC_CODES)
    county_rows = list(peers.filter(facility__county_id=facility.county_id).values(*fields))
    sector_rows = list(peers.filter(facility__sector=facility.sector).values(*fields))
    result = []
    for pollutant in CRITERIA:
        value = _float(getattr(record, pollutant.key))
        row = {'pollutant': pollutant, 'value': value}
        if value:
            county_values = [float(r[pollutant.key]) for r in county_rows if r[pollutant.key]]
            sector_values = [float(r[pollutant.key]) for r in sector_rows if r[pollutant.key]]
            county_total = sum(county_values)
            row.update({
                'county_rank': _rank_of(value, county_values),
                'county_count': len(county_values),
                'sector_rank': _rank_of(value, sector_values),
                'sector_count': len(sector_values),
                'county_share': value / county_total if county_total else None,
            })
        result.append(row)
    return result


def facility_toxics(facility, year):
    """Toxics the facility reported in `year`, in lbs/yr, with the year before when it has one."""
    current = facility.emissions.filter(year=year).first()
    if current is None:
        return []
    previous = facility.emissions.filter(year=year - 1).first()
    rows = []
    for pollutant in TOXICS:
        value = getattr(current, pollutant.key)
        if not value:
            continue
        rows.append({
            'pollutant': pollutant,
            'value': pollutant.display(value),
            'previous': pollutant.display(getattr(previous, pollutant.key)) if previous else None,
            'previous_year': previous.year if previous else None,
        })
    return rows


def large_changes(facility):
    """Consecutive-year criteria changes larger than LARGE_CHANGE, oldest first."""
    history = list(facility.emissions.order_by('year'))
    changes = []
    for before, after in zip(history, history[1:]):
        if after.year != before.year + 1:
            continue
        for pollutant in CRITERIA:
            old = _float(getattr(before, pollutant.key))
            new = _float(getattr(after, pollutant.key))
            if not old or new is None:
                continue
            pct = (new - old) / old
            if abs(pct) > LARGE_CHANGE:
                changes.append({
                    'pollutant': pollutant,
                    'year': after.year,
                    'previous_year': before.year,
                    'pct': pct * 100,
                })
    return changes
