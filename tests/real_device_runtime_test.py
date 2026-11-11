import json
import os
import signal
import tempfile
import threading
import time
import unittest
from copy import deepcopy
from pathlib import Path
from hardware.real_pi_service import RealPiState
from hardware.real_device_runtime import assess_snapshot, reconcile_cloud_latches, PublisherPump, _terminate_as_interrupt

FLOOR = json.loads((Path(__file__).resolve().parents[1] / 'static/data/floorplan.json').read_text())

class RealRuntimePreflightTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.clock = 100.0
        self.state = RealPiState(FLOOR, Path(self.tmp.name)/'latches.json', clock=lambda:self.clock)
        self.ids = list(self.state.sensor_nodes)
        self.layout = {'verified':False, 'mapping_status':'needs_verification'}

    def test_multiple_latches_are_blocked_and_no_led_is_claimed(self):
        self.state.update({sid:False for sid in self.ids})
        self.state.update({self.ids[0]:True, self.ids[1]:True})
        self.state.update({self.ids[0]:False, self.ids[1]:False})
        data=assess_snapshot(self.state.snapshot(), FLOOR, self.layout)
        self.assertEqual(set(data['latchedSensorIds']),set(self.ids[:2]))
        self.assertEqual(set(data['blockedNodes']),{self.state.sensor_nodes[sid] for sid in self.ids[:2]})
        self.assertFalse(data['readyForLiveOutput']); self.assertFalse(data['sentToCloud'])
        self.assertFalse(data['ledCommandAck'])

    def test_disconnect_does_not_clear_fire_or_permit_output(self):
        self.state.update({sid:False for sid in self.ids}); self.state.update({self.ids[0]:True})
        self.clock += 16
        data=assess_snapshot(self.state.snapshot(), FLOOR, self.layout)
        self.assertIn(self.ids[0],data['latchedSensorIds'])
        self.assertIn(self.state.sensor_nodes[self.ids[0]],data['blockedNodes'])
        self.assertTrue(any('센서' in reason for reason in data['reasons']))
        self.assertFalse(data['readyForLiveOutput'])

    def test_sim_or_inconsistent_fire_never_passes(self):
        self.state.update({sid:False for sid in self.ids})
        s=self.state.snapshot(); s['operationMode']='simulation'
        with self.assertRaises(ValueError): assess_snapshot(s,FLOOR,self.layout)
        s=self.state.snapshot(); s['rawFlame'][self.ids[0]]=True
        with self.assertRaises(ValueError): assess_snapshot(s,FLOOR,self.layout)
        self.state.update({self.ids[0]:True}); s=self.state.snapshot(); s['blockedNodes']=[]
        with self.assertRaises(ValueError): assess_snapshot(s,FLOOR,self.layout)

    def test_startup_restore_preserves_union_without_claiming_raw_freshness(self):
        self.state.update({self.ids[0]:True})
        cloud = self.state.snapshot()
        cloud['cloud']={'enabled':True,'hasTelemetry':True,'deviceId':'pi-01'}
        cloud['flameSensors'][self.ids[1]]['active']=True
        cloud['realFireSensorIds']=sorted(self.ids[:2]); cloud['realFireDetected']=True
        restored = reconcile_cloud_latches(self.state.snapshot(),cloud,device_id='pi-01',
                                          restore=lambda ids:{'ok':True,'state':self.state.restore(ids)})
        self.assertEqual(set(restored['realFireSensorIds']),set(self.ids[:2]))
        self.assertFalse(restored['flameSensors'][self.ids[1]]['connected'])
        self.assertIsNone(restored['rawFlame'][self.ids[1]])
        restarted=RealPiState(FLOOR,Path(self.tmp.name)/'latches.json',clock=lambda:self.clock)
        self.assertEqual(set(restarted.snapshot()['realFireSensorIds']),set(self.ids[:2]))

    def test_startup_missing_unknown_and_wrong_device_fail_closed(self):
        self.state.update({sid:False for sid in self.ids})
        cloud=self.state.snapshot(); cloud['cloud']={'enabled':True,'hasTelemetry':True,'deviceId':'pi-01'}
        called=[]
        for mutate in (lambda c:c['cloud'].update(hasTelemetry=False),
                       lambda c:c['cloud'].update(deviceId='other'),
                       lambda c:c['flameSensors'].pop(self.ids[0]),
                       lambda c:c.update(realFireSensorIds=[self.ids[0]])):
            value=deepcopy(cloud); mutate(value)
            with self.assertRaises(RuntimeError):
                reconcile_cloud_latches(self.state.snapshot(),value,device_id='pi-01',restore=lambda ids:called.append(ids))
        self.assertEqual(called,[])

