#!/usr/bin/env python3
"""Read the 11 Pi flame inputs and publish full snapshots to FireGuard.

Sensor-only integration: it does not control LEDs or report LED success.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'config/cloud_sensors.json').read_text(encoding='utf-8'))


class StableInputs:
    """Confirm each active-low input after consecutive equal samples."""
    def __init__(self, ids, samples=3):
        self.samples = samples
        self.candidates = {sid: None for sid in ids}
        self.counts = {sid: 0 for sid in ids}
        self.stable = {sid: None for sid in ids}

    def sample(self, raw_high):
        changed = False
        for sid, raw in raw_high.items():
            active = not raw
            if self.candidates[sid] == active:
                self.counts[sid] += 1
            else:
                self.candidates[sid], self.counts[sid] = active, 1
            if self.counts[sid] >= self.samples and self.stable[sid] != active:
                self.stable[sid] = active
                changed = True
        return changed, None if any(v is None for v in self.stable.values()) else dict(self.stable)


def send(api, token, payload, timeout=2):
    body = json.dumps(payload).encode('utf-8')
    req = Request(api.rstrip('/') + '/api/hardware/telemetry', data=body, method='POST',
                  headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
    try:
        with urlopen(req, timeout=timeout) as res:
            result = json.load(res)
    except HTTPError as exc:
        raise RuntimeError(f'HTTP {exc.code}: 인증, 데이터 형식 또는 서버 설정을 확인하세요.') from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise RuntimeError('서버 전송 실패: 인터넷 연결을 확인하세요.') from None
    if not isinstance(result, dict) or result.get('ok') is not True:
        raise RuntimeError('서버가 요청을 거절했습니다.')
    if result.get('accepted') is not True:
        raise RuntimeError('서버가 중복 또는 오래된 상태를 거절했습니다. Pi 시간을 확인하세요.')


class Publisher:
    """Network worker publishes the latest snapshot; sampling never waits on HTTP."""
    def __init__(self, api, token, device_id, heartbeat=5):
        self.api, self.token, self.device_id, self.heartbeat = api, token, device_id, heartbeat
        self.boot_id = str(uuid4())
        self.sequence = 0
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.stop_event = threading.Event()
        self.latest = None
        self.worker = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.worker.start()

    def update(self, flame, observed_at, changed):
        with self.lock:
            self.latest = (dict(flame), observed_at)
        if changed:
            self.wake.set()

    def _run(self):
        previous_error = None
        while not self.stop_event.is_set():
            self.wake.wait(self.heartbeat)
            self.wake.clear()
            if self.stop_event.is_set():
                break
            with self.lock:
                snapshot = self.latest
            if snapshot is None:
                continue
            flame, observed_at = snapshot
            payload = {'deviceId': self.device_id, 'bootId': self.boot_id,
                       'sequence': self.sequence, 'observedAt': observed_at,
                       'mappingVersion': CONFIG['mappingVersion'], 'flame': flame,
                       'led': {'status': 'unknown'}}
            self.sequence += 1
            try:
                send(self.api, self.token, payload)
                if previous_error:
                    print('서버 연결 복구', flush=True)
                print(f'전송 성공 · 감지 센서: {", ".join(k for k,v in flame.items() if v) or "없음"}', flush=True)
                previous_error = None
            except RuntimeError as exc:
                if str(exc) != previous_error:
                    print(str(exc), file=sys.stderr, flush=True)
                previous_error = str(exc)

    def close(self):
        self.stop_event.set()
        self.wake.set()
        self.worker.join(timeout=3)


def main():
    parser = argparse.ArgumentParser(description='Pi 불꽃 센서 11개 클라우드 전송 (LED 제어 없음)')
    parser.add_argument('--api', default='https://fire-guard-seven.vercel.app')
    parser.add_argument('--device-id', default=os.environ.get('FIREGUARD_DEVICE_ID', 'pi-01'))
    args = parser.parse_args()
    parsed = urlsplit(args.api)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        parser.error('--api는 인증정보가 없는 HTTPS 서버 주소여야 합니다.')
    token = os.environ.get('FIREGUARD_DEVICE_TOKEN', '')
    if len(token) < 32:
        parser.error('FIREGUARD_DEVICE_TOKEN 환경변수를 확인하세요.')
    os.environ.setdefault('GPIOZERO_PIN_FACTORY', 'lgpio')
    try:
        from gpiozero import DigitalInputDevice
    except ImportError:
        raise SystemExit('gpiozero/lgpio가 필요합니다. Pi의 기존 하드웨어 환경에서 실행하세요.') from None

    devices = {}
    publisher = Publisher(args.api, token, args.device_id)
    try:
        for sensor in CONFIG['sensors']:
            devices[sensor['id']] = DigitalInputDevice(sensor['bcm'], pull_up=None, active_state=True)
        stable = StableInputs(devices)
        publisher.start()
        print('센서 11개 상태를 읽습니다. 종료: Ctrl+C', flush=True)
        while True:
            changed, snapshot = stable.sample({sid: bool(device.pin.state) for sid, device in devices.items()})
            if snapshot is not None:
                observed = datetime.now(timezone.utc).isoformat()
                publisher.update(snapshot, observed, changed)
            time.sleep(0.1)
    except KeyboardInterrupt:
        print('\n센서 읽기 종료', flush=True)
    finally:
        if publisher.worker.is_alive():
            publisher.close()
        for device in devices.values():
            device.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
