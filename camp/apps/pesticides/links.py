"""
Explorer page links: the templates the explorer map and `pesticides/meta/` both serve.
Site-relative here, with `{id}` where the sqid goes; `explorer_links` makes them absolute.
"""
from urllib.parse import unquote

from django.urls import reverse


def page_url_pattern(name):
    """
    A page URL with `{id}` where the sqid goes, for the map JS to fill in
    client-side. `reverse()` percent-encodes the braces, so put them back.
    """
    return unquote(reverse(name, kwargs={'sqid': '{id}'}))


# `reverse()` needs the URLconf loaded, so these are functions, not constants.
def SECTION_PAGE():
    return page_url_pattern('pesticides:section-detail')


def SECTION_RECORDS():
    return reverse('pesticides:records') + '?section={id}'


def SECTION_NOTICES():
    return reverse('pesticides:notice-list') + '?section={id}'


def SECTION_NOTICES_PAST():
    return SECTION_NOTICES() + '&past=1'


def CHEMICAL_PAGE():
    # The bare-sqid redirect: it 301s to the slugged page, query string carried along.
    return page_url_pattern('pesticides:chemical-redirect')


def _p(param, source):
    return {'param': param, 'from': source}


_YEAR_NARROW = [_p('year', 'year'), _p('narrow', 'narrow')]
_NOTICE_VALUES = [_p('chemical', 'chemical_id'), _p('product', 'product_id'), _p('narrow', 'narrow')]

# Which client values fill which query params of each link (see meta's docstring).
LINK_PARAMS = {
    'section_page': _YEAR_NARROW,
    'section_records': [
        _p('year', 'year'), _p('start', 'month_start'), _p('end', 'month_end'),
        _p('chemical', 'chemical_id'), _p('product', 'product_id'),
        _p('commodity', 'commodity_id'), _p('method', 'aerial_ground'),
        _p('narrow', 'narrow'),
    ],
    'section_notices': _NOTICE_VALUES,
    'section_notices_past': [
        _p('archive_year', 'notices_year'), _p('month', 'notices_month'), *_NOTICE_VALUES,
    ],
    'chemical_page': _YEAR_NARROW,
}


def explorer_links(request):
    """The five link templates as absolute URLs on the request's origin."""
    # Never pass a `{id}` template to build_absolute_uri: it percent-encodes the braces.
    origin = request.build_absolute_uri('/').rstrip('/')
    return {
        'section_page': origin + SECTION_PAGE(),
        'section_records': origin + SECTION_RECORDS(),
        'section_notices': origin + SECTION_NOTICES(),
        'section_notices_past': origin + SECTION_NOTICES_PAST(),
        'chemical_page': origin + CHEMICAL_PAGE(),
    }
