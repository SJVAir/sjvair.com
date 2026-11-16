"""
The classification badges a chemical can carry, in display order. Mirrors
templates/pesticides/includes/classification-badges.html (without its `hide_iarc` page
option). Each badge's `note` is the key of the health note that explains it.
"""

BADGES = [
    {'key': 'prop65', 'label': 'Prop 65', 'note': 'prop65'},
    {'key': 'carb_tac', 'label': 'CARB TAC', 'note': 'carb_tac'},
    {'key': 'iarc_1', 'label': 'IARC 1', 'note': 'iarc_1'},
    {'key': 'iarc_2a', 'label': 'IARC 2A', 'note': 'iarc_2a'},
    {'key': 'iarc_2b', 'label': 'IARC 2B', 'note': 'iarc_2b'},
    {'key': 'iarc_3', 'label': 'IARC 3', 'note': 'iarc_3'},
    {'key': 'california_restricted', 'label': 'Restricted', 'note': 'california_restricted'},
]


def chemical_badges(chemical):
    """The keys of the badges this chemical carries, in BADGES order."""
    keys = []
    if chemical.is_prop65:
        keys.append('prop65')
    if chemical.is_tac:
        keys.append('carb_tac')
    if chemical.iarc_group:
        keys.append(f'iarc_{chemical.iarc_group.lower()}')
    if chemical.is_california_restricted:
        keys.append('california_restricted')
    return keys
