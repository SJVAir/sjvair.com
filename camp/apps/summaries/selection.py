"""
Which entry types get summarized, and for whom.

Two switches turn summaries on:

- the entry model's `summarize = True` flag: air-quality types, summarized
  for every monitor type and, from those monitor rows, for regions;
- `'summarize': True` in a monitor type's ENTRY_CONFIG: a type summarized
  only for that monitor type (CIMIS weather). These never get region rows.

Every summaries call site picks its entry types from here.
"""

from camp.apps.entries.utils import get_all_entry_models
from camp.apps.monitors.models import Monitor


def _by_entry_type(models):
    return sorted(models, key=lambda m: m.entry_type)


def is_summarized(monitor_model, entry_model):
    """Whether `entry_model` is summarized for this monitor type (class or instance)."""
    if entry_model.summarize:
        return True
    return bool(monitor_model.ENTRY_CONFIG.get(entry_model, {}).get('summarize', False))


def monitor_summary_entry_models(monitor_model):
    """Entry models summarized for this monitor type (class or instance), sorted by entry_type."""
    return _by_entry_type(m for m in get_all_entry_models() if is_summarized(monitor_model, m))


def region_summary_entry_models():
    """Entry models with summarize = True: the types summarized for regions."""
    return _by_entry_type(m for m in get_all_entry_models() if m.summarize)


def switch_entry_types():
    """
    Entry types turned on by some monitor type's ENTRY_CONFIG and not by the model flag.

    The summaries endpoint picks its `late` settle margin per entry type from
    this set (camp/api/v2/summaries/endpoints.py), not per monitor: every
    monitor's rows of a switch type get the late margin. That holds while only
    CIMIS uses the switch. A second monitor type switching on an air type would
    need a per-monitor decision there.
    """
    return frozenset(
        entry_model.entry_type
        for monitor_model in Monitor.get_subclasses()
        for entry_model, config in monitor_model.ENTRY_CONFIG.items()
        if config.get('summarize') and not entry_model.summarize
    )


def switch_entry_models():
    """The entry models of switch_entry_types(), sorted by entry_type."""
    switch_types = switch_entry_types()
    return _by_entry_type(m for m in get_all_entry_models() if m.entry_type in switch_types)


def monitor_types_summarizing(entry_model):
    """Monitor subclasses for which `entry_model` is summarized."""
    return [m for m in Monitor.get_subclasses() if is_summarized(m, entry_model)]
