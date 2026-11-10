"""Synthetic multi-fire integration; no real DB, network, GPIO, or Arduino.

Only exercises API/auth, queue/worker, Pi-local latching, and cloud projection.
Telemetry publication here is deliberately an explicit fake, not the unfinished
production Pi reporter. No LED acknowledgement or optical output is asserted.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from unittest.mock import patch
from uuid import uuid4
import json
import os
import tempfile
import unittest

from flask import Flask
from cloud_api import install_cloud
from cloud_model import MAPPING_VERSION, cloud_floorplan
from hardware.real_clear_worker import Ledger, Worker
from hardware.real_pi_service import RealPiState, create_app

FLOOR = cloud_floorplan(json.loads((Path(__file__).resolve().parents[1] / 'static/data/floorplan.json').read_text()))
DEVICE = 'unit-device-token-at-least-32-characters'
SIM = 'unit-simulation-token-at-least-32-characters'
ADMIN = 'unit-real-operator-token-at-least-32-characters'
LOCAL = 'unit-pi-local-token-at-least-32-characters'


class MemoryTelemetry:
    def __init__(self): self.row = None
    def ingest(self, data):
        self.row = {'device_id':data['deviceId'], 'boot_id':data['bootId'],
                    'sequence':data['sequence'], 'observed_at':data['observedAt'],
                    'received_at':datetime.now(timezone.utc).isoformat(),
                    'mapping_version':data['mappingVersion'], 'telemetry':deepcopy(data)}
        return {'accepted':True}
    def latest(self, device): return deepcopy(self.row)
    def events(self, device): return []


class MemoryClearQueue:
    def __init__(self): self.items = []
    def create(self, device, command_id, sensor_ids):
        assert not any(x['status'] in ('pending','claimed') for x in self.items)
        item = {'id':command_id,'device':device,'sensorIds':sensor_ids[:], 'status':'pending',
                'expiresAt':(datetime.now(timezone.utc)+timedelta(seconds=60)).isoformat(),
                'claimToken':None, 'result':None}
        self.items.append(item)
        return {'id':command_id,'status':'pending','expiresAt':item['expiresAt']}
    def claim(self, device):
        item = next((x for x in self.items if x['device']==device and x['status']=='pending'),None)
        if item is None: return None
        item['status']='claimed'; item['claimToken']=str(uuid4())
        return {k:deepcopy(item[k]) for k in ('id','sensorIds','claimToken','expiresAt')}
    def complete(self, device, command_id, token, result):
        item = next(x for x in self.items if x['id']==command_id and x['device']==device)
        assert item['status']=='claimed' and item['claimToken']==token
        item['result']=deepcopy(result); item['status']=result['status']
        return {'id':command_id, 'status':item['status']}
    def latest(self, device):
        item=next((x for x in reversed(self.items) if x['device']==device),None)
        return None if item is None else {k:deepcopy(item[k]) for k in ('id','sensorIds','status','result','expiresAt')}


class RealEndToEndTest(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ, {'FIREGUARD_CLOUD':'1','FIREGUARD_DEVICE_ID':'pi-01',
            'FIREGUARD_DEVICE_TOKEN':DEVICE,'FIREGUARD_SIM_OPERATOR_TOKEN':SIM,
            'FIREGUARD_REAL_OPERATOR_TOKEN':ADMIN,'FIREGUARD_REAL_CONTROL_ENABLED':'1'},clear=False)
        self.env.start(); self.addCleanup(self.env.stop)
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.temp=Path(tmp.name); self.now=100.0
        self.pi=RealPiState(FLOOR,self.temp/'fire.json',clock=lambda:self.now)
        self.pi_client=create_app(self.pi,LOCAL).test_client()
        app=Flask(__name__); install_cloud(app,FLOOR)
        self.telemetry=MemoryTelemetry(); self.queue=MemoryClearQueue()
        app.extensions['cloud_store']=self.telemetry; app.extensions['real_clear_store']=self.queue
        self.cloud=app.test_client()
        self.worker=Worker('https://cloud.test','http://127.0.0.1:5001', DEVICE, LOCAL,
                           Ledger(self.temp/'clear-ledger.json'),http=self.http)
        self.ids=[s['id'] for s in FLOOR['sensors'] if s['type']=='flame']
        self.nodes={s['id']:s['node'] for s in FLOOR['sensors'] if s['type']=='flame'}
        self.boot=str(uuid4()); self.seq=0
    def http(self,url,*,headers,payload=None,timeout=3):
        parsed=urlsplit(url)
        client=self.cloud if parsed.hostname=='cloud.test' else self.pi_client
        response=(client.get(parsed.path,headers=headers) if payload is None else
                  client.post(parsed.path,headers=headers,json=payload))
        if response.status_code >= 400:
            raise HTTPError(url,response.status_code,'fake transport error',None,None)
        return response.get_json()
    def post_sensor(self, readings):
        return self.pi_client.post('/api/hardware/batch',json={'flame':readings})
    def cloud_state(self):
        response=self.cloud.get('/api/state'); self.assertEqual(response.status_code,200,response.json)
        return response.json
    def publish_synthetic_real_snapshot(self):
        # This explicit fake is NOT the unfinished REAL Pi network publisher.
        snap=self.pi.snapshot(); self.seq+=1
        payload={'deviceId':'pi-01','bootId':self.boot,'sequence':self.seq,
                 'observedAt':datetime.now(timezone.utc).isoformat(), 'mappingVersion':MAPPING_VERSION,
                 'startNode':snap['startNode'],
                 'flame':{k:v['active'] for k,v in snap['flameSensors'].items()},
                 'led':{'status':'unknown'}}
        result=self.cloud.post('/api/hardware/telemetry',json=payload,
                               headers={'Authorization':'Bearer '+DEVICE})
        self.assertEqual(result.status_code,200,result.json)
    def request_clear(self, ids, token=ADMIN):
        return self.cloud.post('/api/real-control/clear',json={'sensorIds':ids},
                               headers={'Authorization':'Bearer '+token})

    def test_two_latches_reject_active_clear_then_selectively_clear_after_ack(self):
        one,two='FLM-01','FLM-07'
        self.assertEqual(self.post_sensor({sid:False for sid in self.ids}).status_code,200)
        self.assertEqual(self.post_sensor({one:True,two:True}).status_code,200)
        self.assertEqual(self.post_sensor({one:False}).status_code,200)
        self.publish_synthetic_real_snapshot()
        visible=self.cloud_state()
        self.assertEqual(set(visible['realFireSensorIds']),{one,two})
        self.assertEqual(set(visible['blockedNodes']),{self.nodes[one],self.nodes[two]})
        self.assertTrue(all(n not in visible['blockedNodes'] for n in (visible['route'] or {}).get('nodes',[])))
        self.assertEqual(visible['cloud']['led']['status'],'unknown')
        self.assertEqual(self.cloud.post('/api/cloud/simulation',json={'history':[]}).status_code,409,
                         'connected REAL fire must take precedence over simulation')
        self.assertEqual(self.request_clear([one],SIM).status_code,401)
        before=deepcopy(self.telemetry.row)
        self.assertEqual(self.request_clear([one,two]).status_code,200)
        self.assertEqual(self.telemetry.row,before,'queueing must not clear cloud telemetry')
        rejected=self.worker.poll_once()
        self.assertEqual(rejected['status'],'rejected','active second sensor must reject atomically')
        self.assertEqual(set(self.pi.snapshot()['realFireSensorIds']),{one,two})
        self.assertEqual(set(self.cloud_state()['realFireSensorIds']),{one,two})
        self.assertEqual(self.request_clear([one]).status_code,200)
        completed=self.worker.poll_once()
        self.assertEqual(completed['status'],'completed')
        self.assertEqual(completed['clearedSensorIds'],[one])
        self.assertEqual(self.pi.snapshot()['realFireSensorIds'],[two])
        self.assertEqual(set(self.cloud_state()['realFireSensorIds']),{one,two},'ACK alone must not mutate REAL telemetry')
        self.publish_synthetic_real_snapshot()
        visible=self.cloud_state()
        self.assertEqual(visible['realFireSensorIds'],[two])
        self.assertEqual(visible['blockedNodes'],[self.nodes[two]])
        self.assertEqual(visible['cloud']['led']['status'],'unknown')
        restored=RealPiState(FLOOR,self.temp/'fire.json',clock=lambda:self.now)
        self.assertEqual(restored.snapshot()['realFireSensorIds'],[two])
        self.assertFalse(restored.snapshot()['flameSensors'][two]['connected'])

    def test_stale_raw_sensor_cannot_clear_a_latched_alarm(self):
        sensor='FLM-10'
        self.assertEqual(self.post_sensor({sid:False for sid in self.ids}).status_code,200)
        self.assertEqual(self.post_sensor({sensor:True}).status_code,200)
        self.assertEqual(self.post_sensor({sensor:False}).status_code,200)
        self.publish_synthetic_real_snapshot()
        self.now += 16
        self.assertEqual(self.request_clear([sensor]).status_code,200)
        result=self.worker.poll_once()
        self.assertEqual(result['status'],'rejected')
        self.assertEqual(self.pi.snapshot()['realFireSensorIds'],[sensor])
        self.assertIn(sensor,self.cloud_state()['realFireSensorIds'])

if __name__=='__main__': unittest.main()