class RealRuntimeOutputTest(unittest.TestCase):
    def setUp(self):
        from hardware.real_device_runtime import RealLedController
        self.Controller = RealLedController
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.clock = 100.0
        self.state = RealPiState(FLOOR, Path(self.tmp.name)/'latches.json', clock=lambda:self.clock)
        self.ids = list(self.state.sensor_nodes)
        self.state.update({sid:False for sid in self.ids})
        self.layout = {'verified':True, 'mapping_status':'confirmed'}
        self.instances=[]
        owner=self
        class Uno:
            def __init__(self,port,check): self.check=check; self.calls=[]; owner.instances.append(self)
            def stop(self): self.calls.append('stop')
            def flow(self,path,red): self.check(); self.calls.append(('flow',path,red))
            def command(self,cmd): self.check(); self.calls.append(cmd)
            def close(self): self.calls.append('close')
        self.Uno=Uno
        self.controller = self.Controller(self.state.snapshot,FLOOR,self.layout,enabled=True,port='/dev/test',
            uno_factory=Uno,planner=lambda s,f,l:([0,20],[21]),translate=lambda i:i if i<20 else i+1,
            clock=lambda:self.clock)

    def test_two_latched_fires_only_ack_actual_flow_and_recalculate_clear(self):
        self.state.update({self.ids[0]:True,self.ids[1]:True})
        output=self.controller.step(self.state.snapshot())
        self.assertEqual(output['led_status'],'active'); self.assertTrue(output['command_ack'])
        self.assertEqual(output['commanded_path'],[0,21]); self.assertEqual(output['commanded_fire'],[22])
        self.state.update({self.ids[0]:False,self.ids[1]:False})
        self.assertEqual(set(self.state.snapshot()['realFireSensorIds']),set(self.ids[:2]))
        self.state.clear([self.ids[0]])
        output=self.controller.step(self.state.snapshot())
        self.assertEqual(output['led_status'],'active')
        self.assertEqual(sum(isinstance(c,tuple) and c[0]=='flow' for c in self.instances[0].calls),2)
        self.assertEqual(self.state.snapshot()['realFireSensorIds'],[self.ids[1]])

    def test_stale_sensor_forces_stop_and_reconnect_can_recompute(self):
        self.state.update({self.ids[0]:True})
        self.assertEqual(self.controller.step(self.state.snapshot())['led_status'],'active')
        self.clock += 16
        stale=self.state.snapshot()
        result=self.controller.step(stale)
        self.assertEqual(result['led_status'],'error'); self.assertIn('stop',self.instances[0].calls)
        self.assertTrue(stale['realFireDetected']); self.assertIn(self.state.sensor_nodes[self.ids[0]],stale['blockedNodes'])
        self.state.update({sid:False for sid in self.ids})
        self.assertEqual(self.controller.step(self.state.snapshot())['led_status'],'active')
        self.assertIn(self.ids[0],self.state.snapshot()['realFireSensorIds'])

    def test_flow_failure_and_stop_failure_never_claim_active(self):
        class Broken(self.Uno):
            def flow(self,path,red): raise TimeoutError('no ACK')
            def stop(self): raise TimeoutError('stop failed')
        self.controller.uno_factory=Broken
        self.state.update({self.ids[0]:True})
        result=self.controller.step(self.state.snapshot())
        self.assertEqual(result['led_status'],'error'); self.assertFalse(result['command_ack'])
        self.assertEqual(result['commanded_path'],[])

    def test_unverified_mapping_never_opens_serial(self):
        with self.assertRaises(ValueError):
            self.Controller(self.state.snapshot,FLOOR,{'verified':False,'mapping_status':'needs_verification'},
                enabled=True,port='/dev/test',uno_factory=self.Uno)
        self.assertEqual(self.instances,[])

    def test_service_termination_runs_led_cleanup(self):
        self.state.update({self.ids[0]:True})
        self.assertEqual(self.controller.step(self.state.snapshot())['led_status'], 'active')
        previous = signal.signal(signal.SIGTERM, _terminate_as_interrupt)
        try:
            try:
                os.kill(os.getpid(), signal.SIGTERM)
            except KeyboardInterrupt:
                pass
            finally:
                self.controller.close()
        finally:
            signal.signal(signal.SIGTERM, previous)
        self.assertEqual(self.instances[0].calls[-2:], ['stop', 'close'])

    def test_publisher_stops_heartbeats_after_local_snapshot_loss(self):
        class Reporter:
            def __init__(self): self.calls=[]; self.called=threading.Event()
            def maybe_report(self,*args,**kwargs): self.calls.append((args,kwargs)); self.called.set()
        reporter=Reporter(); pump=PublisherPump(reporter,FLOOR,self.layout)
        pump.start()
        try:
            self.state.update({self.ids[0]:True})
            pump.update(self.state.snapshot(), {'led_status':'not_running','command_ack':False})
            self.assertTrue(reporter.called.wait(2))
            pump.invalidate(); count=len(reporter.calls)
            time.sleep(0.7)
            self.assertEqual(len(reporter.calls),count)
            self.assertEqual(reporter.calls[0][1]['led_status'],'not_running')
            self.assertFalse(reporter.calls[0][1]['command_ack'])
        finally:
            pump.close()

if __name__ == '__main__': unittest.main()
