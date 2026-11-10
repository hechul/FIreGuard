import unittest
import sys
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from hardware import cloud_sim_led as led

CMD = {'id':'test','claimToken':'test','startNode':'N4','fireNode':'N10',
       'expiresAt':(datetime.now(timezone.utc)+timedelta(seconds=30)).isoformat()}

class FakeUno:
    def __init__(self, port, check):
        self.check=check; self.started=None; self.calls=[]
        instances.append(self)
    def flow(self, path, red):
        self.check(); self.calls.append(('flow',path,red)); self.started=led.time.monotonic()
    def stop(self): self.calls.append('stop')
    def close(self): self.calls.append('close')

instances=[]
class LedBridgeTest(unittest.TestCase):
    def setUp(self): instances.clear()
    def test_fire_nodes_compatibility_and_fail_closed(self):
        self.assertEqual(led.selected_fire_nodes({'fireNode':'N10'}), ['N10'])
        self.assertEqual(led.selected_fire_nodes({'fireNode':'__MULTI__','fireNodes':['N10','N7']}), ['N10','N7'])
        for command in (
            {'fireNode':'N10','fireNodes':['N10','N7']},
            {'fireNode':'__MULTI__'},
            {'fireNode':'__MULTI__','fireNodes':['N10','N10']},
            {'fireNode':'__MULTI__','fireNodes':[]},
            {'fireNode':'__MULTI__','fireNodes':['N10', None]},
        ):
            with self.subTest(command=command), self.assertRaises(ValueError):
                led.selected_fire_nodes(command)

    def test_multiple_fires_route_and_red_use_same_full_snapshot(self):
        floor={'nodes':[{'id':'N4'}], 'sensors':[
            {'id':'FLM-07','type':'flame','node':'N7'},
            {'id':'FLM-10','type':'flame','node':'N10'},
            {'id':'FLM-02','type':'flame','node':'N2'}]}
        seen = {}
        class Graph:
            def __init__(self, loaded): self.floor=loaded
            def shortest_route(self, start, *, blocked_nodes):
                seen['blocked'] = blocked_nodes
                return SimpleNamespace(as_dict=lambda:{'nodes':['N4','EXIT_NW'],'edges':['E01']})
            def shortest_fallback_route(self,*args,**kwargs):
                raise AssertionError('normal route should be selected')
        def inspect(snapshot, *args):
            seen['active'] = {key for key, value in snapshot['flameSensors'].items() if value['active']}
            return {'nodes':snapshot['route']['nodes'],'ordered':[1,2], 'red':[4,7]}
        module=SimpleNamespace(load_files=lambda: ({},floor),
            demo_snapshot=lambda *a:{'route':None, 'flameSensors':{}},
            inspect_route=inspect, fire_led_indices=lambda *a: ([],[]))
        with patch.dict(sys.modules, {'hardware.led_routes':module, 'route_service':SimpleNamespace(FloorGraph=Graph)}):
            result=led.plan({'startNode':'N4','fireNode':'__MULTI__','fireNodes':['N7','N10']})
        self.assertEqual(seen['blocked'], {'N7','N10'})
        self.assertEqual(seen['active'], {'FLM-07','FLM-10'})
        self.assertEqual(result['red'], [4,7])
        self.assertEqual(result['nodes'], ['N4','EXIT_NW'])

    def test_multiple_fires_no_route_preserves_all_red(self):
        floor={'nodes':[{'id':'N4'}], 'sensors':[
            {'id':'FLM-07','type':'flame','node':'N7'},
            {'id':'FLM-10','type':'flame','node':'N10'}]}
        class Graph:
            def __init__(self, loaded): pass
            def shortest_route(self, start, *, blocked_nodes): return None
            def shortest_fallback_route(self, start, *, blocked_nodes): return None
        def red(snapshot, *args):
            self.assertTrue(all(value['active'] for value in snapshot['flameSensors'].values()))
            return [7,4], []
        module=SimpleNamespace(load_files=lambda: ({},floor),
            demo_snapshot=lambda *a:{'route':None, 'flameSensors':{}},
            inspect_route=lambda *a: self.fail('no route must not calculate green'), fire_led_indices=red)
        with patch.dict(sys.modules, {'hardware.led_routes':module, 'route_service':SimpleNamespace(FloorGraph=Graph)}):
            result=led.plan({'startNode':'N4','fireNode':'__MULTI__','fireNodes':['N7','N10']})
        self.assertEqual(result['routeStatus'],'no_route')
        self.assertEqual(result['path'], [])
        self.assertEqual(result['red'], [4,7])
    def test_cancel_check_posts_secret_in_body_and_fails_closed(self):
        with patch('hardware.cloud_sim_led.request', return_value={'ok':True, 'active':True}) as req:
            led.ensure_current('https://example.test', 'secret', CMD)
            self.assertEqual(req.call_args.args[0], 'https://example.test/api/hardware/sim-command/check')
            self.assertEqual(req.call_args.kwargs['data'], {'id':CMD['id'], 'claimToken':CMD['claimToken']})
        for response in ({'ok':True,'active':False}, {'ok':False,'active':True}, {}, None):
            with self.subTest(response=response), patch('hardware.cloud_sim_led.request', return_value=response):
                with self.assertRaises(led.GuardError): led.ensure_current('https://example.test','secret',CMD)
        with patch('hardware.cloud_sim_led.request', side_effect=TimeoutError):
            with self.assertRaises(led.GuardError): led.ensure_current('https://example.test','secret',CMD)

    @patch('hardware.cloud_sim_led.plan',return_value={'nodes':['N4','N2'],'edges':['E01'],'path':[1,2,3],'red':[4],'routeStatus':'ok'})
    @patch('hardware.cloud_sim_led.ensure_safe')
    def test_cancel_after_flow_stops_output(self, guard, plan):
        def cancel():
            if instances and any(isinstance(call, tuple) and call[0] == 'flow' for call in instances[0].calls):
                raise led.GuardError('취소')
        with patch('hardware.cloud_sim_led.time.monotonic', side_effect=(n / 10 for n in range(1000))):
            out=led.execute(CMD,'http://localhost:5000','/dev/ttyACM0',FakeUno,seconds=1.2,cancel_check=cancel)
        self.assertEqual(out['status'],'failed')
        self.assertEqual(instances[0].calls[-2:],['stop','close'])

    @patch('hardware.cloud_sim_led.plan',return_value={'nodes':['N4','N2'],'edges':['E01'],'path':[1,2,3],'red':[4],'routeStatus':'ok'})
    @patch('hardware.cloud_sim_led.ensure_safe')
    def test_ack_and_stop(self, guard, plan):
        out=led.execute(CMD,'http://localhost:5000','/dev/ttyACM0',FakeUno,seconds=0.01,cancel_check=lambda:None)
        self.assertEqual(out['status'],'completed'); self.assertTrue(out['ledCommandAck'])
        self.assertEqual(instances[0].calls[-2:],['stop','close'])
        self.assertIn('발광 여부 미확인',out['message'])
    @patch('hardware.cloud_sim_led.plan',return_value={'nodes':['N4','N2'],'edges':['E01'],'path':[1,2,3],'red':[4],'routeStatus':'ok'})
    def test_guard_loss_stops_and_reports_failure(self, plan):
        count=[0]
        def guard(*a):
            count[0]+=1
            if count[0]>=5: raise led.GuardError('sensor lost')
        with patch('hardware.cloud_sim_led.ensure_safe',side_effect=guard):
            out=led.execute(CMD,'http://localhost:5000','/dev/ttyACM0',FakeUno,seconds=.2,cancel_check=lambda:None)
        self.assertEqual(out['status'],'failed')
        self.assertEqual(instances[0].calls[-2:],['stop','close'])
    @patch('hardware.cloud_sim_led.plan',return_value={'nodes':['N4','N2'],'edges':['E01'],'path':[1,2,3],'red':[4],'routeStatus':'ok'})
    @patch('hardware.cloud_sim_led.ensure_safe')
    def test_stop_failure_never_reported_success(self, guard, plan):
        class BadStop(FakeUno):
            def stop(self): raise TimeoutError('STOP failed')
        out=led.execute(CMD,'http://localhost:5000','/dev/ttyACM0',BadStop,seconds=.01,cancel_check=lambda:None)
        self.assertEqual(out['status'],'failed'); self.assertIn('STOP 응답 미확인',out['message'])
        self.assertFalse(out['ledCommandAck'])
    @patch('hardware.cloud_sim_led.request',side_effect=OSError('down'))
    def test_guard_unavailable_fails_closed(self, request):
        with self.assertRaises(led.GuardError):
            led.ensure_safe('http://localhost:5000',datetime.now(timezone.utc)+timedelta(seconds=30))
        self.assertEqual(instances,[])
    def test_flow_not_written_when_guard_fails_before_receive_window(self):
        class FakeSerial:
            def __init__(self): self.writes=[]
            def write(self, value): self.writes.append(value)
            def flush(self): pass
            def readline(self): return b'GO\n'
        serial=FakeSerial()
        uno=led.GuardedUno.__new__(led.GuardedUno)
        uno.serial=serial
        calls=[0]
        def check():
            calls[0]+=1
            raise led.GuardError('실제 센서 경고')
        uno.check=check
        with self.assertRaises(led.GuardError): uno.command('FLOW 200 0 8 0')
        self.assertEqual(serial.writes,[])

    def test_go_window_has_no_network_check_before_command_write(self):
        events = []
        class FakeSerial:
            def write(self, value): events.append(('write', value))
            def flush(self): pass
            def readline(self):
                return b'GO\n' if events[-1] == ('write', b'?') else b'OK\n'
        uno=led.GuardedUno.__new__(led.GuardedUno)
        uno.serial=FakeSerial()
        uno.check=lambda: events.append(('check',))
        uno.command('FLOW 200 0 8 0')
        go = events.index(('write', b'?'))
        flow = events.index(('write', b'FLOW 200 0 8 0\n'))
        self.assertEqual(flow, go + 1, events)
    @patch('hardware.cloud_sim_led.execute')
    @patch('hardware.cloud_sim_led.report_result')
    @patch('hardware.cloud_sim_led.request', return_value={'command': CMD})
    def test_warmup_rejects_pending_request(self, request, report, execute):
        led.poll_once('https://example.test','token','http://localhost','/dev/ttyACM0',True)
        execute.assert_not_called()
        self.assertEqual(request.call_args.args[0], 'https://example.test/api/hardware/sim-command?version=2')
        self.assertEqual(report.call_args.args[3]['status'],'rejected')
        self.assertFalse(report.call_args.args[3]['ledCommandAck'])
    @patch('hardware.cloud_sim_led.plan',return_value={'nodes':[],'edges':[],'path':[],'red':[4],'routeStatus':'no_route'})
    @patch('hardware.cloud_sim_led.ensure_safe')
    def test_no_route_red_only_is_explicit(self, guard, plan):
        out=led.execute(CMD,'http://localhost:5000','/dev/ttyACM0',FakeUno,seconds=.01,cancel_check=lambda:None)
        self.assertEqual(out['routeStatus'],'no_route')
        self.assertTrue(out['stopCommandAck'])
        self.assertIn('안전 경로 없음',out['message'])
        self.assertIn('발광 여부 미확인',out['message'])
    def test_mapping_error_does_not_become_red_only(self):
        floor={'nodes':[{'id':'N4'}], 'sensors':[{'id':'FLM-10','type':'flame','node':'N10'}]}
        module=SimpleNamespace(load_files=lambda: ({},floor),
            demo_snapshot=lambda *a: {'route':{'nodes':['N4','N2'],'edges':['E1']}},
            inspect_route=lambda *a: (_ for _ in ()).throw(ValueError('LED mapping failed')),
            fire_led_indices=lambda *a: ([4],[]))
        with patch.dict(sys.modules,{'hardware.led_routes':module}):
            with self.assertRaisesRegex(ValueError,'LED mapping failed'):
                led.plan(CMD)
    @patch('hardware.cloud_sim_led.request',return_value={'ok':True,'ready':False,'reason':'센서 미수신'})
    def test_guard_reason_is_reported(self, request):
        with self.assertRaisesRegex(led.GuardError,'센서 미수신'):
            led.ensure_safe('http://localhost:5000',datetime.now(timezone.utc)+timedelta(seconds=30))

    def test_demo_checks_sim_mode_and_reported_real_fire(self):
        expires = datetime.now(timezone.utc) + timedelta(seconds=30)
        with patch('hardware.cloud_sim_led.request', return_value={'operationMode':'simulation','realFireDetected':False}) as req:
            led.ensure_demo_safe('http://localhost:5000', expires)
            self.assertEqual(req.call_args.args[0], 'http://localhost:5000/api/state')
        for snapshot in ({'operationMode':'real','realFireDetected':False},
                         {'operationMode':'simulation','realFireDetected':True},
                         {'operationMode':'simulation'}, None):
            with self.subTest(snapshot=snapshot), patch('hardware.cloud_sim_led.request', return_value=snapshot):
                with self.assertRaises(led.GuardError):
                    led.ensure_demo_safe('http://localhost:5000', expires)
        with patch('hardware.cloud_sim_led.request', side_effect=OSError):
            with self.assertRaises(led.GuardError):
                led.ensure_demo_safe('http://localhost:5000', expires)
        with self.assertRaises(led.GuardError):
            led.ensure_demo_safe('http://localhost:5000', datetime.now(timezone.utc)-timedelta(seconds=1))

    @patch('hardware.cloud_sim_led.plan',return_value={'nodes':['N4','N2'],'edges':['E01'],'path':[1,2,3],'red':[4],'routeStatus':'ok'})
    @patch('hardware.cloud_sim_led.ensure_safe')
    @patch('hardware.cloud_sim_led.ensure_demo_safe')
    def test_demo_opt_in_is_separate_and_tagged(self, demo, guard, plan):
        out = led.execute(CMD,'http://localhost:5000','/dev/ttyACM0',FakeUno,seconds=.01,demo_no_sensors=True,cancel_check=lambda:None)
        self.assertEqual(out['safetyMode'],'simulation_only')
        self.assertIn('실제 센서 감시 안 함',out['message'])
        self.assertTrue(out['ledCommandAck'])
        demo.assert_called()
        guard.assert_not_called()
        demo.reset_mock()
        out = led.execute(CMD,'http://localhost:5000','/dev/ttyACM0',FakeUno,seconds=.01,cancel_check=lambda:None)
        self.assertEqual(out['safetyMode'],'sensor_guarded')
        guard.assert_called()
        demo.assert_not_called()

    @patch('hardware.cloud_sim_led.plan',return_value={'nodes':['N4','N2'],'edges':['E01'],'path':[1,2,3],'red':[4],'routeStatus':'ok'})
    def test_demo_stops_if_local_state_changes_during_output(self, plan):
        calls = [0]
        def check(*args):
            calls[0] += 1
            if calls[0] >= 5:
                raise led.GuardError('모드 변경')
        with patch('hardware.cloud_sim_led.ensure_demo_safe',side_effect=check):
            out = led.execute(CMD,'http://localhost:5000','/dev/ttyACM0',FakeUno,seconds=.2,demo_no_sensors=True,cancel_check=lambda:None)
        self.assertEqual(out['status'],'failed')
        self.assertEqual(out['safetyMode'],'simulation_only')
        self.assertEqual(instances[0].calls[-2:],['stop','close'])

if __name__=='__main__': unittest.main()
