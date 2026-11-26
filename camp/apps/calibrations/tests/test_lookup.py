from datetime import datetime, timedelta, timezone as dt_timezone

from django.test import TestCase

from camp.apps.calibrations.lookup import ChunkCalibrationLookup, active_lookup
from camp.apps.calibrations.models import Calibration, CalibrationPair
from camp.apps.entries.models import PM25
from camp.apps.monitors.bam.models import BAM1022
from camp.apps.monitors.purpleair.models import PurpleAir

TRAINER = 'PM25_Trainer'


class ChunkCalibrationLookupTests(TestCase):
    def setUp(self):
        self.colocated = PurpleAir.objects.create(
            name='Colocated', position='POINT(-119.80 36.76)', county='Fresno', sensor_id=11235,
        )
        self.near = BAM1022.objects.create(name='Near', position='POINT(-119.801 36.761)', county='Fresno')
        self.far = BAM1022.objects.create(name='Far', position='POINT(-119.90 36.80)', county='Fresno')
        self.chunk_start = datetime(2023, 1, 2, tzinfo=dt_timezone.utc)
        self.chunk_end = self.chunk_start + timedelta(days=1)
        self.position = self.colocated.position

    def pair(self, reference, **kwargs):
        return CalibrationPair.objects.create(
            colocated=self.colocated, reference=reference, entry_type='pm25', **kwargs,
        )

    def calibration(self, pair, end_time, created=None, trainer=TRAINER):
        calibration = Calibration.objects.create(
            pair=pair, entry_type='pm25', trainer=trainer, formula='pm25', end_time=end_time,
        )
        if created is not None:
            Calibration.objects.filter(pk=calibration.pk).update(created=created)
        return calibration

    def entry(self, timestamp):
        return PM25(monitor=self.colocated, timestamp=timestamp, position=self.position, sensor='')

    def test_matches_get_for_entry(self):
        near, far = self.pair(self.near), self.pair(self.far)
        disabled = self.pair(self.near, is_enabled=False)
        day = timedelta(days=1)
        hour = timedelta(hours=1)
        created = datetime(2022, 12, 1, tzinfo=dt_timezone.utc)

        self.calibration(far, self.chunk_start - 10 * day)
        self.calibration(near, self.chunk_start - 5 * day, created=created)
        # Same pair and end_time as the one above, created later: wins the tie.
        self.calibration(near, self.chunk_start - 5 * day, created=created + day)
        self.calibration(near, self.chunk_start + 6 * hour, created=created + 2 * day)  # ends inside the chunk
        self.calibration(far, self.chunk_start + 12 * hour)  # inside, but farther away
        self.calibration(near, self.chunk_end + hour)  # ends after the chunk
        self.calibration(disabled, self.chunk_start - day)  # disabled pair
        self.calibration(near, self.chunk_start - day, trainer='OtherTrainer')

        lookup = ChunkCalibrationLookup(self.chunk_end)
        timestamps = [
            self.chunk_start - 20 * day,  # before every calibration
            self.chunk_start - 7 * day,  # only the far one has ended
            self.chunk_start,
            self.chunk_start + 5 * hour,
            self.chunk_start + 6 * hour,  # exactly at an end_time
            self.chunk_start + 7 * hour,
            self.chunk_start + 13 * hour,
            self.chunk_end - hour,
        ]
        found = set()
        for timestamp in timestamps:
            entry = self.entry(timestamp)
            expected = Calibration.objects.get_for_entry(entry, TRAINER)
            actual = lookup.get_for_entry(entry, TRAINER)
            assert getattr(actual, 'pk', None) == getattr(expected, 'pk', None), timestamp
            found.add(getattr(actual, 'pk', None))
        # The scenario really exercised several different outcomes.
        assert len(found) >= 4
        assert None in found

    def test_loads_candidates_once_per_combination(self):
        near = self.pair(self.near)
        self.calibration(near, self.chunk_start - timedelta(days=1))
        lookup = ChunkCalibrationLookup(self.chunk_end)
        lookup.get_for_entry(self.entry(self.chunk_start), TRAINER)
        with self.assertNumQueries(0):
            for minutes in range(0, 600, 2):
                lookup.get_for_entry(self.entry(self.chunk_start + timedelta(minutes=minutes)), TRAINER)

    def test_entry_after_the_chunk_falls_back_to_the_query(self):
        near = self.pair(self.near)
        late = self.calibration(near, self.chunk_end + timedelta(hours=1))
        lookup = ChunkCalibrationLookup(self.chunk_end)
        entry = self.entry(self.chunk_end + timedelta(hours=2))
        assert lookup.get_for_entry(entry, TRAINER).pk == late.pk

    def test_activate_scopes_the_lookup(self):
        lookup = ChunkCalibrationLookup(self.chunk_end)
        assert active_lookup() is None
        with lookup.activate():
            assert active_lookup() is lookup
        assert active_lookup() is None
