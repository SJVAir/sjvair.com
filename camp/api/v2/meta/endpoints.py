from django.core.exceptions import ValidationError

from resticus import generics, http

from camp.apps.monitors.cimis.models import CIMIS
from camp.apps.monitors.models import Monitor
from camp.apps.regions.models import Region
from camp.utils.views import CachedEndpointMixin

from . import catalog, coverage


class DatasetCatalogEndpoint(generics.Endpoint):
    """
    Every data domain the server has, with its entry types, geographies,
    and the summary resolutions each entry type supports.

    Dataset ids and entry-type ids are a permanent public contract: they are
    never reused for a different meaning, and a rename changes only the label.
    Retired ids stay listed with a non-null `retired`.
    """

    def get(self, request, *args, **kwargs):
        response = http.Http200({'data': catalog.get_catalog()})
        response['Cache-Control'] = 'public, max-age=300'
        return response


class CoverageEndpointBase(generics.Endpoint):
    """
    First and last Pacific date of data for ?dataset=, optionally narrowed by
    ?entry_type=. For air-quality and weather, also for one place: ?monitor=<id>
    or ?region_type=<type>&region=<code> (air-quality only), with entry_type
    required. Nulls when there is no data.

    The get() lives on this un-cached base so CachedEndpointMixin.get() on
    CoverageEndpoint is the one dispatched to.
    """
    MONITOR_DATASETS = ('air-quality', 'weather')

    def get(self, request, *args, **kwargs):
        params = {key: request.GET.get(key, '').strip() for key in
                  ('dataset', 'entry_type', 'monitor', 'region_type', 'region')}
        dataset = params['dataset']
        entry_type = params['entry_type'] or None

        if dataset not in catalog.DATASET_IDS:
            return self.error(f'Unknown dataset: {dataset or "(none)"}.')
        if entry_type and entry_type not in catalog.dataset_entry_types(dataset):
            return self.error(f'Unknown entry type for {dataset}: {entry_type}.')

        monitor_id = params['monitor']
        region_type, region_code = params['region_type'], params['region']
        if monitor_id and (region_type or region_code):
            return self.error('Give either monitor or region, not both.')
        if bool(region_type) != bool(region_code):
            return self.error('region_type and region go together.')

        if monitor_id or region_code:
            if dataset not in self.MONITOR_DATASETS:
                return self.error(f'Per-place coverage is not available for {dataset}.')
            if entry_type is None:
                return self.error('entry_type is required with monitor or region.')

        data = {'dataset': dataset, 'entry_type': entry_type}
        try:
            if monitor_id:
                monitor = self.get_monitor(monitor_id)
                if monitor is None:
                    return http.Http404({'error': f'No such monitor: {monitor_id}.'})
                if isinstance(monitor, CIMIS) != (dataset == 'weather'):
                    return self.error(f'Monitor {monitor_id} is not part of {dataset}.')
                data['monitor'] = str(monitor.pk)
                span = coverage.monitor_span(monitor, entry_type)
            elif region_code:
                if dataset != 'air-quality':
                    return self.error(f'{dataset} has no region-level coverage.')
                if region_type == Region.Type.LAND_USE:
                    return self.error("Land-use regions can't be looked up by code yet.")
                # all_objects: a retired region's code still answers.
                region = Region.all_objects.filter(type=region_type, external_id=region_code).first()
                if region is None:
                    return http.Http404({'error': f'No such region: {region_type} {region_code}.'})
                data['region'] = {'type': region.type, 'external_id': region.external_id}
                span = coverage.region_span(region, entry_type)
            else:
                span = coverage.dataset_span(dataset, entry_type)
        except coverage.CoverageError as err:
            return self.error(str(err))

        data['first'] = span['first'].isoformat() if span['first'] else None
        data['last'] = span['last'].isoformat() if span['last'] else None
        response = http.Http200({'data': data})
        response['Cache-Control'] = 'public, max-age=900'
        return response

    def error(self, message):
        return http.Http400({'error': message})

    def get_monitor(self, monitor_id):
        try:
            return Monitor.objects.get(pk=monitor_id)
        except (Monitor.DoesNotExist, ValidationError, ValueError):
            return None


class CoverageEndpoint(CachedEndpointMixin, CoverageEndpointBase):
    cache_timeout = 900
