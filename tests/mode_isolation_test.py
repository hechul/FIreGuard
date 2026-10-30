import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as server
from state_manager import SimulationState

class ModeIsolationTest(unittest.TestCase):
    def setUp(self):
        self.previous = server.state
        server.state = SimulationState(server.floorplan)
        # Timing boundaries are covered separately; these tests isolate modes.
        server.state.REAL_FLAME_CONFIRM_SECONDS = 0
        self.client = server.app.test_client()
        self.flame = next(s['id'] for s in server.floorplan['sensors'] if s['type'] == 'flame')

    def tearDown(self):
        server.state = self.previous

    def post(self, path, data=None):
        r = self.client.post('/api/' + path, json=data or {})
        self.assertEqual(r.status_code, 200, r.json)
        return r.json['state']

    def test_real_fire_does_not_overwrite_simulation(self):
        self.post('simulation/manual-edge', {'edgeId':'E02','blocked':True})
        s = self.post('hardware/flame', {'sensorId':self.flame,'active':True})
        self.assertEqual(s['operationMode'], 'simulation')
        self.assertFalse(s['flameSensors'][self.flame]['active'])
        self.assertTrue(s['realFireDetected'])
        self.assertEqual(s['manualBlockedEdges'], ['E02'])
        self.post('hardware/heartbeat')
        self.post('simulation/reset')
        self.assertTrue(server.state.snapshot()['realFireDetected'])
        s = self.post('mode', {'mode':'real'})
        self.assertTrue(s['flameSensors'][self.flame]['active'])
        self.assertEqual(s['manualBlockedEdges'], [])
        self.assertEqual(self.client.post('/api/simulation/reset', json={}).status_code, 409)
        s = self.post('mode', {'mode':'simulation'})
        self.assertFalse(s['flameSensors'][self.flame]['active'])
        s = self.post('hardware/flame', {'sensorId':self.flame,'active':False})
        self.assertTrue(s['realFireDetected'])
        s = self.post('real/fire/clear', {'sensorIds': [self.flame]})
        self.assertFalse(s['realFireDetected'])

    def test_simulated_fire_never_activates_real_alert(self):
        self.post('simulation/flame', {'sensorId':self.flame,'active':True})
        s = self.post('hardware/batch', {'flame':{self.flame:False}})
        self.assertTrue(s['flameSensors'][self.flame]['active'])
        self.assertFalse(s['realFireDetected'])
        self.post('mode', {'mode':'real'})
        s = self.post('mode', {'mode':'simulation'})
        self.assertTrue(s['flameSensors'][self.flame]['active'])
        s = self.post('hardware/flame', {'sensorId':self.flame,'active':True})
        self.assertTrue(s['realFireDetected'])
        s = self.post('hardware/flame', {'sensorId':self.flame,'active':False})
        self.assertTrue(s['realFireDetected'])
        s = self.post('real/fire/clear', {'sensorIds': [self.flame]})
        self.assertFalse(s['realFireDetected'])

    def test_sensor_demo_then_simulation_survives_continuous_hardware(self):
        self.post('mode', {'mode': 'real'})
        s = self.post('hardware/flame', {'sensorId': self.flame, 'active': True})
        self.assertTrue(s['flameSensors'][self.flame]['active'])
        self.post('hardware/flame', {'sensorId': self.flame, 'active': False})
        self.post('real/fire/clear', {'sensorIds': [self.flame]})
        self.post('mode', {'mode': 'simulation'})
        expected = self.post('simulation/scenario', {'scenarioId': 'east_shutter'})
        events = expected['events']
        for _ in range(10):
            # Normal readings and heartbeat continue after the flame is removed.
            self.post('hardware/heartbeat')
            self.post('hardware/flame', {'sensorId': self.flame, 'active': False})
            s = self.post('hardware/batch', {
                'flame': {self.flame: False},
                'shutters': {'SH-02': False},
            })
            self.assertEqual(s['operationMode'], 'simulation')
            self.assertEqual(s['route'], expected['route'])
            self.assertEqual(s['shutters'], expected['shutters'])
            self.assertEqual(s['events'], events)
            self.assertFalse(s['realFireDetected'])
        # Even another real alert must preserve the explicitly selected mode.
        s = self.post('hardware/flame', {'sensorId': self.flame, 'active': True})
        self.assertEqual(s['operationMode'], 'simulation')
        self.assertTrue(s['realFireDetected'])
        self.assertEqual(s['shutters'], expected['shutters'])
        s = self.post('mode', {'mode': 'real'})
        self.assertTrue(s['flameSensors'][self.flame]['active'])
        self.assertFalse(s['shutters']['SH-02']['closed'])

    def test_invalid_sensor_does_not_leave_real_bank_selected(self):
        self.post('simulation/flame', {'sensorId':self.flame,'active':True})
        r = self.client.post('/api/hardware/flame', json={'sensorId':'missing','active':True})
        self.assertEqual(r.status_code, 400)
        s = server.state.snapshot()
        self.assertEqual(s['operationMode'], 'simulation')
        self.assertTrue(s['flameSensors'][self.flame]['active'])
        self.assertFalse(s['realFireDetected'])

if __name__ == '__main__':
    unittest.main()
