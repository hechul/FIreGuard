import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hardware.real_fire_latch import RealFireLatch

IDS = [f'FLM-{i:02}' for i in range(1, 12)]


class RealFireLatchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'state' / 'real-fire.json'
        self.now = 100.0
        self.state = RealFireLatch(IDS, self.path, stale_after=5, clock=lambda: self.now)

    def test_multiple_alarms_persist_through_normal_samples_and_restart(self):
        self.state.update({'FLM-01': True, 'FLM-07': True})
        result = self.state.update({'FLM-01': False, 'FLM-07': False})
        self.assertEqual(result['latchedSensorIds'], ['FLM-01', 'FLM-07'])
        restarted = RealFireLatch(IDS, self.path, clock=lambda: self.now)
        after = restarted.snapshot()
        self.assertEqual(after['latchedSensorIds'], ['FLM-01', 'FLM-07'])
        self.assertIsNone(after['sensors']['FLM-01']['rawActive'])
        self.assertFalse(after['sensors']['FLM-01']['connected'])
        with self.assertRaises(ValueError):
            restarted.clear(['FLM-01'])

    def test_selective_clear_requires_fresh_inactive_and_is_atomic(self):
        self.state.update({'FLM-01': True, 'FLM-02': True})
        self.state.update({'FLM-01': False})
        with self.assertRaises(ValueError):
            self.state.clear(['FLM-01', 'FLM-02'])
        self.assertEqual(self.state.snapshot()['latchedSensorIds'], ['FLM-01', 'FLM-02'])
        result = self.state.clear(['FLM-01'])
        self.assertEqual(result['latchedSensorIds'], ['FLM-02'])
        self.state.update({'FLM-02': False})
        self.now += 6
        with self.assertRaises(ValueError):
            self.state.clear(['FLM-02'])
        self.assertEqual(self.state.snapshot()['latchedSensorIds'], ['FLM-02'])

    def test_failed_write_keeps_alarm_in_memory_and_retries(self):
        with patch.object(self.state, '_persist', side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                self.state.update({'FLM-10': True})
        self.assertEqual(self.state.snapshot()['latchedSensorIds'], ['FLM-10'])
        self.assertTrue(self.state.snapshot()['persistencePending'])
        self.state.update({'FLM-10': False})
        self.assertFalse(self.state.snapshot()['persistencePending'])
        self.assertEqual(json.loads(self.path.read_text())['latched'], ['FLM-10'])

    def test_failed_clear_never_drops_alarm(self):
        self.state.update({'FLM-11': True})
        self.state.update({'FLM-11': False})
        with patch.object(self.state, '_persist', side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                self.state.clear(['FLM-11'])
        self.assertEqual(self.state.snapshot()['latchedSensorIds'], ['FLM-11'])
        self.assertEqual(json.loads(self.path.read_text())['latched'], ['FLM-11'])

    def test_bad_input_does_not_change_state(self):
        for readings in ({}, {'FLM-01': 1}, {'FLM-99': True}, {'FLM-01': True, 'FLM-02': 'false'}):
            with self.subTest(readings=readings), self.assertRaises(ValueError):
                self.state.update(readings)
        self.assertFalse(self.state.snapshot()['realFireDetected'])
        self.assertFalse(self.path.exists())

    def test_cloud_restore_is_durable_union_but_never_fakes_fresh_input(self):
        self.state.update({'FLM-01': True})
        state = self.state.restore(['FLM-07'])
        self.assertEqual(state['latchedSensorIds'], ['FLM-01','FLM-07'])
        self.assertFalse(state['sensors']['FLM-07']['connected'])
        self.assertIsNone(state['sensors']['FLM-07']['rawActive'])
        restarted = RealFireLatch(IDS, self.path, clock=lambda: self.now)
        self.assertEqual(restarted.snapshot()['latchedSensorIds'], ['FLM-01','FLM-07'])
        with self.assertRaises(ValueError): restarted.clear(['FLM-07'])

    def test_corrupt_or_unknown_stored_latch_fails_closed(self):
        self.path.parent.mkdir(parents=True)
        for raw in ('{', '{"version":1,"latched":["FLM-99"]}', '{"version":1,"latched":["FLM-01","FLM-01"]}'):
            self.path.write_text(raw)
            with self.subTest(raw=raw), self.assertRaises(RuntimeError):
                RealFireLatch(IDS, self.path)


if __name__ == '__main__':
    unittest.main()
