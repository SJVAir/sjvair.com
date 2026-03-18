import re

# Strips trailing unit/suite/apt/# suffixes from street addresses.
# Requires an explicit unit keyword (Apt, Unit, Suite) or a # sign before the unit value.
_unit_re = re.compile(r',?\s*(?:(?:Apt|Unit|Suite)\s*#?\s*\w+|#\s*\w+)$', re.IGNORECASE)


def clean_address(address):
    if not isinstance(address, str):
        return ''
    address = address.replace('\n', ' ').replace('\r', ' ').strip()
    return _unit_re.sub('', address).strip()
