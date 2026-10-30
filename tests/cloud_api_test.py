"""Cloud contract and stateless dashboard regression tests; no live DB needed."""
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
from cloud_model import CONFIG, MAPPING_VERSION, cloud_floorplan, project_state, validate_telemetry
from cloud_store import StoreUnavailable
from route_service import FloorGraph

FLOOR = cloud_floorplan(json.loads((Path(__file__).resolve().parents[1] / 'static/data/floorplan.json').read_text()))
TOKEN = 'test-only-device-token-32-characters-long'


def sample(active=None, sequence=0):
    return {'deviceId': 'pi-01', 'bootId': str(uuid4()), 'sequence': sequence,
            'observedAt': datetime.now(timezone.utc).isoformat(), 'mappingVersion': MAPPING_VERSION,
            'flame': {s['id']: s['id'] == active for s in CONFIG['sensors']}, 'startNode': 'N33'}


class MemoryStore:
    """Browser/API test fixture only; production always uses Supabase."""
    def __init__(self):
        self.row = None

    def ingest(self, telemetry):
        if self.row and telemetry['bootId'] == self.row['boot_id'] and telemetry['sequence'] <= self.row['sequence']:
            return {'accepted': False, 'reason': 'duplicate', 'deviceId': 'pi-01', 'sequence': self.row['sequence']}
        self.row = {'device_id': telemetry['deviceId'], 'boot_id': telemetry['bootId'],
                    'sequence': telemetry['sequence'], 'observed_at': telemetry['observedAt'],
                    'received_at': datetime.now(timezone.utc).isoformat(),
                    'mapping_version': telemetry['mappingVersion'], 'telemetry': deepcopy(telemetry)}
        return {'accepted': True, 'deviceId': 'pi-01', 'sequence': telemetry['sequence']}

    def latest(self, device_id):
        return deepcopy(self.row)

    def events(self, device_id):
        return []


class CloudApiTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'FIREGUARD_CLOUD': '1', 'FIREGUARD_DEVICE_TOKEN': TOKEN,
                                           'FIREGUARD_DEVICE_ID': 'pi-01'}, clear=False)
        self.env.start()
        self.app = Flask(__name__)
        install_cloud(self.app, FLOOR)
        self.store = MemoryStore()
        self.app.extensions['cloud_store'] = self.store
        self.client = self.app.test_client()

    def tearDown(self):
        self.env.stop()

    def post(self, data, path='/api/hardware/telemetry'):
        return self.client.post(path, json=data, headers={'Authorization': 'Bearer ' + TOKEN})

    def test_cloud_config_never_exposes_server_or_device_keys(self):
        with patch.dict(os.environ, {'SUPABASE_SERVICE_ROLE_KEY': 'private-service-key', 'SUPABASE_ANON_KEY': 'public-key'}):
            response = self.client.get('/api/cloud/config')
        self.assertTrue(response.json['enabled'])
        self.assertEqual(response.json['supabaseAnonKey'], 'public-key')
        self.assertNotIn(TOKEN, response.text)
        self.assertNotIn('private-service-key', response.text)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_unauthenticated_ingestion_is_rejected(self):
        self.assertEqual(self.client.post('/api/hardware/telemetry', json=sample()).status_code, 401)
        self.assertIsNone(self.store.row)

    def test_misconfigured_secret_is_never_published_as_public_key(self):
        import base64
        claims = base64.urlsafe_b64encode(b'{"role":"service_role"}').decode().rstrip('=')
        for key in ('sb_secret_private', 'header.' + claims + '.signature', 'same-private-key'):
            with patch.dict(os.environ, {'SUPABASE_ANON_KEY': key, 'SUPABASE_SERVICE_ROLE_KEY': 'same-private-key'}):
                response = self.client.get('/api/cloud/config')
            self.assertEqual(response.status_code, 503)
            self.assertNotIn(key, response.text)

    def test_unknown_state_is_not_safe_or_led_applied(self):
        state = self.client.get('/api/state').json
        self.assertEqual(state['overallStatus'], 'unknown')
        self.assertIsNone(state['route'])
        self.assertFalse(state['connections']['pi'])
        self.assertEqual(state['cloud']['led']['status'], 'unknown')
        self.assertEqual(state['sensorCounts']['offline'], 11)

    def test_fire_clear_and_alias(self):
        data = sample('FLM-08')
        self.assertTrue(self.post(data, '/api/hardware/batch').json['accepted'])
        state = self.client.get('/api/state').json
        self.assertEqual(state['operationMode'], 'real')
        self.assertIn('N8', state['blockedNodes'])
        self.assertEqual(state['overallStatus'], 'fire')
        self.assertEqual(state['cloud']['routeSource'], 'server_preview')
        self.assertEqual(state['cloud']['led']['status'], 'unknown')
        data['sequence'] += 1
        data['flame']['FLM-08'] = False
        self.assertTrue(self.post(data).json['accepted'])
        self.assertEqual(self.client.get('/api/state').json['overallStatus'], 'normal')

    def test_duplicate_cannot_clear_fire(self):
        data = sample('FLM-08')
        self.post(data)
        data['flame']['FLM-08'] = False
        self.assertFalse(self.post(data).json['accepted'])
        self.assertIn('N8', self.client.get('/api/state').json['blockedNodes'])

    def test_requests_do_not_depend_on_existing_python_state(self):
        self.post(sample('FLM-01'))
        app2 = Flask('fresh-instance')
        install_cloud(app2, FLOOR)
        app2.extensions['cloud_store'] = self.store
        snapshot = app2.test_client().get('/api/state').json
        self.assertIn('N20', snapshot['blockedNodes'])

    def test_location_preview_does_not_change_device_start_or_ack(self):
        self.post(sample())
        preview = self.client.get('/api/state?startNode=N37').json
        self.assertEqual(preview['startNode'], 'N37')
        self.assertEqual(preview['route']['nodes'][0], 'N37')
        self.assertEqual(preview['cloud']['routeSource'], 'server_preview')
        self.assertEqual(self.client.get('/api/state').json['startNode'], 'N33')
        self.assertEqual(self.client.get('/api/state?startNode=missing').status_code, 400)

    def test_stale_fire_retains_last_known_danger(self):
        self.post(sample('FLM-08'))
        old = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        self.store.row['received_at'] = old
        state = self.client.get('/api/state').json
        self.assertTrue(state['cloud']['stale'])
        self.assertFalse(state['connections']['pi'])
        self.assertIn('N8', state['blockedNodes'])
        self.assertTrue(state['flameSensors']['FLM-08']['active'])

    def test_delayed_observation_is_stale_even_when_just_received(self):
        data = sample()
        data['observedAt'] = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        self.post(data)
        self.assertTrue(self.client.get('/api/state').json['cloud']['stale'])

    def test_mutation_routes_cannot_touch_process_memory(self):
        for path in ('/api/mode', '/api/simulation/scenario', '/api/floorplan/layout', '/api/hardware/flame', '/api/hardware/heartbeat'):
            self.assertEqual(self.client.post(path, json={}).status_code, 409, path)

    def test_legacy_socket_is_not_exposed(self):
        self.assertEqual(self.client.get('/socket.io/?transport=polling').status_code, 404)

    def test_body_limit(self):
        self.assertEqual(self.client.post('/api/hardware/telemetry', json={'padding': 'x' * 70000},
                                         headers={'Authorization': 'Bearer ' + TOKEN}).status_code, 413)

    def test_invalid_payload_is_atomic(self):
        cases = []
        for field, value in [('sequence', True), ('sequence', -1), ('sequence', 1.5),
                             ('bootId', 'not-uuid'), ('observedAt', '2026-10-30'),
                             ('mappingVersion', 'old'), ('deviceId', 'another-pi'),
                             ('flame', {'FLM-08': True}), ('led', [])]:
            data = sample(); data[field] = value; cases.append(data)
        data = sample(); data['flame']['FLM-08'] = 'false'; cases.append(data)
        for data in cases:
            with self.subTest(data=data):
                self.assertEqual(self.post(data).status_code, 400)
                self.assertIsNone(self.store.row)

    def test_led_applied_requires_matching_valid_pi_route(self):
        data = sample()
        data['led'] = {'status': 'applied', 'routeId': 'route-1'}
        self.assertEqual(self.post(data).status_code, 400)
        data['route'] = {**FloorGraph(FLOOR).shortest_route('N33').as_dict(), 'id': 'route-1'}
        data['led']['segments'] = [{'id': 'S1', 'on': True, 'color': '#00ff00'}]
        self.assertEqual(self.post(data).status_code, 200)
        state = self.client.get('/api/state').json
        self.assertEqual(state['cloud']['routeSource'], 'pi')
        self.assertEqual(state['cloud']['led']['status'], 'applied')

    def test_route_cannot_pass_fire_or_invent_an_edge(self):
        data = sample('FLM-10')
        data['route'] = {**FloorGraph(FLOOR).shortest_route('N33').as_dict(), 'id': 'route-1'}
        self.assertEqual(self.post(data).status_code, 400)
        data = sample()
        data['route'] = {**FloorGraph(FLOOR).shortest_route('N33').as_dict(), 'id': 'route-1'}
        data['route']['edges'][0] = 'invented'
        self.assertEqual(self.post(data).status_code, 400)

    def test_database_outage_is_explicit_not_fake_safe(self):
        with patch.object(self.store, 'latest', side_effect=StoreUnavailable('private failure')):
            response = self.client.get('/api/state')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private failure', response.text)

    def test_config_matches_seed_nodes(self):
        expected = ['N20'] + [f'N{i}' for i in range(2, 12)]
        self.assertEqual([s['node'] for s in FLOOR['sensors']], expected)
        graph = FloorGraph(FLOOR)
        self.assertTrue(all(s['node'] in graph.nodes for s in FLOOR['sensors']))

    def test_actual_templates_render_in_cloud_and_local_modes(self):
        import app as server
        previous = server.app.config['CLOUD_ENABLED']
        try:
            for enabled in (False, True):
                server.app.config['CLOUD_ENABLED'] = enabled
                client = server.app.test_client()
                for path in ('/', '/3d', '/mobile/N1'):
                    self.assertEqual(client.get(path).status_code, 200, (enabled, path))
        finally:
            server.app.config['CLOUD_ENABLED'] = previous


if __name__ == '__main__':
    unittest.main()
