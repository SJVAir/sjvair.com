"""
Facility names as the explorer prints them. CEIDARS keeps nearly every name
in capitals ("NATIONAL CEMENT CO"); shown as-is they shout in every table.
facility_name() title-cases them for display only -- the stored name, search
and the CSV keep CARB's text.

The rule: a word turns to "Title" case except
- short words (3 letters or fewer) that aren't ordinary words, and words
  with no vowels: initialisms like MRP, DTE, NAS, AFB, MBMJ stay capitals;
- legal and corporate abbreviations that read as capitals (LLC, LP, USA);
- initials with dots (J.P.) and short ampersand pairs (E&B, PG&E);
- anything with a digit (#2319, 6TH).
Small joining words go lower case after the first word, and brands CARB
writes in capitals but that have their own casing come from BRANDS.
A name that isn't all capitals was cased on purpose and is left alone.
"""
import re

# Abbreviations that read as capitals however long they are.
UPPER = {
    'LLC', 'LLP', 'LP', 'USA', 'II', 'III', 'IV', 'VI', 'CNG', 'LNG', 'UC', 'CSU', 'CSUF', 'USD',
    'YMCA', 'YWCA', 'AT&T', 'PG&E', 'DBA',
}

# Short words that are words, not initialisms: these get title case.
WORDS = {
    'co', 'inc', 'ltd', 'oil', 'gas', 'new', 'old', 'bay', 'air', 'dry', 'car', 'bus', 'big', 'top',
    'sun', 'one', 'two', 'six', 'ten', 'red', 'san', 'los', 'las', 'del', 'la', 'el', 'mt', 'st',
    'ft', 'dr', 'ave', 'hwy', 'rd', 'mfg', 'mgmt', 'corp', 'ag', 'way', 'end', 'pit', 'ice', 'nut',
    'hay', 'tea', 'fox', 'elk', 'oak', 'gin', 'mill', 'farm', 'auto', 'body', 'shop', 'bar', 'pan',
    'can', 'tin', 'box', 'war', 'arm', 'pro', 'job', 'lab', 'art', 'cut', 'hot', 'jim', 'joe', 'bob',
    'tom', 'ray', 'lee', 'dan', 'don', 'ron', 'sam', 'ann', 'kim', 'mar', 'vista', 'rio', 'mesa',
    'sky', 'cal', 'bros', 'son', 'sons', 'go', 'my', 'we', 'us', 'our', 'to', 'by', 'or', 'as',
}

# Joining words, lower case unless they open the name.
SMALL = {'of', 'and', 'the', 'at', 'for', 'in', 'on', 'a', 'an', 'to', 'by', 'or', 'de', 'del'}

# Brands with their own casing.
BRANDS = {
    'CALPORTLAND': 'CalPortland',
    'MCDONALDS': 'McDonalds',
    "MCDONALD'S": "McDonald's",
    'MCKITTRICK': 'McKittrick',
    'MCFARLAND': 'McFarland',
    'TMOBILE': 'TMobile',
    'FEDEX': 'FedEx',
    'PETSMART': 'PetSmart',
    'WALMART': 'Walmart',
}

VOWELS = set('AEIOUY')
# One token's letters, with the punctuation around it kept as it is.
TOKEN_RE = re.compile(r"^([^A-Za-z0-9]*)(.*?)([^A-Za-z0-9]*)$")


def _part(core, first):
    """One hyphen- or slash-free piece of a word."""
    if not core:
        return core
    upper = core.upper()
    if upper in BRANDS:
        return BRANDS[upper]
    if upper in UPPER or re.search(r'\d', core):
        return core
    if re.fullmatch(r"(?:[A-Z]\.)+[A-Z]?", core) or re.fullmatch(r'[A-Z]{1,3}&[A-Z]{1,3}', core):
        return core
    low = core.lower()
    letters = re.sub(r'[^A-Z]', '', upper)
    known = low.replace("'", '') in WORDS or low in SMALL
    if not known and letters and (len(letters) <= 3 or not (set(letters) & VOWELS)):
        return core
    if not first and low in SMALL:
        return low
    # "O'NEILL" -> "O'Neill", but "JIM'S" -> "Jim's".
    cased = low[:1].upper() + low[1:]
    return re.sub(r"'([a-z])([a-z]{2,})", lambda m: "'" + m.group(1).upper() + m.group(2), cased)


def _word(token, first):
    pre, core, post = TOKEN_RE.match(token).groups()
    # Each side of a hyphen or slash cased on its own: "T-MOBILE", "LLC/DBA".
    pieces = re.split(r'([-/])', core)
    cased = [
        piece if piece in '-/' else _part(piece, first and index == 0)
        for index, piece in enumerate(pieces)
    ]
    return pre + ''.join(cased) + post


def facility_name(name):
    """CARB's all-capitals facility name as the explorer shows it."""
    text = ' '.join(str(name or '').split())
    if not text or text != text.upper() or not re.search(r'[A-Z]', text):
        return text
    return ' '.join(_word(token, index == 0) for index, token in enumerate(text.split(' ')))
