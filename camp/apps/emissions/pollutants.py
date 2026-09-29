"""The pollutants the explorer can show: the criteria pollutants, the two weighted toxics measures, and (from the database) every toxic CARB reports."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Pollutant:
    key: str                 # picker key: an EmissionsRecord field, 'cancer' / 'chronic', or a ToxicPollutant slug
    label: str                # short, for pickers and column headers
    name: str                 # spelled out
    toxic: bool = False
    weight_field: str = ''    # 'cancer_weight' or 'chronic_weight' for the two weighted measures
    pollutant_id: Optional[int] = None  # ToxicPollutant pk for one toxic

    @property
    def weighted(self):
        return bool(self.weight_field)

    @property
    def slug(self):
        return self.key

    @property
    def unit(self):
        """
        'tons' (criteria, CEIDARS tons/yr), 'lbs' (one toxic, CARB's lbs/yr),
        or 'share' (a weighted measure: the facility's, area's or scope's
        fraction of the Valley's weighted total that year -- it has no unit a
        person can read, so it's never shown raw).
        """
        if self.weighted:
            return 'share'
        return 'lbs' if self.toxic else 'tons'

    @property
    def unit_label(self):
        return {'tons': 'tons/yr', 'lbs': 'lbs/yr', 'share': 'share of Valley total'}[self.unit]

    def display(self, value):
        """The stored value in its display unit -- a passthrough (values are already tons, lbs or a share)."""
        return None if value is None else float(value)


CRITERIA = [
    Pollutant('nox', 'NOx', 'Nitrogen oxides'),
    Pollutant('rog', 'ROG', 'Reactive organic gases'),
    Pollutant('pm', 'Total PM', 'Total particulate matter'),
    Pollutant('pm10', 'PM10', 'Particulate matter under 10 microns'),
    Pollutant('sox', 'SOx', 'Sulfur oxides'),
    Pollutant('co', 'CO', 'Carbon monoxide'),
    Pollutant('tog', 'TOG', 'Total organic gases'),
]

# The two toxicity-weighted measures (pounds × OEHHA potency, CARB's method;
# see models.ToxicPollutant.set_weights). Shown as a share of the Valley
# total, never as a number with a unit.
CANCER = Pollutant('cancer', 'Cancer-weighted', 'Cancer-weighted toxics (relative)', toxic=True, weight_field='cancer_weight')
CHRONIC = Pollutant('chronic', 'Hazard-weighted', 'Non-cancer hazard-weighted toxics (relative)', toxic=True, weight_field='chronic_weight')
WEIGHTED = [CANCER, CHRONIC]

POLLUTANTS = {pollutant.key: pollutant for pollutant in CRITERIA + WEIGHTED}
DEFAULT_CRITERIA = 'nox'
DEFAULT_TOXIC = 'cancer'

# The ten toxics the explorer used to store as columns, by their old picker
# key; old links resolve (and redirect) to the pollutant's slug.
LEGACY_TOXIC_KEYS = {
    'acetaldehyde': '75070', 'benzene': '71432', 'butadiene': '106990', 'carbon_tetrachloride': '56235',
    'chromium_hexavalent': '18540299', 'dichlorobenzene': '106467', 'formaldehyde': '50000',
    'methylene_chloride': '75092', 'naphthalene': '91203', 'perchloroethylene': '127184',
}


def get_pollutant(key):
    """The criteria pollutant for `key`, else the default. Toxics resolve in stats.resolve_toxic (they live in the database)."""
    pollutant = POLLUTANTS.get(key)
    if pollutant is not None and not pollutant.toxic:
        return pollutant
    return POLLUTANTS[DEFAULT_CRITERIA]


def toxic_pollutant(row):
    """A Pollutant for one ToxicPollutant row (or a values() dict with pk, slug, name)."""
    if isinstance(row, dict):
        return Pollutant(row['slug'], row['name'], row['name'], toxic=True, pollutant_id=row['pk'])
    return Pollutant(row.slug, row.name, row.name, toxic=True, pollutant_id=row.pk)
