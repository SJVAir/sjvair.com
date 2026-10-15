"""
What an explorer's import audit is made of (emissions.audit, and the
pesticides one): a Step per import with its status, and the report the
audit_*_imports commands print -- one row per step, then the commands to run
for anything not done, in order, with the cache clear last.
"""
from dataclasses import dataclass, field

from django.core.management.base import CommandError

OK = 'ok'
PARTIAL = 'partial'
MISSING = 'missing'
STALE = 'stale'
NEEDED = 'needed'

# The report's colours (Django's command styles) per status.
STYLES = {OK: 'SUCCESS', PARTIAL: 'WARNING', STALE: 'WARNING', NEEDED: 'WARNING', MISSING: 'ERROR'}

CACHE_CLEAR = 'python manage.py shell -c "from django.core.cache import cache; cache.clear()"'


@dataclass
class Step:
    """One import step: the command as you'd run it, its status, what was found, and the command to fix it (if anything's wrong)."""
    command: str
    status: str
    found: str
    fix: str = ''
    notes: list = field(default_factory=list)

    @property
    def done(self):
        return self.status == OK


def report(command, steps, *, strict=False):
    """
    Print `steps` on a management `command`'s stdout: each step's status,
    command and what was found (notes under it); how many look done; and the
    fixes to run, each once, in order, then the cache clear (the explorers'
    caches last a day and imports don't clear them all). `strict` raises
    CommandError (a non-zero exit) when any step isn't done.
    """
    width = max(len(step.command) for step in steps)
    for step in steps:
        status = getattr(command.style, STYLES[step.status])(f'{step.status.upper():<8}')
        command.stdout.write(f'{status} {step.command:<{width}}  {step.found}')
        for note in step.notes:
            command.stdout.write(f'{"":<8} {"":<{width}}  {note}')

    todo = [step for step in steps if not step.done]
    command.stdout.write('')
    command.stdout.write(f'{len(steps) - len(todo)} of {len(steps)} steps look done.')
    if not todo:
        return
    command.stdout.write('\nTo finish, in this order:')
    seen = set()
    for step in todo:
        if step.fix and step.fix not in seen:
            seen.add(step.fix)
            command.stdout.write(f'  {step.fix}')
    command.stdout.write(f'  {CACHE_CLEAR}')
    if strict:
        raise CommandError(f'{len(todo)} import step(s) not done.')
