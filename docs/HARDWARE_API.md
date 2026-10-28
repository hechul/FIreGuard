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
{"sensorId":"FLM-15","active":true}
```

## Batch

```http
POST /api/hardware/batch
{
  "flame":{"FLM-14":false,"FLM-15":true},
  "shutters":{"SH-01":false}
}
```

하드웨어 API는 실제 센서 상태만 갱신하며, Dashboard에서 선택한 모드를 자동으로 바꾸지 않습니다.

## 실제 센서 시연 후 시뮬레이션 시연

1. Dashboard의 REAL 버튼으로 실제 센서 관제를 선택합니다.
2. 실제 센서 감지와 정상 복귀를 확인합니다. 불꽃이 사라져도 라즈베리파이는 정상값과 heartbeat를 계속 전송합니다.
3. SIMULATION 버튼을 누르고 예외 상황 시나리오를 실행합니다.
4. 실제 센서가 계속 데이터를 보내도 시뮬레이션의 경로, 화재, 셔터 상태와 이벤트는 유지됩니다.
5. 실제 화재가 다시 감지되면 기존 실제 화재 알림이 표시됩니다. 사용자가 REAL 전환을 선택해야 관제 모드가 바뀝니다.

라즈베리파이 센서 수집 프로그램에서는 `/api/hardware/*`만 호출합니다. 반복 수집 루프에서 `/api/mode`로 REAL을 강제 선택하지 마세요.
이전에 사용하던 서버가 입력마다 REAL로 전환한다면 최신 서버로 교체하고 재시작해야 합니다.

실제 센서 상태와 시뮬레이션 상태는 별도로 보관합니다. 시뮬레이션 초기화는 실제 센서의 경보를 지우지 않습니다.

## 센서 구성 변경 (2026-10-28)

현재 프로젝트는 불꽃 센서만 사용합니다. MQ-2 개별 API는 제거됐으며, batch에 `mq2`를 보내면 상태 변경 없이 HTTP 400을 반환합니다. 라즈베리파이 수집 코드에서도 MQ-2 읽기와 전송을 제거하세요.
