# 실제 화재 관제 연결 안내

이 문서는 **장비를 사용할 수 있을 때 진행할 절차**다. 현재 코드는 모의 테스트로 확인했으며, 이 문서 작성 시점에는 실제 GPIO·Arduino·LED 및 운영 DB를 이용한 전체 통합 시험을 완료하지 않았다. 이 프로젝트는 인증된 화재 경보·피난 설비가 아닌 캡스톤 모형이다.

## 먼저 확인할 것

- 기존 SIM 대시보드와 Pi의 `node1` 앱·지도·펌웨어를 통째로 교체하지 않는다. 새 REAL 서비스는 Pi의 `127.0.0.1:5001`에서 별도로 동작한다.
- 기존 `flame_multi_reader.py`, `cloud_flame_reader.py`, `led_fireguard_usb.py --cloud-send`, SIM LED 프로그램 등 같은 GPIO·Arduino 또는 동일 장치 클라우드 상태를 사용하는 프로세스를 **각 실행 터미널에서 종료**한다. 기존 송신기는 새 프로그램의 잠금을 따르지 않으므로 동시에 쓰면 순번이나 상태가 충돌할 수 있다. 어떤 프로세스인지 확인되지 않으면 임의로 종료하지 않는다.
- 제공된 `led_layout_162.json`은 `verified=false`, `mapping_status=needs_verification`이다. 현재 상태에서 **REAL LED 출력은 잠겨 있다.** `verified`나 `mapping_status`를 임의 변경해 잠금을 해제하지 않는다. 실제 162개 논리 인덱스, 163개 Arduino 슬롯, 20번 이후 보정, 교차점과 방향을 실물에서 검증해야 한다.
- 센서가 여전히 불을 감지하거나 입력이 오래된 상태면 해당 센서의 화재 해제는 거부된다. 화재가 여러 개면 각 센서를 별도로 선택할 수 있다. GPIO 논리 상태 수신만으로 배선 단선이나 센서 물리 고장을 판정할 수는 없다.

## 서버 준비

운영 DB에 적용하기 전 별도 시험 DB에서 아래 SQL의 순서와 기존 마이그레이션 적용 상태를 확인한다. 이 파일들은 실제 관제 상태를 직접 지우지 않는다.

1. `supabase/migrations/202611100003_real_clear_queue.sql`: Pi가 처리할 REAL 해제 명령 큐와 권한 설정.
2. `supabase/migrations/202611100005_v2_preserve_restored_latch.sql`: 센서 단절 시 기존 화재 또는 Pi가 복원한 화재를 보존하는 수신 함수.

두 SQL은 격리 PostgreSQL 테스트를 통과했지만 실제 운영 Supabase 적용 여부와 환경은 별도로 확인해야 한다.

Vercel **Production**의 기존 `FIREGUARD_DEVICE_TOKEN`은 Pi 송신·명령 수신용이다. 웹 관리자 해제 기능은 기본 꺼져 있으며, 준비 후에만 `FIREGUARD_REAL_CONTROL_ENABLED=1` 및 **32자 이상의 별도** `FIREGUARD_REAL_OPERATOR_TOKEN`을 설정하고 Production 재배포한다. 이 관리자 키는 장치 토큰 및 `FIREGUARD_SIM_OPERATOR_TOKEN`과 달라야 한다. 서로 다른 키를 채팅, 소스코드, 로그에 넣지 않는다.

## Pi 파일 준비

친구 Pi의 `~/FIreGuard`에 최신 Git 코드가 있고, 실제 하드웨어 프로젝트는 `~/Desktop/node1`이라고 가정한다. 이 단계는 Pi가 준비되었을 때만 진행한다. 기존 파일 백업을 남기고 새 REAL 파일과 공용 시리얼 브리지만 복사한다.

```bash
git -C ~/FIreGuard pull --ff-only origin main
mkdir -p ~/Desktop/node1/hardware
cp --backup=numbered ~/FIreGuard/hardware/{real_fire_latch.py,real_pi_service.py,real_device_runtime.py,real_allzone_reporter.py,all_zone_routes.py,real_clear_worker.py,real_flame_reader.py,real_sensor_outbox.py,cloud_sim_led.py,cloud_sim_bridge.py} ~/Desktop/node1/hardware/
```

`node1`에는 최신 `hardware/cloud_telemetry.py`, `hardware/flame_multi_reader.py`, `hardware/led_routes.py`, `hardware/led_junctions.py`, `hardware/led_layout_162.json`, `pi_led_usb.py`, `route_service.py`와 `.venv`가 이미 있어야 한다. 파일 버전·11센서 매핑이 다르면 먼저 확인하고 중단한다. 기존 SIM 시스템과 호환성은 실물에서 검증되지 않았다.

## Pi 실행 순서 — LED 출력 없이 REAL 수신부터 시험

아래는 **같은 터미널 세션**에서 수행한다. 이 절차는 준비 전용이며 LED를 켜지 않는다. REAL 서비스에 필요한 로컬 토큰은 매 실행 때 생성해 자식 프로세스에만 공유한다. 실행 중인 Pi 터미널을 닫으면 관련 프로세스가 종료될 수 있다.

```bash
cd ~/Desktop/node1
mkdir -p runtime
umask 077
read -rs -p '장치 토큰 입력: ' FIREGUARD_DEVICE_TOKEN; echo
export FIREGUARD_DEVICE_TOKEN
export FIREGUARD_REAL_LOCAL_TOKEN="$(openssl rand -hex 32)"
export FIREGUARD_DEVICE_ID=pi-01
export FIREGUARD_TELEMETRY_URL=https://fire-guard-seven.vercel.app/api/hardware/telemetry
```

