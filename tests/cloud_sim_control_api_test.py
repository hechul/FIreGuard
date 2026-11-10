import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from flask import Flask
from cloud_api import install_cloud

FLOOR = json.loads((Path(__file__).resolve().parents[1] / 'static/data/floorplan.json').read_text())
DEVICE = 'device-token-for-testing-only-1234567890'
OPERATOR = 'operator-token-for-testing-only-1234567890'

class Commands:
    def __init__(self): self.items = []
    def create(self, device, command_id, start, fire):
        self.items.append((device, start, fire))
        return {'id': command_id, 'status': 'pending'}
    def latest(self, device): return None
    def claim(self, device): return None
    def complete(self, device, command_id, token, result): return {'status': result['status']}

class ControlTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'FIREGUARD_CLOUD':'1', 'FIREGUARD_SIM_CONTROL_ENABLED':'1', 'FIREGUARD_DEVICE_TOKEN':DEVICE, 'FIREGUARD_SIM_OPERATOR_TOKEN':OPERATOR}, clear=False)
        self.env.start()
        app = Flask(__name__)
        install_cloud(app, FLOOR)
        self.commands = Commands()
        app.extensions['sim_command_store'] = self.commands
        self.app = app
        self.client = app.test_client()
        self.real = {'connections': {'pi': True}, 'realFireDetected': False, 'flameSensors': {'FLM-01': {'connected': True}}}
        class Store:
            def latest(self, device): return None
            def events(self, device): return []
        app.extensions['cloud_store'] = Store()
        self.projection = patch('cloud_api.project_state', side_effect=lambda *a, **k: self.real)
        self.projection.start()
    def tearDown(self): self.projection.stop(); self.env.stop()
    def send(self, body, token=OPERATOR):
        return self.client.post('/api/sim-control/commands', json=body, headers={'Authorization':'Bearer '+token})
    def test_auth_and_graph_validation(self):
        self.assertEqual(self.send({'startNode':'N4','fireNode':'N10'}, DEVICE).status_code, 401)
        self.assertEqual(self.send({'startNode':'N40','fireNode':'N10'}).status_code, 400)
        self.assertEqual(self.send({'startNode':[], 'fireNode':'N10'}).status_code, 400)
        self.assertEqual(self.commands.items, [])
    def test_preview_request_is_queued_without_real_telemetry(self):
        self.real['connections']['pi'] = False
        self.assertEqual(self.send({'startNode':'N4','fireNode':'N10'}).status_code, 200)
        self.assertEqual(self.commands.items, [('pi-01','N4','N10')])
    def test_disabled_even_with_token(self):
        with patch.dict(os.environ, {'FIREGUARD_SIM_CONTROL_ENABLED':'0'}):
            self.assertEqual(self.send({'startNode':'N4','fireNode':'N10'}).status_code, 503)
    def test_device_and_operator_are_separate(self):
        self.assertEqual(self.client.get('/api/hardware/sim-command', headers={'Authorization':'Bearer '+OPERATOR}).status_code, 401)
        self.assertEqual(self.client.get('/api/hardware/sim-command', headers={'Authorization':'Bearer '+DEVICE}).status_code, 200)
        self.assertEqual(self.client.get('/api/sim-control/latest', headers={'Authorization':'Bearer '+DEVICE}).status_code, 401)
