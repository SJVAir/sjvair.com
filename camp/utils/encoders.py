import json
import math

import numpy as np
import rapidjson

from django.contrib.gis.geos import GEOSGeometry
from nameparser.parser import HumanName
from phonenumber_field.phonenumber import PhoneNumber

from resticus.encoders import JSONEncoder as ResticusJSONEncoder


def coalesce(gen, target=64 * 1024):
    buf = []
    size = 0
    for s in gen:
        if isinstance(s, (bytes, bytearray)):
            s = s.decode('utf-8')
        buf.append(s)
        size += len(s)
        if size >= target:
            yield ''.join(buf).encode('utf-8')
            buf, size = [], 0
    if buf:
        yield ''.join(buf).encode('utf-8')


class JSONDecoder:
    def decode(self, data):
        if isinstance(data, (bytes, bytearray)):
            data = data.decode('utf-8')
        return rapidjson.loads(data)


class JSONEncoder(ResticusJSONEncoder):
    def default(self, obj):
        if isinstance(obj, (HumanName, PhoneNumber)):
            return str(obj)

        if isinstance(obj, GEOSGeometry):
            return obj.__geo_interface__

        if isinstance(obj, np.number):
            return obj.item()

        return super().default(obj)

    def iterencode(self, o, _one_shot=False):
        markers = {} if self.check_circular else None
        _encoder = json.encoder.encode_basestring_ascii if self.ensure_ascii else json.encoder.encode_basestring

        # This is basically what stdlib does internally, but we override floatstr.
        def floatstr(value, allow_nan=True, _repr=float.__repr__):
            if isinstance(value, float) and not math.isfinite(value):
                return 'null'
            return _repr(value)

        if (_one_shot and json.encoder.c_make_encoder is not None
                and self.indent is None):
            _iterencode = json.encoder.c_make_encoder(
                markers, self.default, _encoder, self.indent,
                self.key_separator, self.item_separator, self.sort_keys,
                self.skipkeys, self.allow_nan)
            return _iterencode(o, 0)

        _iterencode = json.encoder._make_iterencode(
            markers, self.default, _encoder, self.indent, floatstr,
            self.key_separator, self.item_separator, self.sort_keys,
            self.skipkeys, _one_shot)
        return coalesce(_iterencode(o, 0))
