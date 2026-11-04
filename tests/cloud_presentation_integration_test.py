"""Cloud presentation integration: no real Supabase, Pi, GPIO or HTTP calls."""
import json
import os
import sys
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cloud_api import install_cloud
from cloud_model import CONFIG, MAPPING_VERSION
from cloud_store import StoreUnavailable

ORIGINAL_FLOORPLAN = json.loads((ROOT / 'static/data/floorplan.json').read_text())
TOKEN = 'test-only-device-token-32-characters-long'


def report(active=None, sequence=0):
    return {'deviceId': 'pi-01', 'bootId': str(uuid4()), 'sequence': sequence,
            'observedAt': datetime.now(timezone.utc).isoformat(), 'mappingVersion': MAPPING_VERSION,
            'flame': {s['id']: s['id'] == active for s in CONFIG['sensors']}, 'startNode': 'N33'}


class FakeStore:
    def __init__(self):
        self.row = None
        self.ingested = 0
        self.fail = False

    def ingest(self, telemetry):
        self.ingested += 1
        self.row = {'device_id': telemetry['deviceId'], 'boot_id': telemetry['bootId'],
                    'sequence': telemetry['sequence'], 'observed_at': telemetry['observedAt'],
                    'received_at': datetime.now(timezone.utc).isoformat(),
                    'mapping_version': telemetry['mappingVersion'], 'telemetry': deepcopy(telemetry)}
        return {'accepted': True, 'deviceId': telemetry['deviceId'], 'sequence': telemetry['sequence']}

    def latest(self, device_id):
        if self.fail:
            raise StoreUnavailable('offline')
        return deepcopy(self.row)

    def events(self, device_id):
        if self.fail:
            raise StoreUnavailable('offline')
        return []


class CloudPresentationIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.environ = patch.dict(os.environ, {'FIREGUARD_CLOUD': '1', 'FIREGUARD_DEVICE_ID': 'pi-01',
                                              'FIREGUARD_DEVICE_TOKEN': TOKEN}, clear=False)
        self.environ.start()
        self.app = Flask(__name__)
        install_cloud(self.app, ORIGINAL_FLOORPLAN)
        self.store = FakeStore()
        self.app.extensions['cloud_store'] = self.store
        self.client = self.app.test_client()

    def tearDown(self):
        self.environ.stop()

    def hardware(self, payload):
        return self.client.post('/api/hardware/telemetry', json=payload,
                                headers={'Authorization': 'Bearer ' + TOKEN})

    def simulation(self, history=None, action=None):
        return self.client.post('/api/cloud/simulation', json={'history': history or [], 'action': action})

    @staticmethod
    def action(name, **body):
        return {'path': '/api/simulation/' + name, 'body': body}

    def test_last_fire_from_offline_pi_does_not_block_presentation(self):
        self.assertEqual(self.hardware(report('FLM-07')).status_code, 200)
        self.store.row['received_at'] = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        before = deepcopy(self.store.row)
        count = self.store.ingested
        res = self.simulation(action=self.action('node-fire', nodeId='N10', active=True))
        self.assertEqual(res.status_code, 200, res.json)
        self.assertEqual(res.json['state']['operationMode'], 'simulation')
        self.assertIn('N10', res.json['state']['blockedNodes'])
        self.assertFalse(res.json['realState']['connections']['pi'])
        self.assertTrue(res.json['realState']['cloud']['stale'])
        self.assertIn('N7', res.json['realState']['blockedNodes'])
        self.assertEqual(before, self.store.row)
        self.assertEqual(count, self.store.ingested)

    def test_online_healthy_pi_allows_simulation(self):
        self.assertEqual(self.hardware(report()).status_code, 200)
        res = self.simulation(action=self.action('scenario', scenarioId='ticket_fire'))
        self.assertEqual(res.status_code, 200, res.json)
        self.assertTrue(res.json['realState']['connections']['pi'])
        self.assertFalse(res.json['realState']['realFireDetected'])
        self.assertIn('N14', res.json['state']['blockedNodes'])
        self.assertTrue(any(s['node'] == 'N14' for s in res.json['floorplan']['sensors']))

    def test_connected_real_fire_rejects_start_and_existing_sim_action(self):
        self.hardware(report('FLM-08'))
        real_before = deepcopy(self.store.row)
        cases = [([], None), ([self.action('node-fire', nodeId='N10', active=True)],
                              self.action('scenario', scenarioId='normal'))]
        for history, action in cases:
            with self.subTest(history=history):
                res = self.simulation(history, action)
                self.assertEqual(res.status_code, 409, res.json)
                self.assertTrue(res.json['realState']['connections']['pi'])
                self.assertTrue(res.json['realState']['realFireDetected'])
                self.assertIn('N8', res.json['realState']['blockedNodes'])
        self.assertEqual(real_before, self.store.row)

    def test_tabs_have_independent_histories_and_real_data_is_unchanged(self):
        self.hardware(report())
        real_before = deepcopy(self.store.row)
        action_a = self.action('node-fire', nodeId='N10', active=True)
        action_b = self.action('node-fire', nodeId='N7', active=True)
        a = self.simulation(action=action_a).json
        b = self.simulation(action=action_b).json
        self.assertIn('N10', a['state']['blockedNodes'])
        self.assertNotIn('N7', a['state']['blockedNodes'])
        self.assertIn('N7', b['state']['blockedNodes'])
        self.assertNotIn('N10', b['state']['blockedNodes'])
        # A repeated request with A's own history preserves only A's actions.
        a_again = self.simulation(history=a['history']).json
        self.assertIn('N10', a_again['state']['blockedNodes'])
        self.assertNotIn('N7', a_again['state']['blockedNodes'])
        self.assertEqual(real_before, self.store.row)

    def test_history_survives_function_restart_without_global_state(self):
        self.hardware(report())
        first = self.simulation(action=self.action('node-fire', nodeId='N10', active=True)).json
        new_instance = Flask('another-function-instance')
        install_cloud(new_instance, ORIGINAL_FLOORPLAN)
        new_instance.extensions['cloud_store'] = self.store
        response = new_instance.test_client().post('/api/cloud/simulation', json={
            'history': first['history'], 'action': self.action('node-fire', nodeId='N7', active=True)})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(set(response.json['state']['blockedNodes']), {'N7', 'N10'})
        self.assertEqual(self.store.ingested, 1)

    def test_malformed_or_privileged_history_never_mutates_real_data(self):
        self.hardware(report())
        before = deepcopy(self.store.row)
        for item in [{'path': '/api/hardware/flame', 'body': {'sensorId': 'FLM-07', 'active': True}},
                     {'path': '/api/simulation/node-fire', 'body': {'nodeId': 'N10', 'active': 'false'}},
                     {'path': '/api/floorplan/layout', 'body': {}}, {'path': '/api/simulation/reset'}]:
            with self.subTest(item=item):
                self.assertEqual(self.simulation(history=[item]).status_code, 400)
        self.assertEqual(before, self.store.row)

    def test_database_outage_is_not_interpreted_as_safe_pi_offline(self):
        self.store.fail = True
        self.assertEqual(self.simulation().status_code, 503)
        self.assertEqual(self.store.ingested, 0)

    def test_existing_telemetry_authentication_and_flow_still_work(self):
        self.assertEqual(self.client.post('/api/hardware/telemetry', json=report()).status_code, 401)
        self.assertEqual(self.hardware(report()).status_code, 200)
        self.assertEqual(self.store.ingested, 1)
        self.assertEqual(self.client.get('/api/state').json['overallStatus'], 'normal')


if __name__ == '__main__':
    unittest.main()
