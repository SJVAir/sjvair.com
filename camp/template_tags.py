import json

from urllib.parse import urlparse

from django import template
from django.conf import settings
from django.shortcuts import resolve_url
from django.template.loader import render_to_string
from django.test import RequestFactory
from django.urls import resolve, reverse
from django.urls.exceptions import Resolver404

from resticus import generics

from camp.api.middleware import MonitorAccessMiddleware
from camp.utils.datafiles import datafile
from camp.utils.test import get_response_data

register = template.Library()


@register.simple_tag
def load_datafile(name):
    return datafile(name)


@register.filter
def domainify(url):
    ''' Parse out the domain of a URL '''
    parsed = urlparse(url)
    domain = parsed.netloc
    if domain.startswith('www.'):
        domain = domain[4:]
    if parsed.path in ['/', '']:
        return domain
    return f'{domain}{parsed.path}'


@register.filter
def urlify(to, *args, **kwargs):
    ''' Convert a path into a full URL '''
    return settings.DOMAIN + resolve_url(to, *args, **kwargs)


@register.filter
def jsonify(data):
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.decoder.JSONDecodeError as err:
            pass
    try:
        return json.dumps(data, indent=4)
    except Exception:
        return data

# Admin URL helpers

@register.simple_tag
def admin_changelist_url(instance):
    return reverse(
        f'admin:{instance._meta.app_label}_{instance._meta.model_name}_changelist'
    )


@register.simple_tag
def admin_add_url(instance):
    return reverse(
        f'admin:{instance._meta.app_label}_{instance._meta.model_name}_add'
    )


@register.simple_tag
def admin_history_url(instance):
    return reverse(
        f'admin:{instance._meta.app_label}_{instance._meta.model_name}_history',
        args=[instance.pk]
    )


@register.simple_tag
def admin_delete_url(instance):
    return reverse(
        f'admin:{instance._meta.app_label}_{instance._meta.model_name}_delete',
        args=[instance.pk]
    )


@register.simple_tag
def admin_change_url(instance):
    return reverse(
        f'admin:{instance._meta.app_label}_{instance._meta.model_name}_change',
        args=[instance.pk]
    )


## /Admin URL helpers


@register.simple_tag
def api_docs(path, json_params=None):
    try:
        match = resolve(path)
    except Resolver404:
        return f"Invalid path: {path}"

    if json_params is not None:
        try:
            params = json.loads(json_params)
        except Exception:
            return str(err)
    else:
        params = {}

    view = getattr(match.func, 'view_class', None)
    if not issubclass(view, generics.GenericEndpoint):
        return f"View is not an API endpoint: {view}"

    middleware = MonitorAccessMiddleware(lambda request: request)
    factory = RequestFactory()
    request = factory.get(path, params)
    middleware.process_view(request, match.func, match.args, match.kwargs)
    response = match.func(request, **match.kwargs)

    response_data = get_response_data(response)

    # Trim the JSON responses
    is_json = response.get('Content-Type') == 'application/json'
    if (is_json
        and isinstance(response_data, dict)
        and 'data' in response_data
        and isinstance(response_data['data'], list)
    ):
        response_data['data'] = response_data['data'][:1]

    # Trim the CSV
    is_csv = response.get('Content-Type') == 'text/csv'
    if is_csv:
        response_data = '\n'.join(response_data.splitlines()[:10])

    instance = view()

    filters = None
    if hasattr(instance, 'get_filter_class'):
        filter_class = instance.get_filter_class()
        if filter_class is not None:
            filters = [(k, f.__class__.__name__) for k, f in filter_class.get_filters().items()]

    context = {
        'name': match.url_name,
        'route': f"/{match.route.lstrip('/')}",
        'filters': filters,
        'is_json': is_json,
        'is_csv': is_csv,
        'is_download': response.get('Content-Disposition', '').startswith('attachment'),
        'data': response_data,
    }

    return render_to_string('api/endpoint-get.html', context)





