import json
import tempfile
import unittest
from pathlib import Path

from hardware.real_pi_service import RealPiState, create_app

FLOOR = json.loads((Path(__file__).resolve().parents[1] / 'static/data/floorplan.json').read_text())
TOKEN = 'unit-test-real-local-secret-32-characters'

class RealPiStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'alarms.json'
        self.now = 100.0
        self.sensor_ids = [s['id'] for s in FLOOR['sensors'] if s.get('type') == 'flame']
        self.one, self.two = self.sensor_ids[:2]
        self.nodes = {s['id']: s['node'] for s in FLOOR['sensors'] if s.get('type') == 'flame'}
        self.state = RealPiState(FLOOR, self.path, clock=lambda: self.now)
        self.client = create_app(self.state, TOKEN).test_client()

    def post(self, values):
        return self.client.post('/api/hardware/batch', json={'flame': values})

    def test_multiple_latch_persist_and_disconnected_blocked(self):
        self.assertEqual(self.post({sid: False for sid in self.sensor_ids}).status_code, 200)
        self.assertEqual(self.post({self.one: True, self.two: True}).status_code, 200)
        self.assertEqual(self.post({self.one: False, self.two: False}).status_code, 200)
        snapshot = self.client.get('/api/real/state').json
        self.assertEqual(set(snapshot['realFireSensorIds']), {self.one, self.two})
        self.assertEqual(set(snapshot['blockedNodes']), {self.nodes[self.one], self.nodes[self.two]})
        self.now += 16
        snapshot = self.state.snapshot()
        self.assertTrue(snapshot['realFireDetected'])
        self.assertFalse(snapshot['flameSensors'][self.one]['connected'])
        self.assertIn(self.nodes[self.one], snapshot['blockedNodes'])
        self.assertFalse(snapshot['ledSafetyReady'])
        restarted = RealPiState(FLOOR, self.path, clock=lambda: self.now)
        self.assertEqual(set(restarted.snapshot()['realFireSensorIds']), {self.one, self.two})
        self.assertTrue(all(not x['connected'] for x in restarted.snapshot()['flameSensors'].values()))

    def test_clear_is_authenticated_selective_and_requires_fresh_inactive(self):
        self.post({self.one: True, self.two: True})
        self.post({self.one: False})
        data = {'sensorIds': [self.one]}
        self.assertEqual(self.client.post('/api/real/clear', json=data).status_code, 401)
        headers = {'X-Fireguard-Local-Token': TOKEN}
        self.assertEqual(self.client.post('/api/real/clear', json={'sensorIds':[self.one,self.two]}, headers=headers).status_code, 409)
        self.assertEqual(self.client.post('/api/real/clear', json=data, headers=headers).status_code, 200)
        self.assertEqual(self.state.snapshot()['realFireSensorIds'], [self.two])
        self.now += 16
        self.assertEqual(self.client.post('/api/real/clear', json={'sensorIds':[self.two]}, headers=headers).status_code, 409)
        self.assertEqual(self.state.snapshot()['realFireSensorIds'], [self.two])

    def test_rejects_invalid_sensor_and_nonlocal_access(self):
        self.assertEqual(self.post({self.one: 1}).status_code, 400)
        self.assertEqual(self.post({'FLM-unknown': True}).status_code, 400)
        self.assertEqual(self.client.get('/api/real/state', environ_base={'REMOTE_ADDR':'192.0.2.5'}).status_code, 403)
        with self.assertRaises(ValueError): create_app(self.state, 'short')

    def test_restore_requires_token_and_does_not_mark_input_fresh(self):
        body = {'sensorIds':[self.one,self.two]}
        self.assertEqual(self.client.post('/api/real/restore',json=body).status_code,401)
        reply=self.client.post('/api/real/restore',json=body,headers={'X-Fireguard-Local-Token':TOKEN})
        self.assertEqual(reply.status_code,200)
        state=reply.json['state']
        self.assertEqual(set(state['realFireSensorIds']),{self.one,self.two})
        self.assertFalse(state['flameSensors'][self.one]['connected'])
        self.assertIsNone(state['rawFlame'][self.one])
        self.assertIn(self.nodes[self.one],state['blockedNodes'])

if __name__ == '__main__': unittest.main()
