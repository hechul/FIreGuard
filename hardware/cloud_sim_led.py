#!/usr/bin/env python3
"""Opt-in three-second Pi/Uno lab test; separate from REAL telemetry.

Requires exclusive access to the Uno. By default also requires the Pi guard
wrapper; the explicitly opted-in demo-only mode does not monitor real sensors.
This is a prototype demonstration, not a life-safety controller or optical LED check.
"""
from __future__ import annotations
import argparse
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import termios
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from hardware.cloud_sim_bridge import request, validate_command, report_result


class GuardError(RuntimeError):
    pass


def label_demo_result(result, demo_no_sensors):
    if demo_no_sensors:
        result['safetyMode'] = 'simulation_only'
        result['message'] = '모형 시연 · 실제 센서 감시 안 함 · ' + result['message']
    return result


def ensure_safe(local, expires_at):
    if datetime.now(timezone.utc) >= expires_at:
        raise GuardError('시험 요청 만료')
    try:
        status = request(local + '/api/hardware/guard', timeout=0.3)
    except Exception:
        raise GuardError('실제 센서 감시 연결 실패') from None
    if not isinstance(status, dict) or status.get('ok') is not True:
        raise GuardError('실제 센서 감시 응답 오류')
    if status.get('ready') is not True:
        reason = status.get('reason')
        raise GuardError(str(reason)[:160] if isinstance(reason, str) and reason else '실제 센서 감시 준비 안 됨')


def ensure_demo_safe(local, expires_at):
    """Check local SIM state only; this does not establish real sensor health."""
    if datetime.now(timezone.utc) >= expires_at:
        raise GuardError('시험 요청 만료')
    try:
        state = request(local + '/api/state', timeout=0.3)
    except Exception:
        raise GuardError('Pi 로컬 시뮬레이션 연결 실패') from None
    if not isinstance(state, dict) or state.get('operationMode') != 'simulation':
        raise GuardError('Pi 로컬 서버가 SIMULATION 모드가 아님')
    if state.get('realFireDetected') is not False:
        raise GuardError('로컬 서버에 실제 화재가 보고되었거나 상태를 확인할 수 없음')


def plan(command):
    from hardware.led_routes import load_files, demo_snapshot, inspect_route, fire_led_indices
    layout, floor = load_files()
    sensors = [s['id'] for s in floor['sensors'] if s.get('type') == 'flame' and s.get('node') == command['fireNode']]
    if len(sensors) != 1 or command['startNode'] not in {n['id'] for n in floor['nodes']}:
        raise ValueError('Pi 지도에 없는 출발점 또는 센서')
    snapshot = demo_snapshot(floor, sensors[0], command['startNode'])
    route = snapshot.get('route')
    if route is None:
        red, _ = fire_led_indices(snapshot, floor, layout)
        return {'nodes': [], 'edges': [], 'path': [], 'red': sorted(red), 'routeStatus': 'no_route'}
    if not isinstance(route, dict):
        raise ValueError('Pi 경로 형식 오류: LED 시험 취소')
    report = inspect_route(snapshot, floor, layout)
    edges = route.get('edges')
    if not isinstance(edges, list) or any(not isinstance(edge, str) for edge in edges):
        raise ValueError('Pi 경로 간선 형식 오류: LED 시험 취소')
    return {'nodes': report['nodes'], 'edges': edges, 'path': report['ordered'],
            'red': report['red'], 'routeStatus': 'ok'}