서버 설정과 기존 REAL 보고를 확인한 뒤, 각 프로그램을 별도 로그로 실행한다. 출력에는 개인정보나 비밀값이 포함될 수 있으므로 공유 전 확인한다.

```bash
.venv/bin/python -m hardware.real_pi_service > runtime/real-service.log 2>&1 &
FG_REAL_SERVICE_PID=$!
```

```bash
.venv/bin/python hardware/real_flame_reader.py --api http://127.0.0.1:5001 > runtime/real-sensors.log 2>&1 &
FG_REAL_READER_PID=$!
```

센서 11개의 입력이 확인될 시간을 준 후 로컬 상태와 사전 점검을 확인한다. 실제 불꽃을 만들지 않고 먼저 정상·연결 상태를 확인한다.

```bash
curl --max-time 3 http://127.0.0.1:5001/api/real/state
.venv/bin/python -m hardware.real_device_runtime --check-only
```

`persistencePending`, 센서별 `connected`와 `rawFlame`, `realFireSensorIds`, 출력 잠금 이유를 확인한다. 재시작 후에는 각 센서의 새 입력을 받기 전까지 연결 미확인이다. `--check-only`는 전송하거나 LED를 켜지 않는다.

센서·지도·기존 송신자 종료를 확인했다면 REAL 상태만 서버에 보내는 모드를 시작한다. `--assert-exclusive-publisher`는 실제 기존 송신자를 중지했다는 현장 확인이 전제다.

```bash
.venv/bin/python -m hardware.real_device_runtime --enable-real-cloud --assert-exclusive-publisher > runtime/real-cloud.log 2>&1 &
FG_REAL_RUNTIME_PID=$!
```

시작 시 마지막 클라우드 REAL 화재를 Pi 저장 상태에 합친다. 이전 실제 보고가 없거나 서버·로컬 상태를 확인할 수 없으면 송신과 LED 출력을 시작하지 않는다. 네트워크 장애를 해결하거나 기존 실제 상태를 확인해야 하며, 임의로 초기화하지 않는다.

관리자 해제 기능의 DB·Vercel 설정이 완료된 경우에만 별도의 해제 워커를 실행한다.

```bash
.venv/bin/python -m hardware.real_clear_worker --cloud-url https://fire-guard-seven.vercel.app --enable-real-clear > runtime/real-clear.log 2>&1 &
FG_REAL_CLEAR_PID=$!
```

각 로그를 확인한다. 실제 상태가 배포 화면에 표시될 때까지 센서 리더와 송신 프로세스가 계속 실행되어야 한다.

```bash
tail -n 30 runtime/real-service.log runtime/real-sensors.log runtime/real-cloud.log runtime/real-clear.log
```

## 실물 검증과 종료

웹의 해제 요청은 Pi가 원시 센서가 정상이고 최신인지 확인한 뒤 처리한다. Pi ACK만으로 화면에서 정상으로 확정하지 않고, 그 이후의 최신 REAL 보고도 확인한다. 연결이 끊겼거나 처리 결과가 불명확하면 관리자가 실제 상태를 확인해야 한다. 처리 중 Pi가 중단된 명령은 자동 재실행하지 않는다.

실제 LED를 켜려면 Pi·Arduino 연결과 실물 맵 검증을 별도로 마치고, **GPIO 감지 → 래치 → 복수 화재 경로 → Arduino FLOW/STOP → UI 보고 → 선택 해제**를 현장에서 검증해야 한다. REAL LED 출력 옵션은 검증된 배치 파일이 없는 현재 환경에서 사용하지 않는다. Arduino `OK`는 명령 응답일 뿐 실제 발광 확인이 아니다.

현장 매핑 검증을 완료한 후에만, 앞에서 실행한 LED 없는 런타임을 종료하고 같은 터미널에서 다음을 실행한다. 포트는 Arduino가 실제 연결된 포트로 확인한다.

```bash
kill "$FG_REAL_RUNTIME_PID"
.venv/bin/python -m hardware.real_device_runtime --enable-real-cloud --assert-exclusive-publisher --enable-verified-led --port /dev/ttyACM0 > runtime/real-cloud.log 2>&1 &
FG_REAL_RUNTIME_PID=$!
```

매핑이 검증되지 않았거나 센서 입력·화재 저장이 확인되지 않으면 LED 출력이 거부된다. 스위치나 메타데이터만 변경하여 검증을 대신하지 않는다.

실제 화재 시 전체 구역에서 출구까지의 계획을 계산한다. 일부 구역이 차단되면 `partial`과 경로 없는 노드가 표시되며, 모든 구역의 대피가 보장되는 것은 아니다. 지도 파란 경로는 계산 계획이고 녹색·빨간 점은 Arduino가 명령을 승인한 LED의 추정 위치다. FLOW의 단일 전역 애니메이션이 갈림길별 방향을 정확히 나타내는지 실물 확인이 필요하다.

이 터미널에서 위 PID 변수가 설정된 경우, 관련 프로세스를 각각 종료할 수 있다. 실제 장비 상태를 확인한 뒤 필요한 프로세스만 종료한다.

```bash
kill "$FG_REAL_CLEAR_PID" "$FG_REAL_RUNTIME_PID" "$FG_REAL_READER_PID" "$FG_REAL_SERVICE_PID"
```

모든 명령이 성공했다고 가정하지 말고 각 로그와 화면을 확인한다. 시뮬레이션 전용 LED 프로그램은 실제 센서 감시를 대신하지 않는다.
