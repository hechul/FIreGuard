import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as server
from state_manager import SimulationState


class FlameConfirmationTest(unittest.TestCase):
    def setUp(self):
        self.previous = server.state
        server.state = SimulationState(server.floorplan)
        self.client = server.app.test_client()
        self.clock = patch('state_manager.monotonic', return_value=0.0)
        self.time = self.clock.start()
        self.ids = list(server.state.flame_sensors)

    def tearDown(self):
        self.clock.stop()
        server.state = self.previous

    def sample(self, at, active=True, sensor=None, batch=False):
        self.time.return_value = at
        sensor = sensor or self.ids[0]
        path = '/api/hardware/batch' if batch else '/api/hardware/flame'
        data = {'flame': {sensor: active}} if batch else {'sensorId': sensor, 'active': active}
        result = self.client.post(path, json=data)
        self.assertEqual(result.status_code, 200)
        return result.json['state']

    def test_boundary_and_real_route_for_both_endpoints(self):
        for batch in (False, True):
            with self.subTest(batch=batch):
                server.state = SimulationState(server.floorplan)
                self.client.post('/api/mode', json={'mode': 'real'})
                for at in (0, .2, .4, .6, .8, .999):
                    s = self.sample(at, batch=batch)
                    self.assertFalse(s['realFireDetected'])
                    self.assertFalse(s['flameSensors'][self.ids[0]]['active'])
                s = self.sample(1.0, batch=batch)
                self.assertTrue(s['realFireDetected'])
                node = next(x['node'] for x in server.floorplan['sensors'] if x['id'] == self.ids[0])
                self.assertIn(node, s['blockedNodes'])
                events = s['events']
                self.assertEqual(self.sample(1.2, batch=batch)['events'], events)
                self.assertTrue(self.sample(1.3, False, batch=batch)['realFireDetected'])

    def test_short_pulse_and_false_restart(self):
        self.sample(0)
        self.sample(.4)
        self.sample(.8, False)
        for at in (.9, 1.3, 1.7, 1.899):
            self.assertFalse(self.sample(at)['realFireDetected'])
        self.assertTrue(self.sample(1.91)['realFireDetected'])

    def test_silent_gap_cannot_confirm_fire(self):
        self.sample(0)
        self.time.return_value = 5
        self.client.post('/api/hardware/heartbeat', json={})
        self.assertFalse(server.state.snapshot()['realFireDetected'])
        self.assertFalse(self.sample(5)['realFireDetected'])
        self.assertFalse(self.sample(5.4)['realFireDetected'])
        self.assertFalse(self.sample(5.8)['realFireDetected'])
        self.assertTrue(self.sample(6)['realFireDetected'])

    def test_each_sensor_has_its_own_timer(self):
        self.sample(0)
        self.sample(.4)
        self.sample(.6, sensor=self.ids[1])
        self.sample(.8)
        s = self.sample(1.0, sensor=self.ids[1])
        self.assertFalse(s['realFireDetected'])
        s = self.sample(1.0)
        self.assertEqual(s['realFireSensorIds'], [self.ids[0]])

    def test_mode_switch_and_sim_reset_preserve_real_timer(self):
        self.sample(0)
        self.sample(.4)
        self.client.post('/api/mode', json={'mode': 'real'})
        self.sample(.8)
        self.client.post('/api/mode', json={'mode': 'simulation'})
        self.client.post('/api/simulation/reset', json={})
        s = self.sample(1)
        self.assertTrue(s['realFireDetected'])
        self.assertEqual(s['operationMode'], 'simulation')
        self.assertFalse(s['flameSensors'][self.ids[0]]['active'])

    def test_simulation_is_immediate(self):
        s = self.client.post('/api/simulation/flame', json={'sensorId': self.ids[0], 'active': True}).json['state']
        self.assertTrue(s['flameSensors'][self.ids[0]]['active'])
        self.assertFalse(s['realFireDetected'])

    def test_disconnect_discards_pending_timer(self):
        self.client.post('/api/mode', json={'mode': 'real'})
        self.sample(0)
        self.sample(.4)
        server.state.set_sensor_connection(self.ids[0], False)
        server.state.set_sensor_connection(self.ids[0], True)
        self.assertFalse(self.sample(.8)['realFireDetected'])
        self.assertFalse(self.sample(1.2)['realFireDetected'])

    def test_confirmed_fire_is_not_cleared_by_a_gap(self):
        for at in (0, .4, .8, 1):
            self.sample(at)
        self.assertTrue(self.sample(5)['realFireDetected'])
        self.assertTrue(self.sample(5.1, False)['realFireDetected'])

    def test_one_second_sender_interval_is_supported(self):
        self.assertFalse(self.sample(0)['realFireDetected'])
        self.assertTrue(self.sample(1)['realFireDetected'])

    def test_pending_expired_sample_starts_over(self):
        self.sample(0)
        self.assertFalse(self.sample(1.51)['realFireDetected'])
        self.assertTrue(self.sample(2.52)['realFireDetected'])

    def test_manual_clear_then_full_second_required_again(self):
        self.sample(0)
        self.sample(1)
        cleared = self.client.post('/api/real/fire/clear', json={'sensorIds': [self.ids[0]]})
        self.assertEqual(cleared.status_code, 200)
        self.assertFalse(cleared.json['state']['realFireDetected'])
        self.assertFalse(self.sample(1.2)['realFireDetected'])
        self.assertFalse(self.sample(2.199)['realFireDetected'])
        self.assertTrue(self.sample(2.21)['realFireDetected'])

    def test_disconnect_keeps_fire_and_blocked_node_until_manual_clear(self):
        self.client.post('/api/mode', json={'mode': 'real'})
        self.sample(0)
        s = self.sample(1)
        blocked = s['blockedNodes']
        server.state.set_sensor_connection(self.ids[0], False, source='REAL')
        server.state.set_connection('pi', False, source='REAL')
        s = server.state.snapshot()
        self.assertTrue(s['realFireDetected'])
        self.assertEqual(s['blockedNodes'], blocked)
        self.assertEqual(s['overallStatus'], 'fire')
        with self.assertRaises(ValueError):
            server.state.reset()
        s = self.client.post('/api/real/fire/clear', json={'sensorIds': [self.ids[0]]}).json['state']
        self.assertFalse(s['realFireDetected'])
        self.assertEqual(s['blockedNodes'], [])

    def test_manual_clear_in_simulation_does_not_clear_simulated_fire(self):
        self.sample(0)
        self.sample(1)
        self.client.post('/api/simulation/flame', json={'sensorId': self.ids[0], 'active': True})
        s = self.client.post('/api/real/fire/clear', json={'sensorIds': [self.ids[0]]}).json['state']
        self.assertEqual(s['operationMode'], 'simulation')
        self.assertFalse(s['realFireDetected'])
        self.assertTrue(s['flameSensors'][self.ids[0]]['active'])

    def test_invalid_clear_does_not_clear_alarm(self):
        self.sample(0)
        self.sample(1)
        for ids in (None, [], ['missing'], [self.ids[0], 'missing']):
            self.assertEqual(self.client.post('/api/real/fire/clear', json={'sensorIds': ids}).status_code, 400)
            self.assertTrue(server.state.snapshot()['realFireDetected'])

    def test_clear_only_affects_sensor_ids_user_confirmed(self):
        for sid in self.ids[:2]:
            self.sample(0, sensor=sid)
            self.sample(1, sensor=sid)
        s = self.client.post('/api/real/fire/clear', json={'sensorIds': [self.ids[0]]}).json['state']
        self.assertEqual(s['realFireSensorIds'], [self.ids[1]])

    def test_alarm_persists_across_server_restart_and_manual_clear(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'real_fire.json'
            server.state = SimulationState(server.floorplan, real_fire_path=path)
            self.sample(0)
            self.sample(1)
            server.state = SimulationState(server.floorplan, real_fire_path=path)
            self.assertTrue(server.state.snapshot()['realFireDetected'])
            self.assertTrue(self.sample(10, False)['realFireDetected'])
            self.client.post('/api/real/fire/clear', json={'sensorIds': [self.ids[0]]})
            server.state = SimulationState(server.floorplan, real_fire_path=path)
            self.assertFalse(server.state.snapshot()['realFireDetected'])

    def test_failed_manual_clear_save_keeps_alarm(self):
        self.sample(0)
        self.sample(1)
        with patch.object(server.state, '_persist_real_fire', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                with server.state.hardware_input():
                    server.state.clear_real_fire([self.ids[0]])
        self.assertTrue(server.state.snapshot()['realFireDetected'])


if __name__ == '__main__':
    unittest.main()
