import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hardware.cloud_flame_reader import CONFIG, StableInputs
from cloud_model import cloud_floorplan, validate_telemetry
from datetime import datetime, timezone
from uuid import uuid4
import json


class CloudFlameReaderTest(unittest.TestCase):
    def test_active_low_debounce_and_all_channels(self):
        ids = [s['id'] for s in CONFIG['sensors']]
        self.assertEqual(len(ids), 11)
        reader = StableInputs(ids)
        raw = {sid: True for sid in ids}
        self.assertIsNone(reader.sample(raw)[1])
        self.assertIsNone(reader.sample(raw)[1])
        changed, snapshot = reader.sample(raw)
        self.assertTrue(changed)
        self.assertFalse(any(snapshot.values()))
        raw['FLM-08'] = False
        self.assertFalse(reader.sample(raw)[1]['FLM-08'])
        self.assertFalse(reader.sample(raw)[1]['FLM-08'])
        self.assertTrue(reader.sample(raw)[1]['FLM-08'])
        raw['FLM-08'] = True
        for _ in range(3):
            changed, snapshot = reader.sample(raw)
        self.assertTrue(changed)
        self.assertFalse(snapshot['FLM-08'])

    def test_reader_snapshot_matches_cloud_contract(self):
        floor = json.loads((Path(__file__).resolve().parents[1] / 'static/data/floorplan.json').read_text())
        payload = {'deviceId': 'pi-01', 'bootId': str(uuid4()), 'sequence': 0,
                   'observedAt': datetime.now(timezone.utc).isoformat(), 'mappingVersion': CONFIG['mappingVersion'],
                   'flame': {s['id']: s['id'] == 'FLM-08' for s in CONFIG['sensors']},
                   'led': {'status': 'unknown'}}
        normalized = validate_telemetry(payload, cloud_floorplan(floor), 'pi-01')
        self.assertTrue(normalized['flame']['FLM-08'])
        self.assertEqual(normalized['led']['status'], 'unknown')


if __name__ == '__main__':
    unittest.main()
