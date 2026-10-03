# FireGuard Scenario Lab 시나리오 카탈로그 v5.4

> 발표/예외상황 검증용 시나리오 목록. 모든 시나리오는 SIMULATION 모드에서 실행한다.

| 분류 | Scenario ID | 화면 표시 | 핵심 동작 |
|---|---|---|---|
| 기본 | `normal` | 정상 | 전체 초기화, 기본 최단경로 복원 |
| 감지 | `smoke_warning` | 연기 주의 | MQ2-02 = 450, WARNING만 표시 |
| 감지 | `smoke_danger` | 연기 위험 | MQ2-05 = 760, N3 위험 Node 차단 |
| 화재 | `east_exit_fire` | 동측 출구 화재 | N3 통합 화재 |
| 화재 | `ticket_fire` | 매표소 화재 | N14 통합 화재 |
| 화재 | `cinema4_fire` | 4관 화재 | N9 통합 화재 |
| 화재 | `large_fire` | 복합 대형화재 | N3 + N7 동시 화재 |
| 시설 | `east_shutter` | 방화셔터 | SH-02 CLOSED → E02 차단 |
| 경로 | `mid_route_block` | 이동 중 통로 폐쇄 | 현재 기본 경로의 E02 수동 차단 |
| 인파 | `crowd_congestion` | 인파 혼잡 | E02/E03 가중치 증가 → 혼잡 우회 |
| Fallback | `fallback_toilet` | 화장실 대피 | 정규 EXIT 4곳 모두 진입 차단 |
| Fallback | `fallback_descender` | 완강기 대피 | EXIT + 화장실 접근 차단 |
| 한계 | `no_route` | 경로 없음 | EXIT + 화장실 + 완강기 접근 전부 차단 |
| 통신 | `server_off` | 서버 단절 | 외부 서버만 OFF, Local Fail-safe 유지 |
| 통신 | `fire_server_off` | 화재 + 서버 단절 | N3 화재 + 외부 서버 OFF |
| 장비 | `pi_off` | Pi 제어기 단절 | 현장 제어기 OFF, LED/센서 현장 기능 확인 필요 |
| 장비 | `sensor_fault` | 센서 통신 장애 | FLM-15 + MQ2-05 OFFLINE |
| 복구 | `server_on` | 서버 복구 | 외부 서버 링크 복구 |
| 복구 | `pi_on` | Pi 복구 | Raspberry Pi 연결 복구 |
| 복구 | `sensor_recover` | 센서 복구 | FLM-15 + MQ2-05 연결 복구 |

## 발표 때 특히 좋은 6개

1. `east_exit_fire` — 화재 위치 회피
2. `mid_route_block` — 이미 선택한 최단경로가 나중에 막히는 예외
3. `crowd_congestion` — 막히지 않아도 혼잡 가중치로 우회
4. `fire_server_off` — 화재 중 서버 단절에도 Local Fail-safe
5. `fallback_toilet` → `fallback_descender` — 정규 출구 실패 후 단계적 보조 대피
6. `no_route` — 시스템이 무리하게 존재하지 않는 경로를 만들지 않음

## 상태 해석

- **SAFE**: 정상
- **WARNING**: MQ-2 주의
- **FIRE DETECTED**: Flame 또는 MQ-2 Danger
- **CONGESTION REROUTE**: 동적 Edge 가중치 기반 혼잡 우회
- **SENSOR DEGRADED**: 일부 센서 통신 단절
- **LOCAL FAIL-SAFE**: 외부 서버 단절, Raspberry Pi 로컬 제어 유지
- **EDGE CONTROLLER OFFLINE**: Raspberry Pi 자체 단절
- **EMERGENCY ROUTE**: 정규 EXIT 실패 후 화장실/완강기 Fallback
- **NO SAFE ROUTE**: 정규/Fallback 모두 불가능