class GuardedUno:
    """Serial protocol with guard checks between each short read and write."""
    def __init__(self, port, check):
        self.check = check
        self.serial = None
        self.lock = None
        self.started = None
        try:
            import serial
            # Cooperating bridges share this lock; TIOCEXCL blocks later opens.
            self.lock = open('/tmp/fireguard-uno-demo.lock', 'w')
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            check()
            try:
                busy = subprocess.run(['fuser', port], capture_output=True, timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                raise GuardError('포트 사용 여부를 확인할 수 없음: fuser 필요') from None
            if busy.returncode != 1 or busy.stderr.strip():
                raise GuardError('Arduino 포트가 이미 사용 중이거나 확인 실패')
            self.serial = serial.Serial(port, 115200, timeout=0.05, write_timeout=0.3, exclusive=True)
            fcntl.ioctl(self.serial.fileno(), termios.TIOCEXCL)
            end = time.monotonic() + 2.5
            while time.monotonic() < end:
                check(); time.sleep(0.05)
            self.serial.reset_input_buffer()
            self.command('PING')
        except BaseException:
            self.close()
            raise

    def command(self, text, *, stop=False):
        if self.serial is None:
            raise GuardError('Arduino 연결 없음')
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if not stop: self.check()
            self.serial.write(b'?'); self.serial.flush()
            reply = self.serial.readline().decode('ascii', errors='replace').strip()
            if reply == 'GO': break
        else:
            raise TimeoutError('Arduino GO 응답 없음')
        if not stop: self.check()
        if text.startswith('FLOW '): self.started = time.monotonic()
        self.serial.write((text + '\n').encode('ascii')); self.serial.flush()
        while time.monotonic() < deadline:
            if not stop: self.check()
            reply = self.serial.readline().decode('ascii', errors='replace').strip()
            if reply == 'OK': return
            if reply == 'ERR': raise RuntimeError('Arduino 명령 거부')
        raise TimeoutError('Arduino OK 응답 없음')

    def flow(self, path, red):
        from pi_led_usb import logical_to_wire
        self.command('BEGIN')
        for name, indices in (('ADD', path), ('FIRE', red)):
            wires = [logical_to_wire(i) for i in indices]
            for n in range(0, len(wires), 12):
                self.command(name + ' ' + ' '.join(map(str, wires[n:n+12])))
        self.command('FLOW 200 0 8 0')

    def stop(self): self.command('STOP', stop=True)
    def close(self):
        if self.serial is not None:
            self.serial.close(); self.serial = None
        if self.lock is not None:
            self.lock.close(); self.lock = None


def execute(command, local, port, uno_factory=GuardedUno, seconds=3, *, demo_no_sensors=False):
    expires = validate_command(command)
    if not 0 < seconds <= 3:
        raise ValueError('시험 시간은 최대 3초')
    check = lambda: (ensure_demo_safe if demo_no_sensors else ensure_safe)(local, expires)
    check()
    route = plan(command)
    nodes, edges, path, red = route['nodes'], route['edges'], route['path'], route['red']
    route_status = route['routeStatus']
    check()
    uno = None
    ack = False
    interrupted = None
    stop_ok = False
    try:
        uno = uno_factory(port, check)
        uno.stop()
        check()
        if not path and not red:
            raise GuardError('표시할 경로 또는 화재 구간 없음')
        uno.flow(path, red)
        ack = True
        # Count from the actual FLOW write, not from the later OK response.
        deadline = uno.started + seconds
        while time.monotonic() < deadline:
            check()
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
    except Exception as exc:
        interrupted = str(exc)[:160]
    finally:
        if uno is not None:
            try:
                uno.stop(); stop_ok = True
            except Exception:
                stop_ok = False
            finally:
                uno.close()
    result = {'routeNodes': nodes, 'routeEdges': edges, 'routeStatus': route_status,
              'ledCommandAck': ack, 'stopCommandAck': stop_ok,
              'safetyMode': 'simulation_only' if demo_no_sensors else 'sensor_guarded'}
    if uno is None:
        return label_demo_result({**result, 'status':'rejected', 'message':'출력 전 중단: ' + (interrupted or 'Arduino 연결 실패')}, demo_no_sensors)
    if not stop_ok:
        return label_demo_result({**result, 'status':'failed', 'message':'STOP 응답 미확인; 물리 전원 확인 필요'}, demo_no_sensors)
    if interrupted:
        return label_demo_result({**result, 'status':'failed', 'message':'시험 중단: ' + interrupted}, demo_no_sensors)
    if route_status == 'no_route':
        return label_demo_result({**result, 'status':'completed', 'message':'안전 경로 없음; 화재 빨강 표시 명령과 STOP 응답 확인; 실물 발광 여부 미확인'}, demo_no_sensors)
    return label_demo_result({**result, 'status':'completed', 'message':'Uno FLOW 및 STOP 응답 확인; 실물 발광 여부 미확인'}, demo_no_sensors)


def poll_once(cloud, token, local, port, warming_up, *, demo_no_sensors=False):
    command = request(cloud + '/api/hardware/sim-command', token=token).get('command')
    if command:
        if warming_up:
            outcome = {'status':'rejected', 'message':'실물 시험 시작 전 대기 중이던 요청은 취소됨. 새로 요청하세요.',
                       'routeNodes':[], 'routeEdges':[], 'routeStatus':'unknown',
                       'ledCommandAck':False, 'stopCommandAck':False}
        else:
            try:
                outcome = execute(command, local, port, demo_no_sensors=demo_no_sensors)
            except Exception as exc:
                outcome = {'status':'rejected', 'message':str(exc)[:240], 'routeNodes':[],
                           'routeEdges':[], 'routeStatus':'unknown', 'ledCommandAck':False, 'stopCommandAck':False}
        if demo_no_sensors and outcome.get('safetyMode') != 'simulation_only':
            label_demo_result(outcome, True)
        report_result(cloud, token, command, outcome)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cloud-url', required=True)
    parser.add_argument('--local-url', default='http://127.0.0.1:5000')
    parser.add_argument('--port', required=True)
    parser.add_argument('--enable-lab-led', action='store_true')
    parser.add_argument('--demo-no-sensors', action='store_true',
                        help='감독하에 모형 시연 전용: 실제 센서 수집 확인 없이 LED 시험')
    args = parser.parse_args()
    cloud, local = args.cloud_url.rstrip('/'), args.local_url.rstrip('/')
    cp, lp = urlparse(cloud), urlparse(local)
    if cp.scheme != 'https' or not cp.hostname or cp.username or cp.password or cp.path not in ('', '/') or cp.query or cp.fragment:
        parser.error('cloud-url은 HTTPS 서버 주소여야 합니다')
    if lp.scheme != 'http' or lp.hostname not in ('127.0.0.1','localhost') or lp.path not in ('','/') or lp.query or lp.fragment:
        parser.error('local-url은 로컬 HTTP 주소여야 합니다')
    token = os.environ.get('FIREGUARD_DEVICE_TOKEN','')
    if not args.enable_lab_led or len(token) < 32:
        parser.error('--enable-lab-led 및 장치 토큰이 필요합니다')
    if args.demo_no_sensors:
        print('모형 시연 전용: 실제 센서 연결·화재 감시를 보장하지 않습니다.', flush=True)
    print('반드시 dry-run과 다른 LED 프로그램을 종료하세요.', flush=True)
    print('31초 준비 중: 준비 완료 전에는 웹에서 요청하지 마세요.', flush=True)
    warmup_until = time.monotonic() + 31
    ready_announced = False
    while True:
        try:
            warming_up = time.monotonic() < warmup_until
            if not warming_up and not ready_announced:
                print('실물 LED 시험 준비 완료: 이제 웹에서 새 요청을 보내세요.', flush=True)
                ready_announced = True
            # DB commands expire after 30 seconds. Requests already visible
            # during warm-up are discarded; the operator must wait for ready.
            poll_once(cloud, token, local, args.port, warming_up, demo_no_sensors=args.demo_no_sensors)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            print('시험 통신 오류:', type(exc).__name__, flush=True)
        time.sleep(1)


if __name__ == '__main__':
    raise SystemExit(main())
