"""실제 센서 API 시연. 먼저 대시보드에서 REAL 모드를 선택하세요."""
import json
import time
import urllib.request

BASE = "http://127.0.0.1:5000"

def post(path, data):
    req = urllib.request.Request(BASE + path, data=json.dumps(data).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=3) as response:
        return json.load(response)

if __name__ == "__main__":
    post("/api/hardware/heartbeat", {})
    print("동측 비상구 불꽃 감지")
    try:
        post("/api/hardware/flame", {"sensorId": "FLM-15", "active": True})
        time.sleep(3)
    finally:
        post("/api/hardware/flame", {"sensorId": "FLM-15", "active": False})
    print("정상 복귀 완료. 선택한 운영 모드는 유지됩니다.")
