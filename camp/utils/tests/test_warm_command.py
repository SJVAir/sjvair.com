from io import StringIO
from unittest import mock

import pytest
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase

RESULT = {'warmed': 3, 'skipped': 1, 'failed': 0, 'seconds': 0.5}


class WarmExplorerCachesTests(SimpleTestCase):
    def run_command(self, *args):
        out = StringIO()
        with mock.patch('camp.apps.pesticides.warm.warm', return_value=RESULT) as pesticides, \
                mock.patch('camp.apps.emissions.warm.warm', return_value=RESULT) as emissions:
            call_command('warm_explorer_caches', *args, stdout=out, stderr=StringIO())
        return out.getvalue(), pesticides, emissions

    def test_warms_every_explorer_by_default(self):
        out, pesticides, emissions = self.run_command()
        pesticides.assert_called_once_with(force=False)
        emissions.assert_called_once_with(force=False)
        assert 'pesticides: 3 warmed, 1 already warm, 0 failed' in out

    def test_one_explorer_with_force(self):
        out, pesticides, emissions = self.run_command('emissions', '--force')
        emissions.assert_called_once_with(force=True)
        pesticides.assert_not_called()

    def test_unknown_explorer(self):
        with pytest.raises(CommandError):
            call_command('warm_explorer_caches', 'nope', stdout=StringIO())
