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
    if parsed.path in ['/', '']:
        return parsed.netloc
    return f'{parsed.netloc}{parsed.path}'
