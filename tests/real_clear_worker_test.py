import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from uuid import uuid4

from hardware.real_clear_worker import Ledger, Worker, parse_command, validate_origin

DEVICE='device-token-xxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
LOCAL='local-token-yyyyyyyyyyyyyyyyyyyyyyyyyyyyyy'
NOW=datetime(2026,11,10,tzinfo=timezone.utc)

def command(delta=60):
    return {'id':str(uuid4()), 'claimToken':str(uuid4()), 'sensorIds':['FLM-07','FLM-01'],
            'expiresAt':(NOW+timedelta(seconds=delta)).isoformat()}

class FakeHTTP:
    def __init__(self, cmd): self.cmd=cmd; self.calls=[]; self.fail_local=None; self.fail_report=False
    def __call__(self,url,*,headers,payload=None,timeout=3):
        self.calls.append((url,headers,payload))
        if url.endswith('/real-clear-command'):
            cmd=self.cmd; self.cmd=None
            return {'ok':True,'command':cmd}
        if url.endswith('/api/real/clear'):
            if self.fail_local: raise self.fail_local
            return {'ok':True,'state':{'realFireSensorIds':['FLM-09']}}
        if url.endswith('/real-clear-result'):
            if self.fail_report: raise TimeoutError('not logged')
            return {'ok':True,'command':{'status':payload['result']['status']}}
        raise AssertionError(url)

class ClearWorkerTest(unittest.TestCase):
    def setUp(self):
        self.dir=tempfile.TemporaryDirectory(); self.path=Path(self.dir.name)/'ledger.json'
        self.cmd=command(); self.http=FakeHTTP(self.cmd)
        self.ledger=Ledger(self.path)
        self.worker=Worker('https://example.com','http://127.0.0.1:5001',DEVICE,LOCAL,self.ledger,http=self.http,clock=lambda:NOW)
    def tearDown(self): self.dir.cleanup()
    def test_success_is_journaled_then_reported_and_never_replayed(self):
        result=self.worker.poll_once()
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['clearedSensorIds'],['FLM-01','FLM-07'])
        self.assertEqual(self.ledger.entries[self.cmd['id']]['phase'],'reported')
        self.assertEqual(os.stat(self.path).st_mode & 0o777,0o600)
        restored=Ledger(self.path)
        self.assertEqual(restored.entries[self.cmd['id']]['result'],result)
        self.assertIsNone(self.worker.poll_once())
        self.assertEqual(sum(u.endswith('/api/real/clear') for u,_,_ in self.http.calls),1)
    def test_local_409_is_rejected_all_or_nothing(self):
        self.http.fail_local=HTTPError('http://127.0.0.1/',409,'blocked',None,None)
        result=self.worker.poll_once()
        self.assertEqual(result['status'],'rejected')
        self.assertEqual(result['rejectedSensorIds'],['FLM-01','FLM-07'])
        self.assertEqual(result['clearedSensorIds'],[])
    def test_expiry_and_validation_prevent_local_effect(self):
        self.http.cmd=command(-1)
        self.assertEqual(self.worker.poll_once()['status'],'rejected')
        self.assertFalse(any(u.endswith('/api/real/clear') for u,_,_ in self.http.calls))
        for bad in ({},dict(command(),sensorIds=['FLM-01','FLM-01']),dict(command(),sensorIds=['FLM-12'])):
            with self.assertRaises(ValueError): parse_command(bad,now=NOW)
    def test_crash_after_start_reports_unknown_without_reapplying(self):
        parsed=parse_command(self.cmd,now=NOW); self.ledger.begin(parsed)
        loaded=Ledger(self.path); self.http.cmd=None
        worker=Worker('https://example.com','http://localhost:5001',DEVICE,LOCAL,loaded,http=self.http,clock=lambda:NOW)
        worker.poll_once()
        result=loaded.entries[self.cmd['id']]['result']
        self.assertEqual(result['status'],'failed')
        self.assertFalse(any(u.endswith('/api/real/clear') for u,_,_ in self.http.calls))
        self.assertEqual(loaded.entries[self.cmd['id']]['phase'],'reported')
    def test_report_timeout_retries_exact_result_not_local_clear(self):
        self.http.fail_report=True
        with self.assertRaises(TimeoutError): self.worker.poll_once()
        expected=self.ledger.entries[self.cmd['id']]['result']
        self.assertEqual(self.ledger.entries[self.cmd['id']]['phase'],'finished')
        self.http.fail_report=False
        Worker('https://example.com','http://localhost:5001',DEVICE,LOCAL,Ledger(self.path),http=self.http,clock=lambda:NOW).poll_once()
        reports=[p['result'] for u,_,p in self.http.calls if u.endswith('/real-clear-result')]
        self.assertEqual(reports,[expected,expected])
        self.assertEqual(sum(u.endswith('/api/real/clear') for u,_,_ in self.http.calls),1)
    def test_persistence_failure_prevents_clear(self):
        with patch.object(self.ledger,'persist',side_effect=OSError('disk')):
            with self.assertRaises(OSError): self.worker.poll_once()
        self.assertFalse(any(u.endswith('/api/real/clear') for u,_,_ in self.http.calls))
    def test_insecure_origins_and_same_tokens_rejected(self):
        for url in ('http://example.com','https://user:password@example.com','https://example.com/path'):
            with self.assertRaises(ValueError): validate_origin(url)
        for url in ('http://192.168.1.5:5001','https://localhost:5001','http://localhost:5001/x'):
            with self.assertRaises(ValueError): validate_origin(url,local=True)
        with self.assertRaises(ValueError): Worker('https://example.com','http://localhost:5001',DEVICE,DEVICE,self.ledger)

    def test_worker_and_real_service_selective_multifire_integration(self):
        # No sockets, GPIO, production DB or Arduino: invoke actual Pi Flask
        # routes with the worker's transport at the in-process boundary.
        from cloud_model import cloud_floorplan
        from hardware.real_pi_service import RealPiState, create_app
        base=Path(__file__).resolve().parents[1]
        floor=cloud_floorplan(json.loads((base/'static/data/floorplan.json').read_text()))
        state=RealPiState(floor,Path(self.dir.name)/'fire.json',clock=lambda:5)
        client=create_app(state,LOCAL).test_client()
        self.assertEqual(client.post('/api/hardware/batch',json={'flame':{'FLM-01':True,'FLM-07':True}}).status_code,200)
        self.assertEqual(client.post('/api/hardware/batch',json={'flame':{'FLM-01':False}}).status_code,200)
        self.http.cmd=dict(command(),sensorIds=['FLM-01'])
        def transport(url, *, headers, payload=None, timeout=3):
            if url.endswith('/api/real/clear'):
                response=client.post('/api/real/clear',json=payload,headers=headers)
                if response.status_code >= 400:
                    raise HTTPError(url,response.status_code,'failed',None,None)
                return response.json
            return self.http(url,headers=headers,payload=payload,timeout=timeout)
        worker=Worker('https://example.com','http://localhost:5001',DEVICE,LOCAL,self.ledger,http=transport,clock=lambda:NOW)
        result=worker.poll_once()
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['clearedSensorIds'],['FLM-01'])
        self.assertEqual(state.snapshot()['realFireSensorIds'],['FLM-07'])
        self.assertIn('N7',state.snapshot()['blockedNodes'])

if __name__=='__main__': unittest.main()
