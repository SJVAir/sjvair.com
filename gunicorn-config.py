"""
Gunicorn config for SJVAir on Heroku.

Goals:
- Explicit, typed env handling
- Heroku-friendly bind/logging/timeouts
- Sensible, env-driven concurrency
- Safe preload with Django
"""

from __future__ import annotations

import multiprocessing
import os
from typing import Callable, Optional, Type


# ---------- helpers ----------

def _parse_bool(s: str) -> bool:
    truey = {'1', 'true', 't', 'yes', 'y', 'on'}
    falsey = {'0', 'false', 'f', 'no', 'n', 'off'}
    v = s.strip().lower()
    if v in truey:
        return True
    if v in falsey:
        return False
    # Fall back: non-empty is True (but we almost always hit the sets above)
    return bool(v)


_CASTERS: dict[type, Callable[[str], object]] = {
    str: str,
    int: int,
    bool: _parse_bool,
}


def env(key: str, default: Optional[object] = None, dtype: Type = str) -> object | None:
    value = os.getenv(key)
    if value is None:
        return default
    caster = _CASTERS.get(dtype, str)
    try:
        return caster(value)
    except Exception:
        return default


# ---------- network / bind ----------
# Heroku provides $PORT and expects 0.0.0.0:$PORT
bind = f"0.0.0.0:{env('PORT', 8000, int)}"

# Respect X-Forwarded-* headers from Heroku's router
forwarded_allow_ips = "*"  # trust router
# (Gunicorn already treats X-FORWARDED-PROTO='https' as secure by default.)

# Keep connections a bit longer to reduce churn behind the router
keepalive = env('GUNICORN_KEEPALIVE', 5, int)


# ---------- logging (12-factor: stdout/stderr) ----------
accesslog = "-"  # stdout
errorlog = "-"   # stderr
loglevel = env('LOG_LEVEL', "info")


# ---------- worker model & sizing ----------
# Prefer env so you can tune by dyno size without code changes.
# Rule of thumb: start conservative on Heroku (memory-bound).
_default_workers = max(2, multiprocessing.cpu_count())  # safe default
workers = env('WEB_CONCURRENCY', _default_workers, int)

# Worker class: 'sync' (default) or 'gthread' if you expect I/O wait
worker_class = env('GUNICORN_WORKER_CLASS', 'sync')

# Threads (used only if worker_class='gthread')
threads = env('GUNICORN_THREADS', 2, int)

# Per-request time budget; Heroku router is ~30s, so don't exceed that.
timeout = env('GUNICORN_TIMEOUT', 30, int)
graceful_timeout = env('GUNICORN_GRACEFUL_TIMEOUT', 30, int)

# Preload to save memory via copy-on-write; pair with post_fork safety.
preload_app = env('GUNICORN_PRELOAD', True, bool)

# Recycle to mitigate slow leaks; jitter staggers restarts.
max_requests = env('GUNICORN_MAX_REQUESTS', 1000, int)
max_requests_jitter = env('GUNICORN_MAX_REQUESTS_JITTER', 100, int)

# Use tmp in memory to avoid slow disk I/O on ephemeral FS
worker_tmp_dir = '/dev/shm'

# Limit request line/headers for extra safety
limit_request_line = env('GUNICORN_LIMIT_REQUEST_LINE', 4094, int)
limit_request_fields = env('GUNICORN_LIMIT_REQUEST_FIELDS', 100, int)
limit_request_field_size = env('GUNICORN_LIMIT_REQUEST_FIELD_SIZE', 8190, int)


# ---------- hooks ----------
def post_fork(server, worker) -> None:
    """
    With preload_app=True, ensure no DB connections are shared.
    Django will lazily re-connect per worker after fork.
    """
    try:
        from django.db import connections
        connections.close_all()
    except Exception:
        # Keep failures visible in logs; don't silently swallow issues.
        server.log.warning('post_fork could not close Django DB connections')
