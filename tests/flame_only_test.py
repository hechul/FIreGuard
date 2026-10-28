"""MQ-2 retirement must preserve flame detection and the remaining demo controls."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as server
from state_manager import SimulationState


class FlameOnlyTest(unittest.TestCase):
    def setUp(self):
        self.previous = server.state
        server.state = SimulationState(server.floorplan)
        self.client = server.app.test_client()

    def tearDown(self):
        server.state = self.previous

    def test_only_installed_flame_sensors_are_reported(self):
        sensors = server.floorplan['sensors']
        self.assertEqual(len(sensors), 11)
        self.assertTrue(all(s['type'] == 'flame' for s in sensors))
        snapshot = self.client.get('/api/state').json
        self.assertNotIn('mq2Sensors', snapshot)
        self.assertNotIn('mq2Total', snapshot['sensorCounts'])
        self.assertFalse(any(e['id'].startswith('MQ2') for e in snapshot['equipment']))

    def test_retired_inputs_cannot_mutate_either_mode(self):
        for path in ('/api/hardware/mq2', '/api/simulation/mq2'):
            self.assertEqual(self.client.post(path, json={'sensorId': 'MQ2-05', 'value': 900}).status_code, 404)
        before = server.state.snapshot()
        response = self.client.post('/api/hardware/batch', json={
            'flame': {'FLM-15': True}, 'mq2': {'MQ2-05': 900},
        })
        self.assertEqual(response.status_code, 400)
        after = server.state.snapshot()
        for field in ('operationMode', 'realFireDetected', 'flameSensors', 'events', 'route'):
            self.assertEqual(before[field], after[field])

    def test_flame_batch_still_updates_real_bank(self):
        response = self.client.post('/api/hardware/batch', json={'flame': {'FLM-15': True}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['state']['operationMode'], 'simulation')
        self.assertTrue(response.json['state']['realFireDetected'])
        response = self.client.post('/api/mode', json={'mode': 'real'})
        self.assertTrue(response.json['state']['flameSensors']['FLM-15']['active'])
        self.assertIn('N10', response.json['state']['blockedNodes'])

    def test_remaining_scenarios_execute(self):
        scenarios = ('normal', 'east_exit_fire', 'ticket_fire', 'cinema4_fire', 'large_fire',
                     'east_shutter', 'mid_route_block', 'crowd_congestion', 'fallback_toilet',
                     'fallback_descender', 'no_route', 'server_off', 'fire_server_off',
                     'server_on', 'pi_off', 'pi_on', 'sensor_fault', 'sensor_recover')
        for name in scenarios:
            with self.subTest(scenario=name):
                response = self.client.post('/api/simulation/scenario', json={'scenarioId': name})
                self.assertEqual(response.status_code, 200, response.json)
                if name == 'cinema4_fire':
                    self.assertTrue(response.json['state']['flameSensors']['FLM-03']['active'])
        for name in ('smoke_warning', 'smoke_danger'):
            self.assertEqual(self.client.post('/api/simulation/scenario', json={'scenarioId': name}).status_code, 400)

    def test_rendered_pages_only_remove_retired_controls(self):
        html = self.client.get('/').get_data(as_text=True)
        self.assertNotIn('mq2', html.lower())
        self.assertNotIn('MQ-2', html)
        for control in ('realModeBtn', 'simModeBtn', 'editorAddNodeBtn', 'editorDeleteItemBtn', 'flameOnBtn'):
            self.assertIn(control, html)
        self.assertNotIn('MQ-2', self.client.get('/3d').get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
