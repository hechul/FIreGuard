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
    def create_v2(self, device, command_id, start, fires):
        self.items.append((device, start, fires))
        return {'id': command_id, 'status': 'pending'}
    def claim_v2(self, device): return {'fireNodes': ['N7','N10'], 'fireNode': '__MULTI__'}
    def complete(self, device, command_id, token, result): return {'status': result['status']}

class Cancellations:
    def cancel(self, device, command_id): return {'id': command_id, 'status': 'rejected', 'cancelRequested': True}
    def check(self, device, command_id, claim_token): return {'active': False, 'cancelRequested': True}

class ControlTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'FIREGUARD_CLOUD':'1', 'FIREGUARD_SIM_CONTROL_ENABLED':'1', 'FIREGUARD_DEVICE_TOKEN':DEVICE, 'FIREGUARD_SIM_OPERATOR_TOKEN':OPERATOR}, clear=False)
        self.env.start()
        app = Flask(__name__)
        install_cloud(app, FLOOR)
        self.commands = Commands()
        app.extensions['sim_command_store'] = self.commands
        app.extensions['sim_cancellation_store'] = Cancellations()
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
    def test_multiple_fires_validate_without_changing_legacy(self):
        self.assertEqual(self.send({'startNode':'N4','fireNodes':['N7','N10']}).status_code, 200)
        self.assertEqual(self.commands.items, [('pi-01','N4',['N7','N10'])])
        for bad in ([], ['N10','N10'], ['N10','N40'], ['N10', {}]):
            self.assertEqual(self.send({'startNode':'N4','fireNodes':bad}).status_code, 400)
        self.assertEqual(self.client.get('/api/hardware/sim-command?version=2', headers={'Authorization':'Bearer '+DEVICE}).json['command']['fireNode'], '__MULTI__')
    def test_disabled_even_with_token(self):
        with patch.dict(os.environ, {'FIREGUARD_SIM_CONTROL_ENABLED':'0'}):
            self.assertEqual(self.send({'startNode':'N4','fireNode':'N10'}).status_code, 503)
    def test_device_and_operator_are_separate(self):
        self.assertEqual(self.client.get('/api/hardware/sim-command', headers={'Authorization':'Bearer '+OPERATOR}).status_code, 401)
        self.assertEqual(self.client.get('/api/hardware/sim-command', headers={'Authorization':'Bearer '+DEVICE}).status_code, 200)
        self.assertEqual(self.client.get('/api/sim-control/latest', headers={'Authorization':'Bearer '+DEVICE}).status_code, 401)
    def test_cancel_and_check_require_correct_tokens(self):
        cancel = '/api/sim-control/cancel'
        check = '/api/hardware/sim-command/check'
        operator = {'Authorization':'Bearer '+OPERATOR}
        device = {'Authorization':'Bearer '+DEVICE}
        self.assertEqual(self.client.post(cancel, json={'id':'one'}, headers=device).status_code, 401)
        self.assertEqual(self.client.post(cancel, json={'id':'one'}, headers=operator).status_code, 200)
        self.assertEqual(self.client.post(check, json={'id':'one','claimToken':'two'}, headers=operator).status_code, 401)
        response = self.client.post(check, json={'id':'one','claimToken':'two'}, headers=device)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json['active'])
