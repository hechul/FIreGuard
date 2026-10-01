# Raspberry Pi → Flask 이벤트 계약

UI와 시뮬레이션은 이미 동일한 `SimulationState`를 사용합니다. 실제 배선이 끝나면 Raspberry Pi 센서 읽기 코드에서 아래 API만 호출하면 됩니다.

## Heartbeat

```http
POST /api/hardware/heartbeat
{}
```

## 불꽃 센서

```http
POST /api/hardware/flame
{"sensorId":"FLM-07","active":true}
```

## MQ-2

```http
POST /api/hardware/mq2
{"sensorId":"MQ2-04","value":720}
```

현재 임계값:

- 0~349: normal
- 350~649: warning
- 650~1023: danger

이 값은 실물 센서 보정 후 `state_manager.py`의 `MQ2_WARNING`, `MQ2_DANGER`에서 변경합니다.

## Batch

```http
POST /api/hardware/batch
{
  "flame":{"FLM-01":false,"FLM-07":true},
  "mq2":{"MQ2-01":120,"MQ2-04":720},
  "shutters":{"SH-01":false}
}
```

하드웨어 API를 받으면 Dashboard는 `REAL` 모드로 자동 전환됩니다.
