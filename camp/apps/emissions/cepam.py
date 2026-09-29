"""
CARB's county emission inventory (CEPAM) by emission inventory code (EIC).

Whole-county requests only: the form that splits a county by air district
sits behind bot protection, and the facility inventory is whole-county too.
The fetch and parse side is importers.cepam.
"""

# The 2019 SIP inventory: base year 2017, every other year back-cast or
# projected ("grown and controlled"). Change here when CARB publishes a
# newer inventory.
INVENTORY = '2019V104ADJ'
BASE_YEAR = 2017

DAYS_PER_YEAR = 365


def tons_per_year(tons_per_day):
    """CEPAM's tons/day (annual average) as tons/yr; None stays None."""
    return None if tons_per_day is None else tons_per_day * DAYS_PER_YEAR
