"""REAL clear queue routes never clear telemetry and are independently protected."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import json
import os
import unittest

from flask import Flask
from cloud_api import install_cloud

FLOOR = json.loads((Path(__file__).resolve().parents[1] / 'static/data/floorplan.json').read_text())
DEVICE = 'device-token-for-tests-only-012345678901'
SIM = 'simulation-token-for-tests-only-012345678'
REAL = 'real-operator-token-for-tests-only-0123456'

class MemoryRealClear:
    def __init__(self): self.commands = []
    def create(self, device, cmd_id, sensors):
        self.commands.append((device, cmd_id, sensors))
        return {'id':cmd_id, 'status':'pending'}
    def latest(self, device): return None
    def claim(self, device): return None
    def complete(self, device, cmd_id, token, result):
        self.commands.append((device, cmd_id, token, deepcopy(result)))
        return {'id':cmd_id, 'status':result['status']}

class FakeTelemetry:
    def __init__(self): self.row={'flame':{'FLM-01':True,'FLM-07':True}}
    def latest(self, did): return self.row
    def events(self, did): return []

class RealControlApiTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            'FIREGUARD_CLOUD':'1', 'FIREGUARD_DEVICE_ID':'pi-01',
            'FIREGUARD_DEVICE_TOKEN':DEVICE, 'FIREGUARD_SIM_OPERATOR_TOKEN':SIM,
            'FIREGUARD_REAL_OPERATOR_TOKEN':REAL, 'FIREGUARD_REAL_CONTROL_ENABLED':'1',
        }, clear=False)
        self.env.start()
        self.app=Flask(__name__)
        install_cloud(self.app,FLOOR)
        self.clear=MemoryRealClear(); self.telemetry=FakeTelemetry()
        self.app.extensions['real_clear_store']=self.clear
        self.app.extensions['cloud_store']=self.telemetry
        self.client=self.app.test_client()
    def tearDown(self): self.env.stop()
    @staticmethod
    def headers(token): return {'Authorization':'Bearer '+token}
    def post(self, body, token=REAL):
        return self.client.post('/api/real-control/clear',json=body,headers=self.headers(token))
    def test_feature_is_disabled_by_default(self):
        with patch.dict(os.environ, {'FIREGUARD_REAL_CONTROL_ENABLED':'0'}):
            self.assertEqual(self.post({'sensorIds':['FLM-01']}).status_code, 503)
        self.assertEqual(self.clear.commands,[])
    def test_sim_and_device_keys_cannot_issue_real_clear(self):
        for token in (SIM, DEVICE, 'wrong'):
            self.assertEqual(self.post({'sensorIds':['FLM-01']},token).status_code,401)
        self.assertEqual(self.clear.commands,[])
    def test_distinct_keys_required_even_if_supplied_correctly(self):
        for other in (SIM, DEVICE):
            with patch.dict(os.environ, {'FIREGUARD_REAL_OPERATOR_TOKEN':other}):
                self.assertEqual(self.post({'sensorIds':['FLM-01']},other).status_code,503)
    def test_invalid_sensors_and_body_fail_before_queue(self):
        for value in ([], ['FLM-01','FLM-01'], ['FLM-12'], ['FLM-01',{}], 'FLM-01'):
            self.assertEqual(self.post({'sensorIds':value}).status_code,400)
        self.assertEqual(self.post({'sensorIds':['FLM-01'],'unexpected':True}).status_code,400)
        self.assertEqual(self.clear.commands,[])
    def test_create_only_queues_and_does_not_clear_state(self):
        before=deepcopy(self.telemetry.row)
        r=self.post({'sensorIds':['FLM-07','FLM-01']})
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.json['command']['status'],'pending')
        self.assertEqual(self.clear.commands[0][0],'pi-01')
        self.assertEqual(self.clear.commands[0][2],['FLM-01','FLM-07'])
        self.assertEqual(self.telemetry.row,before)
    def test_claim_and_result_only_for_device(self):
        claim='/api/hardware/real-clear-command'; result='/api/hardware/real-clear-result'
        self.assertEqual(self.client.get(claim,headers=self.headers(REAL)).status_code,401)
        self.assertEqual(self.client.get(claim,headers=self.headers(DEVICE)).status_code,200)
        body={'id':'id','claimToken':'claim','result':{'status':'completed'}}
        self.assertEqual(self.client.post(result,json=body,headers=self.headers(REAL)).status_code,401)
        self.assertEqual(self.client.post(result,json=body,headers=self.headers(DEVICE)).status_code,200)
        self.assertTrue(self.telemetry.row['flame']['FLM-01'])
    def test_latest_only_operator_and_no_other_methods(self):
        path='/api/real-control/latest'
        self.assertEqual(self.client.get(path,headers=self.headers(DEVICE)).status_code,401)
        self.assertEqual(self.client.get(path,headers=self.headers(REAL)).status_code,200)
        self.assertEqual(self.client.post(path,headers=self.headers(REAL)).status_code,405)

if __name__=='__main__': unittest.main()
