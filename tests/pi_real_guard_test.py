import unittest
from threading import RLock
from flask import Flask, jsonify, request
from hardware.pi_real_guard import install_guard, EXPECTED

class State:
    def __init__(self):
        self._lock = RLock()
        self.operation_mode = 'simulation'
        self._mode_states = {'real': {'flame_sensors': {sid:{'active':False,'connected':True} for sid in EXPECTED}}}
        self.flame_sensors = self._mode_states['real']['flame_sensors']

class GuardTest(unittest.TestCase):
    def setUp(self):
        self.time = 100.0
        self.state = State()
        self.app = Flask(__name__)
        @self.app.post('/api/hardware/batch')
        def batch():
            values = request.get_json()['flame']
            for k,v in values.items():
                if k in EXPECTED: self.state._mode_states['real']['flame_sensors'][k]['active'] = bool(v)
            return jsonify(ok=True)
        install_guard(self.app, self.state, clock=lambda:self.time)
        self.c = self.app.test_client()
    def status(self): return self.c.get('/api/hardware/guard').json
    def post(self, values): return self.c.post('/api/hardware/batch', json={'flame':values})
    def test_startup_all_sensor_freshness_and_expiry(self):
        self.assertFalse(self.status()['ready'])
        self.post({sid:False for sid in EXPECTED})
        self.assertTrue(self.status()['ready'])
        self.time += 8.1
        self.assertFalse(self.status()['ready'])
        self.post({'FLM-01': False})
        self.assertFalse(self.status()['ready'])
    def test_real_fire_and_disconnected_fail_closed(self):
        self.post({sid:False for sid in EXPECTED})
        self.post({'FLM-03':True})
        self.assertFalse(self.status()['ready'])
        self.assertTrue(self.status()['realFireDetected'])
        self.post({'FLM-03':False})
        self.state._mode_states['real']['flame_sensors']['FLM-04']['connected'] = False
        self.assertFalse(self.status()['ready'])
    def test_wrong_mode_malformed_payload_and_remote(self):
        self.post({sid:False for sid in EXPECTED})
        self.state.operation_mode = 'real'
        self.assertFalse(self.status()['ready'])
        self.state.operation_mode = 'simulation'
        self.post({'FLM-01':0})
        self.assertFalse(self.status()['ready'])
        self.assertEqual(self.c.get('/api/hardware/guard', environ_base={'REMOTE_ADDR':'192.0.2.1'}).status_code,403)
        self.post({sid:False for sid in EXPECTED})
        self.time += 8.1
        self.c.post('/api/hardware/batch',json={'flame':{sid:False for sid in EXPECTED}},environ_base={'REMOTE_ADDR':'192.0.2.1'})
        self.assertFalse(self.status()['ready'])

if __name__ == '__main__': unittest.main()
