"""
The dashboard's web app manifest, served by Django because it must be
same-origin. The build writes dist/workspace/manifest.webmanifest with icon
paths relative to it; they're rewritten to the static folder (S3 in
production).
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# (path, static_base) -> manifest. The file only changes with a deploy, which
# restarts the process. Misses aren't cached, so a later import is picked up.
_cache = {}


def clear_cache():
    _cache.clear()


def is_relative(src):
    return '://' not in src and not src.startswith(('/', 'data:'))


def load_manifest(path, static_base):
    """The manifest with icon `src`s under `static_base`, or None (logged) if missing or invalid."""
    key = (str(path), static_base)
    if key not in _cache:
        try:
            data = json.loads(Path(path).read_text())
        except (OSError, ValueError) as err:
            logger.error('Cannot read the dashboard manifest at %s: %s', path, err)
            return None
        for icon in data.get('icons', []):
            if is_relative(icon.get('src', '')):
                icon['src'] = static_base + icon['src']
        _cache[key] = data
    return _cache[key]
