from datetime import datetime, timezone as dt_timezone
from unittest.mock import patch

from django.core.management import call_command
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
