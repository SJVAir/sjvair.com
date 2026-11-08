import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)

CACHE_TIMEOUT = 30 * 60

# Every key of a stored entry type's result besides `status`.
RESULT_FIELDS = ('value', 'level', 'window', 'latest_timestamp', 'readings', 'required', 'previous', 'evaluated_at')


def cache_key(monitor_id):
    return f'alerts:current:{monitor_id}'


def _brief(result):
    if result is None:
        return {'status': None, 'value': None, 'level': None}
    return {
        'status': result.status,
        'value': result.value,
        'level': result.level.key if result.level else None,
    }


def serialize(results, evaluated_at):
    '''
    Turn an evaluator's {entry_model: AlertResult} into plain data keyed by
    entry type. Datetimes stay datetimes for the API serializer.
    '''
    return {
        entry_model.entry_type: {
            **_brief(result),
            'window': {'start': result.window_start, 'end': result.window_end},
            'latest_timestamp': result.latest_timestamp,
            'readings': result.readings,
            'required': result.required,
            'previous': _brief(result.previous),
            'evaluated_at': evaluated_at,
        }
        for entry_model, result in results.items()
    }


def store(monitor, results, evaluated_at):
    # Never let the cache break the alert run (and its SMS).
    try:
        cache.set(cache_key(monitor.pk), serialize(results, evaluated_at), timeout=CACHE_TIMEOUT)
    except Exception:
        logger.exception('Storing alert result failed for monitor %s', monitor.pk)


def load(monitor_id):
    return cache.get(cache_key(monitor_id))
