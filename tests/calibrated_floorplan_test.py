"""Calibration is reversible for old Pi reports and never rewrites source data."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from hardware.real_ticket_overlay import calibrated_floorplan, legacy_room5_floorplan
from cloud_model import cloud_floorplan


class CalibratedFloorplanTest(unittest.TestCase):
    def test_round_trip_and_sensor_identity(self):
        floor = json.loads((Path(__file__).resolve().parents[1] / 'static/data/floorplan.json').read_text(encoding='utf-8'))
        original = deepcopy(floor)
        legacy = legacy_room5_floorplan(floor)
        self.assertEqual(calibrated_floorplan(legacy), floor)
        self.assertEqual(calibrated_floorplan(floor), floor)
        self.assertEqual(floor, original)
        self.assertEqual(legacy['sensors'], floor['sensors'])
        self.assertEqual(next(s['node'] for s in cloud_floorplan(floor)['sensors'] if s['id'] == 'FLM-02'), 'N2')
        self.assertNotIn('N41', {n['id'] for n in legacy['nodes']})

    def test_conflicting_calibration_rejected(self):
        floor = json.loads((Path(__file__).resolve().parents[1] / 'static/data/floorplan.json').read_text(encoding='utf-8'))
        next(e for e in floor['edges'] if e['id'] == 'E40')['to'] = 'N3'
        with self.assertRaises(ValueError):
            calibrated_floorplan(floor)
