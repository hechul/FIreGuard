"""Cloud simulation is isolated and never masks a connected live fire."""
import json
import os
import sys
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flask import Flask
from cloud_api import install_cloud
from cloud_model import CONFIG, MAPPING_VERSION
from cloud_store import StoreUnavailable

ROOT = Path(__file__).resolve().parents[1]
PLAN = json.loads((ROOT / 'static/data/floorplan.json').read_text())


class Store:
    def __init__(self):
        self.row = None
        self.calls = 0
        self.fire_after = None

    def latest(self, device_id):
        self.calls += 1
        if self.fire_after is not None and self.calls >= self.fire_after:
            return self.fire_row()
        return deepcopy(self.row)

    def events(self, device_id):
        return []

    def fire_row(self, age=0):
        stamp = (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat()
        data = {'flame': {s['id']: s['id'] == 'FLM-07' for s in CONFIG['sensors']},
                'startNode': 'N33', 'led': {'status': 'unknown'}}
        return {'device_id': 'pi-01', 'boot_id': str(uuid4()), 'sequence': 0,
                'observed_at': stamp, 'received_at': stamp, 'telemetry': data}


class SimulationTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'FIREGUARD_CLOUD': '1', 'FIREGUARD_DEVICE_ID': 'pi-01'}, clear=True)
        self.env.start()
        self.app = Flask(__name__)
        install_cloud(self.app, PLAN)
        self.store = Store()
        self.app.extensions['cloud_store'] = self.store
        self.client = self.app.test_client()

    def tearDown(self):
        self.env.stop()

    def simulate(self, history=None, action=None):
        return self.client.post('/api/cloud/simulation', json={'history': history or [], 'action': action})

    def test_separate_sessions_and_normal_local_scenarios(self):
        a = self.simulate(action={'path': '/api/simulation/scenario', 'body': {'scenarioId': 'east_exit_fire'}})
        self.assertEqual(a.status_code, 200)
        self.assertEqual(a.json['state']['operationMode'], 'simulation')
        self.assertIn('N10', a.json['state']['blockedNodes'])
        self.assertIn('FLM-15', [s['id'] for s in a.json['floorplan']['sensors']])
        b = self.simulate()
        self.assertEqual(b.status_code, 200)
        self.assertEqual(b.json['state']['blockedNodes'], [])
        self.assertIsNone(self.store.row)
        c = self.simulate(a.json['history'], {'path': '/api/simulation/start-node', 'body': {'nodeId': 'N8'}})
        self.assertEqual(c.status_code, 200)
        self.assertEqual(c.json['state']['startNode'], 'N8')
        self.assertIn('N10', c.json['state']['blockedNodes'])

    def test_all_local_scenarios_work_with_local_sensor_mapping(self):
        for name in ('normal','east_exit_fire','ticket_fire','cinema4_fire','large_fire',
                     'east_shutter','mid_route_block','crowd_congestion','fallback_toilet',
                     'fallback_descender','no_route','server_off','fire_server_off','server_on',
                     'pi_off','pi_on','sensor_fault','sensor_recover'):
            with self.subTest(scenario=name):
                response = self.simulate(action={'path': '/api/simulation/scenario', 'body': {'scenarioId': name}})
                self.assertEqual(response.status_code, 200, response.json)

    def test_live_real_fire_blocks_every_action(self):
        self.store.row = self.store.fire_row()
        result = self.simulate(action={'path': '/api/simulation/scenario', 'body': {'scenarioId': 'normal'}})
        self.assertEqual(result.status_code, 409)
        self.assertFalse(result.json['ok'])
        self.assertTrue(result.json['realState']['realFireDetected'])
        self.assertTrue(result.json['realState']['connections']['pi'])

    def test_offline_old_fire_does_not_block_simulation(self):
        self.store.row = self.store.fire_row(age=30)
        result = self.simulate()
        self.assertEqual(result.status_code, 200)
        self.assertFalse(result.json['realState']['connections']['pi'])
        self.assertTrue(result.json['realState']['realFireDetected'])

    def test_actual_fire_arriving_during_simulation_is_not_suppressed(self):
        self.store.fire_after = 2
        result = self.simulate()
        self.assertEqual(result.status_code, 409)
        self.assertTrue(result.json['realState']['realFireDetected'])

    def test_database_failure_never_claims_live_is_safe(self):
        with patch.object(self.store, 'latest', side_effect=StoreUnavailable('private')):
            result = self.simulate()
        self.assertEqual(result.status_code, 503)
        self.assertNotIn('private', result.text)

    def test_only_bounded_valid_simulation_actions_allowed(self):
        for action in ({'path': '/api/hardware/flame', 'body': {'sensorId': 'FLM-15', 'active': True}},
                       {'path': '/api/simulation/flame', 'body': {'sensorId': 'FLM-15', 'active': 'true'}},
                       {'path': '/api/simulation/edge-weight', 'body': {'edgeId': 'E02', 'weight': float('nan')}},
                       {'path': '/api/simulation/node-fire', 'body': {'nodeId': 'N100000', 'active': True}}):
            with self.subTest(action=action):
                self.assertEqual(self.simulate(action=action).status_code, 400)
        self.assertEqual(self.simulate(history=[{'path': '/bad', 'body': {}}] * 101).status_code, 400)
        self.assertIsNone(self.store.row)


if __name__ == '__main__':
    unittest.main()
