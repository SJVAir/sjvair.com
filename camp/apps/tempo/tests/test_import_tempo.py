from datetime import datetime, timezone as dt_timezone
from unittest.mock import patch

from django.core.management import call_command
from django.db.utils import OperationalError
from django.test import TestCase


class ImportTempoTests(TestCase):
    @patch('camp.apps.tempo.management.commands.import_tempo.sync_granule')
    def test_imports_every_hour_in_range_for_given_product(self, mock_sync):
        call_command(
            'import_tempo',
            '--start', '2023-08-15',
            '--end', '2023-08-15',
            '--product', 'no2',
        )

        assert mock_sync.call_count == 24
        for call in mock_sync.call_args_list:
            assert call.args[0] == 'no2'

    @patch('camp.apps.tempo.management.commands.import_tempo.sync_granule')
    def test_imports_all_products_when_none_specified(self, mock_sync):
        call_command('import_tempo', '--start', '2023-08-15', '--end', '2023-08-15')

        assert mock_sync.call_count == 24 * 4  # 4 products

    @patch('camp.apps.tempo.management.commands.import_tempo.sync_granule')
    def test_continues_past_individual_hour_failures(self, mock_sync):
        mock_sync.side_effect = [RuntimeError('NASA hiccup')] + [None] * 100

        call_command(
            'import_tempo',
            '--start', '2023-08-15',
            '--end', '2023-08-15',
            '--product', 'no2',
        )

        assert mock_sync.call_count == 24

    @patch('camp.apps.tempo.management.commands.import_tempo.connections')
    @patch('camp.apps.tempo.management.commands.import_tempo.sync_granule')
    def test_reconnects_and_continues_after_a_dead_db_connection(self, mock_sync, mock_connections):
        # Regression test: a bare long-running management command never
        # hits Django's request/task-boundary reconnect signals, so a dead
        # connection used to stay dead for the rest of the run -- every
        # remaining hour would fail identically while the command still
        # printed "done" for every day. Force-closing all connections on a
        # database error is what lets subsequent hours succeed again.
        mock_sync.side_effect = (
            [OperationalError('server closed the connection unexpectedly')]
            + [None] * 100
        )

        call_command(
            'import_tempo',
            '--start', '2023-08-15',
            '--end', '2023-08-15',
            '--product', 'no2',
        )

        assert mock_sync.call_count == 24
        mock_connections.close_all.assert_called_once()

    @patch('camp.apps.tempo.management.commands.import_tempo.sync_granule')
    def test_does_not_close_connections_on_non_database_errors(self, mock_sync):
        mock_sync.side_effect = [RuntimeError('NASA hiccup')] + [None] * 100

        with patch('camp.apps.tempo.management.commands.import_tempo.connections') as mock_connections:
            call_command(
                'import_tempo',
                '--start', '2023-08-15',
                '--end', '2023-08-15',
                '--product', 'no2',
            )

            mock_connections.close_all.assert_not_called()
