from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from camp.apps.tempo.models import Granule
from camp.apps.tempo.tasks import fetch_tempo, fetch_tempo_final
from camp.utils.datetime import localtime


class FetchTempoTests(TestCase):
    @patch('camp.apps.tempo.tasks.sync_granule')
    def test_fetch_tempo_syncs_current_hour_for_every_product(self, mock_sync):
        fetch_tempo.call_local()

        products_synced = {call.args[0] for call in mock_sync.call_args_list}
        assert products_synced == {p for p, _ in Granule.Product.choices}
        assert mock_sync.call_count == len(Granule.Product.choices)

    @patch('camp.apps.tempo.tasks.sync_granule')
    def test_fetch_tempo_uses_top_of_the_hour(self, mock_sync):
        fetch_tempo.call_local()

        timestamps = {call.args[1] for call in mock_sync.call_args_list}
        assert len(timestamps) == 1
        timestamp = timestamps.pop()
        assert timestamp.minute == 0 and timestamp.second == 0

    @patch('camp.apps.tempo.tasks.sync_granule')
    def test_fetch_tempo_targets_a_lookback_hour_not_the_current_hour(self, mock_sync):
        # NASA's NRT latency is ~180 min -- the current hour's data can't
        # exist yet, so fetch_tempo must target a past hour, not "now".
        fetch_tempo.call_local()

        timestamp = {call.args[1] for call in mock_sync.call_args_list}.pop()
        now_hour = timezone.now().replace(minute=0, second=0, microsecond=0)
        assert timestamp == now_hour - timedelta(hours=3)

    @patch('camp.apps.tempo.tasks.sync_granule')
    def test_fetch_tempo_continues_past_a_single_product_failure(self, mock_sync):
        mock_sync.side_effect = [RuntimeError('NASA hiccup')] + [None] * 10

        fetch_tempo.call_local()

        assert mock_sync.call_count == len(Granule.Product.choices)


class FetchTempoFinalTests(TestCase):
    @patch('camp.apps.tempo.tasks.sync_granule')
    def test_fetch_tempo_final_syncs_all_24_hours_of_yesterday_for_every_product(self, mock_sync):
        fetch_tempo_final.call_local()

        assert mock_sync.call_count == 24 * len(Granule.Product.choices)

        yesterday = (localtime() - timedelta(days=1)).date()
        # Compare in LA-local time, not UTC -- "yesterday" is an LA-calendar
        # concept here, and each timestamp's raw UTC .date() would disagree
        # with it for the hours before/after LA midnight.
        dates_synced = {localtime(call.args[1]).date() for call in mock_sync.call_args_list}
        assert dates_synced == {yesterday}

    @patch('camp.apps.tempo.tasks.sync_granule')
    def test_fetch_tempo_final_continues_past_individual_hour_failures(self, mock_sync):
        mock_sync.side_effect = [RuntimeError('NASA hiccup')] + [None] * 200

        fetch_tempo_final.call_local()

        assert mock_sync.call_count == 24 * len(Granule.Product.choices)


class SyncTempoReprocessingTests(TestCase):
    @patch('camp.apps.tempo.tasks.sync_granule')
    def test_resyncs_rolling_90_day_window_for_every_product(self, mock_sync):
        from camp.apps.tempo.tasks import sync_tempo_reprocessing

        sync_tempo_reprocessing.call_local()

        assert mock_sync.call_count == 90 * 24 * len(Granule.Product.choices)
