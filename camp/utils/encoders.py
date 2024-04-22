import json

from decimal import Decimal

import rapidjson

from django.contrib.gis.geos import GEOSGeometry
from nameparser.parser import HumanName
from phonenumber_field.phonenumber import PhoneNumber

from resticus.encoders import JSONEncoder as ResticusJSONEncoder


class JSONEncoder(ResticusJSONEncoder):
    def default(self, obj):
        if isinstance(obj, (HumanName, PhoneNumber)):
            return str(obj)

        elif isinstance(obj, GEOSGeometry):
            return json.loads(obj.geojson)

        return super().default(obj)


class IterStream:
    def __init__(self):
        self.__in = []

    def write(self, data):
        self.__in.append(data)

    def __iter__(self):
        return iter(self.__in)


class RapidJSONDecoder:
    def decode(self, data):
        return rapidjson.loads(data)


class RapidJSONEncoder(rapidjson.Encoder):
    def __init__(self, *args, **kwargs):
        self._encoder = JSONEncoder()

    def default(self, obj):
        return self._encoder.default(obj)

    def encode(self, *args, **kwargs):
        return self(*args, **kwargs)

    def iterencode(self, data):
        stream = IterStream()
        self(data, stream)
        yield from stream
