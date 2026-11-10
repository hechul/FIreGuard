#!/usr/bin/env python3
"""Opt-in lab bridge for a Pi-local SIM dashboard and Arduino controller.

Dry-run only: no remote command can operate the Arduino or mutate local state.
This does not publish simulation telemetry to the real-device endpoint.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlparse
from urllib.request import Request, urlopen

# Running this file directly must still import modules from the Pi project root.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def request(url, *, token=None, data=None, timeout=2):
    headers = {'Accept': 'application/json'}
    body = None
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if data is not None:
        headers['Content-Type'] = 'application/json'
        body = json.dumps(data).encode()
    with urlopen(Request(url, data=body, headers=headers), timeout=timeout) as response:
        return json.load(response)


def safe_snapshot(local):
    snapshot = request(local + '/api/state', timeout=0.5)
    if snapshot.get('operationMode') != 'simulation':
        raise RuntimeError('Pi 로컬 대시보드가 SIMULATION 모드가 아닙니다')
    if snapshot.get('realFireDetected') is not False:
        raise RuntimeError('실제 화재가 감지되었거나 상태를 확인할 수 없습니다')
    return snapshot


def validate_command(command):
    if not isinstance(command, dict):
        raise ValueError('명령 형식이 올바르지 않습니다')
    for name in ('id', 'claimToken', 'startNode', 'fireNode', 'expiresAt'):
        if not isinstance(command.get(name), str) or not command[name] or len(command[name]) > 200:
            raise ValueError('명령 필드가 올바르지 않습니다: ' + name)
    expires = datetime.fromisoformat(command['expiresAt'].replace('Z', '+00:00'))
    if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
        raise ValueError('시험 요청이 만료되었습니다')
    return expires


def run_command(command, *, local):
    """Calculate a Pi-side preview without changing local state or Arduino."""
    validate_command(command)
    safe_snapshot(local)
    # These are the same floorplan and route calculator used by the Pi's
    # single-start LED program. Import lazily so the cloud app does not need
    # the Pi-only hardware modules, and never invoke an Arduino control API.
    from hardware.led_routes import demo_snapshot, load_files

    _layout, floor = load_files()
    sensors = [s['id'] for s in floor['sensors']
               if s.get('type') == 'flame' and s.get('node') == command['fireNode']]
    if len(sensors) != 1 or command['startNode'] not in {n['id'] for n in floor['nodes']}:
        raise ValueError('Pi 지도에서 출발 노드 또는 화재 센서를 확인할 수 없습니다')
    preview = demo_snapshot(floor, sensors[0], command['startNode'])
    route = preview.get('route')
    nodes = route.get('nodes') if isinstance(route, dict) else []
    if not isinstance(nodes, list) or any(not isinstance(node, str) for node in nodes):
        raise ValueError('Pi 예상 경로 형식이 잘못되었습니다')
    return {'status': 'completed',
            'message': 'Pi 계산 경로 미리보기; 실물 LED는 제어하지 않았습니다' if nodes else 'Pi 계산 결과 경로 없음; 실물 LED는 제어하지 않았습니다',
            'routeNodes': nodes, 'ledCommandAck': False}


def report_result(cloud, token, command, outcome):
    return request(cloud + '/api/hardware/sim-result', token=token,
                   data={'id': command['id'], 'claimToken': command['claimToken'], 'result': outcome})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cloud-url', required=True)
    parser.add_argument('--local-url', default='http://127.0.0.1:5000')
    parser.add_argument('--dry-run', action='store_true', help='validate commands without controlling hardware')
    args = parser.parse_args()
    cloud = args.cloud_url.rstrip('/')
    local = args.local_url.rstrip('/')
    cp, lp = urlparse(cloud), urlparse(local)
    if cp.scheme != 'https' or not cp.hostname or cp.username or cp.password or cp.path not in ('', '/'):
        parser.error('cloud-url은 HTTPS 서버 주소여야 합니다')
    if lp.scheme != 'http' or lp.hostname not in ('127.0.0.1', 'localhost') or lp.path not in ('', '/'):
        parser.error('local-url은 Pi의 로컬 HTTP 주소여야 합니다')
    token = os.environ.get('FIREGUARD_DEVICE_TOKEN', '')
    if not args.dry_run or len(token) < 32:
        parser.error('--dry-run 및 FIREGUARD_DEVICE_TOKEN 설정이 필요합니다')
    print('클라우드 시험 드라이런 시작: 실물 LED를 제어하지 않습니다', flush=True)
    while True:
        try:
            result = request(cloud + '/api/hardware/sim-command', token=token)
            command = result.get('command')
            if command:
                try:
                    outcome = run_command(command, local=local)
                except (ValueError, RuntimeError, OSError) as exc:
                    outcome = {'status': 'rejected', 'message': str(exc)[:240],
                               'routeNodes': [], 'ledCommandAck': False}
                if isinstance(command, dict) and command.get('id') and command.get('claimToken'):
                    report_result(cloud, token, command, outcome)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            print('시험 브리지 통신 오류:', type(exc).__name__, flush=True)
        time.sleep(1)


if __name__ == '__main__':
    raise SystemExit(main())
