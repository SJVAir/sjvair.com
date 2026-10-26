__all__ = ['AirNowNowCast']


class AirNowNowCast:
    """
    Base for AirNow's NowCast. Not a per-entry processor -- AirNow computes
    the NowCast itself and returns it as `Value`, alongside the hourly
    `RawConcentration` we store as RAW. It isn't derived from our RAW
    entry, so it's built straight from the AirNow row. AirNow's missing
    value (-999) is defined here; the import uses it for RAW too.
    """
    entry_model = None
    next_stage = None

    # AirNow reports a missing or invalid reading as -999.
    MISSING_VALUE = -999

    @classmethod
    def is_missing(cls, value):
        return value is None or value == cls.MISSING_VALUE

    @classmethod
    def create_entry(cls, monitor, payload, origin=None):
        '''`origin` is the hour's RAW entry, if it has a valid one.'''
        nowcast = payload.get('Value')
        if cls.is_missing(nowcast):
            return None

        return monitor.create_entry(cls.entry_model,
            timestamp=monitor.get_timestamp(payload),
            stage=cls.next_stage,
            processor=cls.name,
            origin_id=origin.pk if origin else None,
            value=nowcast,
        )
