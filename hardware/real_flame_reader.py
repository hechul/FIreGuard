#!/usr/bin/env python3
"""Raspberry Pi의 불꽃센서 11개를 읽어 FireGuard UI로 전송한다.

LM393형 불꽃센서는 현재 실물 테스트 결과 ACTIVE LOW:
- 평상시 DO HIGH
- 불꽃 감지 DO LOW

예시:
  python hardware/flame_multi_reader.py --api http://192.168.0.10:5000 --show-raw
  python hardware/flame_multi_reader.py --api http://127.0.0.1:5000 --only FLM-01
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Raspberry Pi OS에서는 lgpio 백엔드를 우선 사용한다.
os.environ.setdefault("GPIOZERO_PIN_FACTORY", "lgpio")

try:
    from gpiozero import DigitalInputDevice
except ImportError as exc:
    raise SystemExit(
        "gpiozero를 불러오지 못했습니다. Raspberry Pi에서 "
        "'sudo apt install -y python3-lgpio python3-gpiozero' 후, "
        "venv는 --system-site-packages 옵션으로 만들어 주세요."
    ) from exc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hardware.config import FLAME_ACTIVE_LOW, FLAME_SENSORS  # noqa: E402
from hardware.real_sensor_outbox import PendingFireSamples  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FireGuard 불꽃센서 11채널 REAL 입력")
    parser.add_argument("--api", default="http://127.0.0.1:5001", help="REAL 로컬 서버 주소")
    parser.add_argument("--only", default="", help="예: FLM-01 또는 FLM-01,FLM-02")
    parser.add_argument("--samples", type=int, default=3, help="상태 확정에 필요한 연속 동일 샘플 수")
    parser.add_argument("--interval", type=float, default=0.10, help="GPIO 샘플 주기(초)")
    parser.add_argument("--heartbeat", type=float, default=5.0, help="전체 상태 재전송 주기(초)")
    parser.add_argument("--timeout", type=float, default=0.3, help="HTTP 타임아웃(초)")
    parser.add_argument("--show-raw", action="store_true", help="각 센서 RAW/HIGH-LOW 출력")
    parser.add_argument("--list", action="store_true", help="센서/Node/GPIO 매핑만 출력")
    return parser.parse_args()


def selected_ids(only: str) -> list[str]:
    if not only.strip():
        return list(FLAME_SENSORS)
    ids = [item.strip().upper() for item in only.split(",") if item.strip()]
    unknown = [sid for sid in ids if sid not in FLAME_SENSORS]
    if unknown:
        raise SystemExit(f"알 수 없는 센서: {', '.join(unknown)}")
    return ids


def post_json(base_url: str, path: str, payload: dict, timeout: float) -> dict:
    url = base_url.rstrip("/") + path
    body = json.dumps(payload).encode("utf-8")
    req = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            data = json.loads(raw) if raw else {}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"서버 연결 실패: {exc.reason}") from exc
    except (OSError, TimeoutError, ValueError) as exc:
        raise RuntimeError(f"서버 응답 실패: {type(exc).__name__}") from exc
    if data.get("ok") is False:
        raise RuntimeError(data.get("error") or "FireGuard API 오류")
    return data


def main() -> int:
    args = parse_args()
    ids = selected_ids(args.only)

    if args.list:
        for sid in ids:
            cfg = FLAME_SENSORS[sid]
            print(f"{sid}: {cfg['node']} / BCM GPIO{cfg['bcm']} / Physical Pin {cfg['physical']}")
        return 0

    samples_needed = max(1, args.samples)
    devices: dict[str, DigitalInputDevice] = {}
    try:
        for sid in ids:
            cfg = FLAME_SENSORS[sid]
            devices[sid] = DigitalInputDevice(
                cfg["bcm"],
                pull_up=None,
                active_state=True,
            )

        print("FireGuard Flame Reader 시작")
        print(f"API: {args.api}")
        for sid in ids:
            cfg = FLAME_SENSORS[sid]
            print(f"  {sid} -> {cfg['node']} / GPIO{cfg['bcm']} (Pin {cfg['physical']})")
        print(f"ACTIVE LOW: {FLAME_ACTIVE_LOW} / debounce: {samples_needed} samples")
        print("Ctrl+C 종료")

        candidate: dict[str, bool | None] = {sid: None for sid in ids}
        streak: dict[str, int] = {sid: 0 for sid in ids}
        stable: dict[str, bool | None] = {sid: None for sid in ids}
        last_full_send = 0.0
        last_error = ""
        pending_fires = PendingFireSamples()
        send_full_after_fire = False

        while True:
            changed: dict[str, bool] = {}

            for sid in ids:
                dev = devices[sid]
                raw = bool(dev.pin.state)

                # 현재 불꽃센서: HIGH=정상, LOW=화재
                active = not raw if FLAME_ACTIVE_LOW else raw

                if args.show_raw:
                    print(
                        f"{sid} {FLAME_SENSORS[sid]['node']} | "
                        f"RAW={'HIGH' if raw else 'LOW'} | FIRE={active}"
                    )

                if candidate[sid] == active:
                    streak[sid] += 1
                else:
                    candidate[sid] = active
                    streak[sid] = 1

                if streak[sid] >= samples_needed and stable[sid] != active:
                    stable[sid] = active
                    changed[sid] = active
                    print(
                        f"[{time.strftime('%H:%M:%S')}] {sid} {FLAME_SENSORS[sid]['node']} "
                        f"=> {'FIRE' if active else 'CLEAR'}"
                    )

            now = time.monotonic()
            full_due = now - last_full_send >= max(1.0, args.heartbeat)
            all_ready = all(value is not None for value in stable.values())
            payload = None
            pending_fires.observe(changed)
            if pending_fires.pending:
                payload = {"flame": pending_fires.next()}
            elif send_full_after_fire and all_ready:
                payload = {"flame": {sid: bool(stable[sid]) for sid in ids}}
            elif changed:
                payload = {"flame": changed}
            elif full_due and all_ready:
                payload = {"flame": {sid: bool(stable[sid]) for sid in ids}}

            if payload is not None:
                try:
                    post_json(args.api, "/api/hardware/batch", payload, args.timeout)
                    if pending_fires.pending:
                        pending_fires.accepted(payload['flame'])
                        send_full_after_fire = True
                    elif all_ready and set(payload['flame']) == set(ids):
                        send_full_after_fire = False
                        last_full_send = now
                    if last_error:
                        print("[API] 연결 복구")
                        last_error = ""
                except RuntimeError as exc:
                    msg = str(exc)
                    if msg != last_error:
                        print(f"[API] {msg}")
                        last_error = msg

            time.sleep(max(0.02, args.interval))

    except KeyboardInterrupt:
        print("\nFlame Reader 종료")
        return 0
    finally:
        for dev in devices.values():
            dev.close()


if __name__ == "__main__":
    raise SystemExit(main())
