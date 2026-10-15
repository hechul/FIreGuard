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
        self.client = server.app.test_client()
        self.flame = next(s['id'] for s in server.floorplan['sensors'] if s['type'] == 'flame')
        self.mq = next(s['id'] for s in server.floorplan['sensors'] if s['type'] == 'mq2')

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
        self.assertFalse(s['realFireDetected'])

    def test_simulated_fire_never_activates_real_alert(self):
        self.post('simulation/flame', {'sensorId':self.flame,'active':True})
        s = self.post('hardware/batch', {'flame':{self.flame:False},'mq2':{self.mq:450}})
        self.assertTrue(s['flameSensors'][self.flame]['active'])
        self.assertFalse(s['realFireDetected'])
        self.post('mode', {'mode':'real'})
        s = self.post('mode', {'mode':'simulation'})
        self.assertTrue(s['flameSensors'][self.flame]['active'])
        s = self.post('hardware/mq2', {'sensorId':self.mq,'value':650})
        self.assertTrue(s['realFireDetected'])
        self.assertEqual(s['mq2Sensors'][self.mq]['value'], 0)
        s = self.post('hardware/mq2', {'sensorId':self.mq,'value':0})
        self.assertFalse(s['realFireDetected'])

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
