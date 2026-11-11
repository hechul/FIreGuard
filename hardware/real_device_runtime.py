#!/usr/bin/env python3
"""Opt-in REAL telemetry runtime with separately gated verified LED output.

The supplied mapping is unverified: physical output is locked until it is
verified and confirmed. A stale sensor forces STOP instead of treating an
unknown sensor as safe. An Arduino OK is not evidence of physical light.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import signal
import threading
import time
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen


def _terminate_as_interrupt(signum, frame):
    """Let a normal service stop run the same LED STOP cleanup as Ctrl+C."""
    raise KeyboardInterrupt


def assess_snapshot(snapshot, floorplan, layout):
    """Check an authoritative REAL snapshot without changing or controlling it.

    A disconnected alarm is still blocked, but it makes LED output ineligible;
    it is never converted into a healthy sensor to placate old mapping code.
    The return contains proposed nodes only, never LED command acknowledgements.
    """
    reasons = []
    if not isinstance(snapshot, dict) or snapshot.get('operationMode') != 'real':
        raise ValueError('An authoritative REAL snapshot is required')
    sensors = [s for s in floorplan.get('sensors', []) if s.get('type') == 'flame']
    mapping = {s.get('id'): s.get('node') for s in sensors}
    if len(sensors) != 11 or len(mapping) != 11 or None in mapping:
        raise ValueError('The Pi floorplan must have 11 unique flame sensors')
    flame = snapshot.get('flameSensors')
    raw = snapshot.get('rawFlame')
    if not isinstance(flame, dict) or set(flame) != set(mapping) or not isinstance(raw, dict) or set(raw) != set(mapping):
        raise ValueError('All 11 REAL sensor statuses are required')
    for sid, value in flame.items():
        if (not isinstance(value, dict) or type(value.get('active')) is not bool
                or type(value.get('connected')) is not bool
                or raw[sid] is not None and type(raw[sid]) is not bool):
            raise ValueError('Invalid REAL sensor status')
        if value['connected'] and raw[sid] is None:
            raise ValueError('A connected REAL sensor requires a fresh raw sample')
        if not value['connected'] and raw[sid] is not None:
            raise ValueError('An unconfirmed sensor cannot provide a fresh raw sample')
        if raw[sid] is True and not value['active']:
            raise ValueError('An active raw fire cannot be reported unlatched')
    latched = {sid for sid, value in flame.items() if value['active']}
    blocked = snapshot.get('blockedNodes')
    if (not isinstance(blocked, list) or any(not isinstance(n, str) for n in blocked)
            or len(set(blocked)) != len(blocked)
            or set(blocked) != {mapping[sid] for sid in latched}):
        raise ValueError('Graph blocked nodes must match all latched fires')
    if type(snapshot.get('realFireDetected')) is not bool or bool(latched) != snapshot['realFireDetected']:
        raise ValueError('REAL fire indication disagrees with latched sensors')
    route = snapshot.get('route')
    if route is not None:
        if not isinstance(route, dict) or not isinstance(route.get('nodes'), list) or any(n in blocked for n in route['nodes']):
            raise ValueError('Proposed route must avoid all latched fire nodes')
    if any(not value['connected'] for value in flame.values()):
        reasons.append('실제 센서 입력이 오래됐거나 확인되지 않음')
    if snapshot.get('persistencePending') is not False:
        reasons.append('화재 상태 저장을 확인하지 못함')
    if not isinstance(layout, dict) or layout.get('verified') is not True or layout.get('mapping_status') != 'confirmed':
        reasons.append('실물 LED 매핑 미검증')
    # A preflight is not itself permission or evidence of physical output.
    reasons.append('현장 장비 및 단일 송신자 확인 필요')
    return {'readyForLiveOutput': False, 'latchedSensorIds': sorted(latched),
            'blockedNodes': sorted(blocked), 'routeNodes': list(route['nodes']) if route else [],
            'reasons': reasons, 'ledCommandAck': False, 'sentToCloud': False}


def _state_key(snapshot):
    """Ignore refreshed timestamps while observing each meaningful change."""
    return json.dumps({'startNode': snapshot['startNode'], 'blockedNodes': snapshot['blockedNodes'],
                       'blockedEdges': snapshot.get('blockedEdges'), 'route': snapshot.get('route'),
                       'flame': {k: [v['active'], v['connected']]
                                 for k, v in snapshot['flameSensors'].items()},
                       'persistencePending': snapshot.get('persistencePending')}, sort_keys=True)


def reconcile_cloud_latches(local_snapshot, cloud_snapshot, *, device_id, restore):
    """Restore the union before first publication; no raw input is fabricated.

    This relies on exclusive ownership of the device's REAL publisher. An
    independent legacy sender must be stopped; the local process lock alone
    cannot enforce that external operational prerequisite.
    """
    if not isinstance(local_snapshot, dict) or local_snapshot.get('operationMode') != 'real':
        raise RuntimeError('Pi REAL 상태를 확인할 수 없습니다')
    local_flame = local_snapshot.get('flameSensors')
    if not isinstance(local_flame, dict) or len(local_flame) != 11:
        raise RuntimeError('Pi 센서 구성을 확인할 수 없습니다')
    cloud = cloud_snapshot.get('cloud') if isinstance(cloud_snapshot, dict) else None
    cloud_flame = cloud_snapshot.get('flameSensors') if isinstance(cloud_snapshot, dict) else None
    if (not isinstance(cloud, dict) or cloud.get('enabled') is not True
            or cloud.get('hasTelemetry') is not True or cloud.get('deviceId') != device_id
            or cloud_snapshot.get('operationMode') != 'real'
            or not isinstance(cloud_flame, dict) or set(cloud_flame) != set(local_flame)):
        raise RuntimeError('클라우드 마지막 REAL 보고를 확인할 수 없습니다')
    if any(not isinstance(v, dict) or type(v.get('active')) is not bool for v in cloud_flame.values()):
        raise RuntimeError('클라우드 화재 상태 형식이 올바르지 않습니다')
    ids = sorted(sid for sid, value in cloud_flame.items() if value['active'])
    listed = cloud_snapshot.get('realFireSensorIds')
    if (not isinstance(listed, list) or any(not isinstance(sid, str) for sid in listed)
            or len(set(listed)) != len(listed) or sorted(listed) != ids
            or type(cloud_snapshot.get('realFireDetected')) is not bool
            or cloud_snapshot['realFireDetected'] != bool(ids)):
        raise RuntimeError('클라우드 화재 상태가 일치하지 않습니다')
    before = {sid for sid, value in local_flame.items() if isinstance(value, dict) and value.get('active') is True}
    restored = restore(ids)
    state = restored.get('state') if isinstance(restored, dict) and restored.get('ok') is True else None
    after = state.get('realFireSensorIds') if isinstance(state, dict) else None
    if not isinstance(after, list) or not (before | set(ids)).issubset(set(after)):
        raise RuntimeError('화재 상태 복원을 확인할 수 없습니다')
    return state


def _no_redirect_json(url, *, headers=None, payload=None, timeout=3):
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl): return None
    headers = {'Accept':'application/json', **(headers or {})}
    data = None
    if payload is not None:
        data = json.dumps(payload, allow_nan=False).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    with build_opener(NoRedirect()).open(Request(url, data=data, headers=headers), timeout=timeout) as response:
        return json.load(response)


class RealLedController:
    """Single owner of the optional serial device; FLOW ACK is not optical proof."""
    def __init__(self, source, floor, layout, *, enabled=False, port=None,
                 uno_factory=None, planner=None, translate=None, clock=time.monotonic):
        self.source, self.floor, self.layout = source, floor, layout
        self.enabled, self.port, self.clock = enabled, port, clock
        if enabled and (not port or layout.get('verified') is not True or layout.get('mapping_status') != 'confirmed'):
            raise ValueError('실제 LED 출력 잠금: 포트와 검증된 confirmed 매핑이 필요합니다')
        self.uno_factory, self.planner, self.translate = uno_factory, planner, translate
        self.uno = None
        self.expected = None
        self.output = self._result('not_running')
        self.last_ping = 0.0
        self.last_all_zone = None
        self.plan_key = None

    @staticmethod
    def _result(status, *, ack=False, path=(), red=(), error=None):
        return {'led_status': status, 'command_ack': ack, 'commanded_path': list(path),
                'commanded_fire': list(red), 'led_error': error}

    def _check_current(self):
        current = self.source()
        assess_snapshot(current, self.floor, self.layout)
        if (not current.get('ledSafetyReady') or current.get('persistencePending') is not False
                or _state_key(current) != self.expected):
            raise RuntimeError('실제 센서 상태가 변경되었거나 확인되지 않습니다')

    def _stop(self, reason=None):
        if self.uno is None:
            self.expected = None
            return self._result('error' if reason else 'off', error=reason)
        try:
            self.uno.stop()
        except Exception:
            self.expected = None
            try: self.uno.close()
            finally: self.uno = None
            return self._result('error', error='STOP 응답 미확인')
        self.expected = None
        return self._result('error' if reason else 'off', ack=True, error=reason)

    def step(self, snapshot):
        assess_snapshot(snapshot, self.floor, self.layout)
        if snapshot.get('ledSafetyReady') is not True or snapshot.get('persistencePending') is not False:
            self.last_all_zone = None
            self.plan_key = None
            self.output = self._stop('센서 입력 또는 화재 저장 미확인')
            return deepcopy(self.output)
        if not snapshot['realFireDetected']:
            self.last_all_zone = None
            self.plan_key = None
            if self.output['led_status'] != 'off': self.output = self._stop()
            return deepcopy(self.output)
        key = _state_key(snapshot)
        try:
            if key != self.plan_key:
                self.last_all_zone = None
                self.plan_key = None
                if self.planner is None:
                    from hardware.all_zone_routes import calculate_all_zones
                    self.last_all_zone = calculate_all_zones(snapshot, self.floor, self.layout)
                else:
                    self.last_all_zone = self.planner(snapshot, self.floor, self.layout)
                self.plan_key = key
            if not self.enabled:
                self.output = self._result('not_running')
                return deepcopy(self.output)
            if self.uno is None:
                if self.uno_factory is None:
                    from hardware.cloud_sim_led import GuardedUno
                    self.uno_factory = GuardedUno
                self.expected = key
                self.uno = self.uno_factory(self.port, self._check_current)
                self.uno.stop()
            if self.output['led_status'] != 'active' or key != self.expected:
                # Stop a prior path before computing/issuing a replacement.
                self.uno.stop()
                self.expected = key
                self._check_current()
                plan = self.last_all_zone
                if isinstance(plan, tuple):  # Legacy injected test planner.
                    path, red = plan
                else:
                    path, red = plan['ledLogicalIndices'], plan['fireLedLogicalIndices']
                if not path and not red:
                    raise ValueError('화재 위치 또는 대피 LED 매핑을 확인할 수 없습니다')
                if self.translate is None:
                    from pi_led_usb import logical_to_wire
                    self.translate = logical_to_wire
                self._check_current()
                self.uno.flow(path, red)
                # Report wire slots only after the Uno's FLOW OK response.
                self.output = self._result('active', ack=True,
                    path=[self.translate(i) for i in path], red=[self.translate(i) for i in red])
                self.last_ping = self.clock()
            elif self.clock() - self.last_ping >= 1.0:
                self.uno.command('PING')
                self.last_ping = self.clock()
        except Exception as error:
            self.output = self._stop(f'LED 명령 실패: {type(error).__name__}')
        return deepcopy(self.output)

    def unavailable(self):
        self.last_all_zone = None
        self.plan_key = None
        self.output = self._stop('Pi 실제 상태 수신 실패') if self.enabled else self._result('not_running')

    def close(self):
        self.unavailable()
        if self.uno is not None:
            self.uno.close()
            self.uno = None


class PublisherPump:
    """One reporter thread, most recent valid snapshot only, no fake heartbeats."""
    def __init__(self, reporter, floor, layout):
        self.reporter, self.floor, self.layout = reporter, floor, layout
        self._lock, self._wake, self._quit = threading.Lock(), threading.Event(), threading.Event()
        self._latest = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self): self.thread.start()

    def update(self, snapshot, output, all_zone_plan=None):
        with self._lock: self._latest = (deepcopy(snapshot), deepcopy(output), time.monotonic(), deepcopy(all_zone_plan))
        self._wake.set()

    def invalidate(self):
        with self._lock: self._latest = None

    def _run(self):
        while not self._quit.is_set():
            self._wake.wait(0.5); self._wake.clear()
            with self._lock: data = deepcopy(self._latest)
            # Never manufacture a fresh cloud heartbeat from an old local state.
            # A request already in flight can finish after local failure; it is
            # bounded by CloudReporter's timeout and is never retried as fresh.
            if data is None or time.monotonic() - data[2] > 1.0: continue
            try: self.reporter.maybe_report(data[0], self.floor, self.layout, all_zone_plan=data[3], **data[1])
            except Exception as error: print('[REAL CLOUD] 전송 실패:', type(error).__name__, flush=True)

    def close(self):
        self.invalidate(); self._quit.set(); self._wake.set(); self.thread.join(timeout=4)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only', action='store_true', help='Read-only status; never send or open Arduino')
    parser.add_argument('--enable-real-cloud', action='store_true', help='Explicitly enable REAL telemetry')
    parser.add_argument('--assert-exclusive-publisher', action='store_true', help='Confirm all legacy publishers are stopped')
    parser.add_argument('--enable-verified-led', action='store_true', help='Enable LED only with verified confirmed mapping')
    parser.add_argument('--port', help='Arduino USB serial port')
    parser.add_argument('--local-url', default='http://127.0.0.1:5001')
    parser.add_argument('--floorplan', default='static/data/floorplan.json')
    parser.add_argument('--layout', default='hardware/led_layout_162.json')
    args = parser.parse_args()
    url = urlparse(args.local_url)
    if url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost') or url.path not in ('', '/') or url.query or url.fragment or url.username or url.password:
        parser.error('local-url must be a loopback HTTP origin')
    floor = json.loads(Path(args.floorplan).read_text(encoding='utf-8'))
    layout = json.loads(Path(args.layout).read_text(encoding='utf-8'))
    def source():
        with urlopen(args.local_url.rstrip('/') + '/api/real/state', timeout=0.5) as response:
            return json.load(response)
    if args.check_only:
        if args.enable_real_cloud or args.enable_verified_led or args.port:
            parser.error('--check-only cannot enable output')
        print(json.dumps(assess_snapshot(source(), floor, layout), ensure_ascii=False))
        return
    if not args.enable_real_cloud or not args.assert_exclusive_publisher:
        parser.error('REAL 송신 및 기존 송신자 종료 확인 옵션이 필요합니다')
    if args.enable_verified_led and (not args.port or layout.get('verified') is not True or layout.get('mapping_status') != 'confirmed'):
        parser.error('실제 LED 출력은 실측 검증된 confirmed 매핑 및 포트가 필요합니다')
    if args.port and not args.enable_verified_led:
        parser.error('--port requires --enable-verified-led')
    telemetry_url = os.environ.get('FIREGUARD_TELEMETRY_URL', '')
    cloud = urlparse(telemetry_url)
    device_id = os.environ.get('FIREGUARD_DEVICE_ID', 'pi-01')
    local_token = os.environ.get('FIREGUARD_REAL_LOCAL_TOKEN', '')
    device_token = os.environ.get('FIREGUARD_DEVICE_TOKEN', '')
    if (cloud.scheme != 'https' or not cloud.hostname or cloud.username or cloud.password
            or cloud.path != '/api/hardware/telemetry' or cloud.query or cloud.fragment
            or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', device_id)
            or len(local_token) < 32 or len(device_token) < 32):
        parser.error('REAL 장치 URL 및 장치/로컬 비밀 설정을 확인하세요')
    # This lock prevents two copies of this runtime. Legacy exporters do not
    # honor it; the operator must explicitly stop them before starting.
    lock_path = Path(os.environ.get('FIREGUARD_REAL_RUNTIME_LOCK', str(Path.home()/'.local/state/fireguard/real-runtime.lock')))
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('a') as lock:
        try: fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise SystemExit('REAL runtime이 이미 실행 중입니다')
        from hardware.cloud_telemetry import CloudReporter
        from hardware.real_allzone_reporter import AllZoneReporter
        reporter = AllZoneReporter(CloudReporter(mode='send', interval=5.0, allow_sim=False))
        # Never publish all-false or enable LEDs until the last cloud alarms
        # have been merged into durable local latches. Unknown/no history or
        # any network/authentication/restore failure stops startup.
        cloud_origin = f'{cloud.scheme}://{cloud.netloc}'
        try:
            local_state = source()
            assess_snapshot(local_state, floor, layout)
            previous = _no_redirect_json(cloud_origin + '/api/state',
                                         headers={'Authorization':'Bearer ' + device_token})
            merged = reconcile_cloud_latches(local_state, previous, device_id=device_id,
                restore=lambda ids: _no_redirect_json(args.local_url.rstrip('/') + '/api/real/restore',
                    headers={'X-Fireguard-Local-Token':local_token}, payload={'sensorIds':ids}))
            assess_snapshot(merged, floor, layout)
        except Exception as error:
            raise SystemExit('마지막 REAL 화재 상태 복원 실패: 송신과 LED 출력을 시작하지 않았습니다 (' + type(error).__name__ + ')') from None
        controller = RealLedController(source, floor, layout, enabled=args.enable_verified_led, port=args.port)
        publisher = PublisherPump(reporter, floor, layout)
        publisher.start()
        last_problem = None
        previous_sigterm = signal.signal(signal.SIGTERM, _terminate_as_interrupt)
        try:
            while True:
                try:
                    snapshot = source()
                    assess_snapshot(snapshot, floor, layout)
                    output = controller.step(snapshot)
                    publisher.update(snapshot, output, controller.last_all_zone)
                    if last_problem:
                        print('[REAL] 로컬 상태 복구', flush=True); last_problem = None
                except Exception as error:
                    controller.unavailable()
                    publisher.invalidate()
                    problem = type(error).__name__
                    if problem != last_problem:
                        print('[REAL] 로컬 상태 확인 실패:', problem, flush=True); last_problem = problem
                time.sleep(0.25)
        except KeyboardInterrupt:
            pass
        finally:
            try:
                publisher.close()
            finally:
                try:
                    controller.close()
                finally:
                    signal.signal(signal.SIGTERM, previous_sigterm)


if __name__ == '__main__':
    main()
