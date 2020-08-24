from datetime import datetime, time
from urllib.parse import urlparse

from django import template

from camp.utils.datafiles import datafile

register = template.Library()


@register.simple_tag
def load_datafile(name):
    return datafile(name)


@register.filter
def domainify(url):
    parsed = urlparse(url)
    domain = parsed.netloc
    if domain.startswith('www.'):
        domain = domain[4:]
    if parsed.path in ['/', '']:
        return domain
    return f'{domain}{parsed.path}'
