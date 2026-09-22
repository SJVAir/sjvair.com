"""The pollutants the explorer can show, in display order."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Pollutant:
    key: str      # EmissionsRecord (and, for criteria, CountyInventory) field name
    label: str    # short, for pickers and column headers
    name: str     # spelled out
    toxic: bool = False

    @property
    def unit(self):
        # Toxic air contaminants are fractions of a ton; pounds read better.
        return 'lbs' if self.toxic else 'tons'

    @property
    def factor(self):
        return 2000 if self.toxic else 1

    def display(self, tons):
        return None if tons is None else float(tons) * self.factor


CRITERIA = [
    Pollutant('nox', 'NOx', 'Nitrogen oxides'),
    Pollutant('rog', 'ROG', 'Reactive organic gases'),
    Pollutant('pm', 'Total PM', 'Total particulate matter'),
    Pollutant('pm10', 'PM10', 'Particulate matter under 10 microns'),
    Pollutant('sox', 'SOx', 'Sulfur oxides'),
    Pollutant('co', 'CO', 'Carbon monoxide'),
    Pollutant('tog', 'TOG', 'Total organic gases'),
]

TOXICS = [
    Pollutant('benzene', 'Benzene', 'Benzene', toxic=True),
    Pollutant('formaldehyde', 'Formaldehyde', 'Formaldehyde', toxic=True),
    Pollutant('acetaldehyde', 'Acetaldehyde', 'Acetaldehyde', toxic=True),
    Pollutant('butadiene', '1,3-Butadiene', '1,3-Butadiene', toxic=True),
    Pollutant('chromium_hexavalent', 'Hexavalent chromium', 'Hexavalent chromium', toxic=True),
    Pollutant('naphthalene', 'Naphthalene', 'Naphthalene', toxic=True),
    Pollutant('perchloroethylene', 'Perchloroethylene', 'Perchloroethylene (dry cleaning solvent)', toxic=True),
    Pollutant('methylene_chloride', 'Methylene chloride', 'Methylene chloride', toxic=True),
    Pollutant('carbon_tetrachloride', 'Carbon tetrachloride', 'Carbon tetrachloride', toxic=True),
    Pollutant('dichlorobenzene', 'p-Dichlorobenzene', 'para-Dichlorobenzene', toxic=True),
]

POLLUTANTS = {pollutant.key: pollutant for pollutant in CRITERIA + TOXICS}
DEFAULT_CRITERIA = 'nox'
DEFAULT_TOXIC = 'benzene'


def get_pollutant(key, toxic=False):
    """The pollutant for `key` when it's of the requested kind, else that kind's default."""
    pollutant = POLLUTANTS.get(key)
    if pollutant is not None and pollutant.toxic == toxic:
        return pollutant
    return POLLUTANTS[DEFAULT_TOXIC if toxic else DEFAULT_CRITERIA]
