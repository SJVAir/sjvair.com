import json
import math

import numpy as np
import rapidjson

from django.contrib.gis.geos import GEOSGeometry
from nameparser.parser import HumanName
from phonenumber_field.phonenumber import PhoneNumber

from resticus.encoders import JSONEncoder as ResticusJSONEncoder


class JSONEncoder(ResticusJSONEncoder):
    def default(self, obj):
        if isinstance(obj, (HumanName, PhoneNumber)):
            return str(obj)

        if isinstance(obj, GEOSGeometry):
            return json.loads(obj.geojson)

        if isinstance(obj, (float, np.floating)) and (math.isnan(obj) or math.isinf(obj)):
            return None

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

    def encode(self, obj):
        return self(self._clean_floats(obj))

    def _clean_floats(self, obj):
        if isinstance(obj, dict):
            return {k: self._clean_floats(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._clean_floats(v) for v in obj]
        elif isinstance(obj, (float, np.floating)) and not math.isfinite(obj):
            return None
        return obj

    def iterencode(self, data):
        stream = IterStream()
        self(data, stream)
        yield from stream
