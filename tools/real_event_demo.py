"""실제 Raspberry Pi 연동 전 REST 계약 확인용 샘플.

FireGuard 서버가 실행 중일 때 다른 터미널에서 실행하면 REAL 모드로 전환되고
4관 앞 Flame/MQ-2 입력을 순차 전송한다. 외부 패키지는 필요 없다.
"""

from __future__ import annotations

import json
import time
import urllib.request

BASE = "http://127.0.0.1:5000"


def post(path: str, data: dict):
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        BASE + path,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


print("1) Raspberry Pi heartbeat")
post("/api/hardware/heartbeat", {})
time.sleep(1)

print("2) 4관 앞 MQ-2 위험값")
post("/api/hardware/mq2", {"sensorId": "MQ2-04", "value": 720})
time.sleep(1)

print("3) 4관 앞 Flame ON")
post("/api/hardware/flame", {"sensorId": "FLM-07", "active": True})
time.sleep(3)

print("4) 센서 정상화")
post("/api/hardware/mq2", {"sensorId": "MQ2-04", "value": 100})
post("/api/hardware/flame", {"sensorId": "FLM-07", "active": False})
print("완료")
