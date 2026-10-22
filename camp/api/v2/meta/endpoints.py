from resticus import generics, http

from . import catalog


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
