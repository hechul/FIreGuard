#!/usr/bin/env bash
# FireGuard REAL monitoring launcher for the existing Raspberry Pi project.
# Default: no physical LED output. Do not change the verified-map gate.
set -u

cd "$(dirname "$0")/.." || exit 1
FG_PYTHON=.venv/bin/python
FG_CLOUD_URL=https://fire-guard-seven.vercel.app
FG_LED_PORT=
if [[ ${1:-} == '--verified-led' && $# -eq 2 ]]; then
  FG_LED_PORT=$2
elif [[ $# -ne 0 ]]; then
  echo '사용법: bash hardware/start_real_monitor.sh [--verified-led /dev/ttyACM0]'
  exit 2
fi

for FG_FILE in "$FG_PYTHON" hardware/config.py hardware/real_pi_service.py \
  hardware/real_flame_reader.py hardware/real_sensor_outbox.py \
  hardware/real_device_runtime.py hardware/real_clear_worker.py \
  hardware/real_allzone_reporter.py hardware/all_zone_routes.py \
  hardware/cloud_telemetry.py hardware/led_routes.py hardware/led_junctions.py \
  hardware/led_layout_162.json pi_led_usb.py static/data/floorplan.json; do
  if [[ ! -f $FG_FILE ]]; then echo "필수 파일 없음: $FG_FILE"; exit 1; fi
done
if [[ ! -x $FG_PYTHON ]]; then echo 'Pi 가상환경 Python을 실행할 수 없습니다.'; exit 1; fi
if ! command -v openssl >/dev/null || ! command -v curl >/dev/null; then
  echo 'openssl 및 curl이 필요합니다.'; exit 1
fi
FG_RUNNING=$(ps -eo pid=,args= | grep -E '[p]ython[^ ]* .*hardware[./](flame_multi_reader|real_flame_reader|cloud_flame_reader|led_fireguard_usb|cloud_sim_led|cloud_sim_bridge|real_device_runtime|real_clear_worker|real_pi_service)(\.py| |$)' || true)
if [[ -n $FG_RUNNING ]]; then
  echo '기존 센서·LED·클라우드 프로세스가 실행 중입니다. 확인 후 해당 터미널에서 종료하세요:'
  printf '%s\n' "$FG_RUNNING"
  exit 1
fi
if curl -fsS --max-time 2 http://127.0.0.1:5001/api/real/state >/dev/null 2>&1; then
  echo '포트 5001에서 기존 REAL 서비스가 응답 중입니다. 중복 실행을 중단합니다.'; exit 1
fi
if ! curl -fsS --connect-timeout 5 --max-time 10 "$FG_CLOUD_URL/api/health" >/dev/null; then
  echo '배포 서버에 연결할 수 없습니다. 인터넷 연결을 확인하세요.'; exit 1
fi
if [[ -n $FG_LED_PORT ]]; then
  if [[ ! -e $FG_LED_PORT ]]; then echo "Arduino 포트를 찾지 못했습니다: $FG_LED_PORT"; exit 1; fi
  if ! "$FG_PYTHON" -c 'import json; x=json.load(open("hardware/led_layout_162.json")); assert x.get("verified") is True and x.get("mapping_status") == "confirmed"'; then
    echo '실물 LED 매핑이 검증되지 않아 실제 LED 출력을 시작할 수 없습니다.'; exit 1
  fi
fi

mkdir -p runtime
umask 077
read -r -s -p 'Vercel 장치 토큰 입력: ' FIREGUARD_DEVICE_TOKEN; echo
if [[ ${#FIREGUARD_DEVICE_TOKEN} -lt 32 ]]; then echo '장치 토큰을 확인하세요.'; exit 1; fi
export FIREGUARD_DEVICE_TOKEN
export FIREGUARD_REAL_LOCAL_TOKEN="$(openssl rand -hex 32)"
export FIREGUARD_DEVICE_ID=pi-01
export FIREGUARD_TELEMETRY_URL="$FG_CLOUD_URL/api/hardware/telemetry"
FG_PIDS=()
FG_RUNTIME=
cleanup() {
  # Stop the LED owner while its local state service is still available.
  # Its SIGTERM handler sends Arduino STOP before releasing the serial port.
  if [[ -n $FG_RUNTIME ]] && kill -0 "$FG_RUNTIME" 2>/dev/null; then
    kill "$FG_RUNTIME" 2>/dev/null || true
    for FG_WAIT in {1..40}; do
      kill -0 "$FG_RUNTIME" 2>/dev/null || break
      sleep 0.25
    done
    if kill -0 "$FG_RUNTIME" 2>/dev/null; then
      echo 'LED 프로그램 종료 응답이 없습니다. Arduino와 LED 상태를 직접 확인하세요.'
      kill -KILL "$FG_RUNTIME" 2>/dev/null || true
    fi
    wait "$FG_RUNTIME" 2>/dev/null || true
  fi
  if (( ${#FG_PIDS[@]} )); then
    for FG_PID in "${FG_PIDS[@]}"; do
      [[ $FG_PID == "$FG_RUNTIME" ]] && continue
      kill "$FG_PID" 2>/dev/null || true
    done
    for FG_PID in "${FG_PIDS[@]}"; do
      [[ $FG_PID == "$FG_RUNTIME" ]] && continue
      wait "$FG_PID" 2>/dev/null || true
    done
  fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM

"$FG_PYTHON" -u -m hardware.real_pi_service >runtime/real-service.log 2>&1 &
FG_SERVICE=$!; FG_PIDS+=("$FG_SERVICE")
for FG_ATTEMPT in {1..20}; do
  if curl -fsS --max-time 1 http://127.0.0.1:5001/api/real/state >/dev/null 2>&1; then break; fi
  if ! kill -0 "$FG_SERVICE" 2>/dev/null; then echo '로컬 관제 서버 시작 실패'; tail -n 20 runtime/real-service.log; exit 1; fi
  sleep 0.5
done
if ! curl -fsS --max-time 1 http://127.0.0.1:5001/api/real/state >/dev/null 2>&1; then
  echo '로컬 관제 서버에 연결할 수 없습니다.'; exit 1
fi
"$FG_PYTHON" -u hardware/real_flame_reader.py --api http://127.0.0.1:5001 >runtime/real-sensors.log 2>&1 &
FG_READER=$!; FG_PIDS+=("$FG_READER")
echo '센서 입력 확인 중...'
for FG_ATTEMPT in {1..30}; do
  if ! kill -0 "$FG_READER" 2>/dev/null; then echo '센서 프로그램 시작 실패'; tail -n 20 runtime/real-sensors.log; exit 1; fi
  if curl -fsS --max-time 1 http://127.0.0.1:5001/api/real/state | "$FG_PYTHON" -c 'import json,sys; x=json.load(sys.stdin); sys.exit(0 if x.get("ledSafetyReady") is True else 1)' 2>/dev/null; then break; fi
  sleep 0.5
done
if ! curl -fsS --max-time 1 http://127.0.0.1:5001/api/real/state | "$FG_PYTHON" -c 'import json,sys; x=json.load(sys.stdin); sys.exit(0 if x.get("ledSafetyReady") is True else 1)' 2>/dev/null; then
  echo '센서 전체 입력 또는 화재 상태 저장을 확인하지 못했습니다.'; tail -n 20 runtime/real-sensors.log; exit 1
fi

FG_RUNTIME_OPTIONS=(--enable-real-cloud --assert-exclusive-publisher)
if [[ -n $FG_LED_PORT ]]; then FG_RUNTIME_OPTIONS+=(--enable-verified-led --port "$FG_LED_PORT"); fi
"$FG_PYTHON" -u -m hardware.real_device_runtime "${FG_RUNTIME_OPTIONS[@]}" >runtime/real-cloud.log 2>&1 &
FG_RUNTIME=$!; FG_PIDS+=("$FG_RUNTIME")
"$FG_PYTHON" -u -m hardware.real_clear_worker --cloud-url "$FG_CLOUD_URL" --enable-real-clear >runtime/real-clear.log 2>&1 &
FG_CLEAR=$!; FG_PIDS+=("$FG_CLEAR")
echo '클라우드 첫 보고를 확인 중입니다...'
for FG_ATTEMPT in {1..60}; do
  if ! kill -0 "$FG_RUNTIME" 2>/dev/null; then
    echo '클라우드 송신 시작 실패:'; tail -n 20 runtime/real-cloud.log; exit 1
  fi
  if grep -q '\[CLOUD\] 전송 성공' runtime/real-cloud.log; then break; fi
  sleep 0.5
done
if ! grep -q '\[CLOUD\] 전송 성공' runtime/real-cloud.log; then
  echo '클라우드 첫 보고를 확인하지 못했습니다:'; tail -n 20 runtime/real-cloud.log; exit 1
fi
echo '클라우드 첫 보고 완료. 이 창을 열어 두세요. 종료: Ctrl+C'
if grep -q '실제 화재 해제 연결 확인 필요' runtime/real-clear.log; then
  echo '관리자 해제 연결은 아직 확인되지 않았습니다. Vercel 설정 및 runtime/real-clear.log를 확인하세요.'
fi
echo '로그: runtime/real-service.log, real-sensors.log, real-cloud.log, real-clear.log'
if [[ -z $FG_LED_PORT ]]; then echo '현재 실물 LED는 제어하지 않습니다.'; fi
FG_CLOUD_STATUS=ok
FG_CLEAR_WARNING=0
while true; do
  for FG_PID in "${FG_PIDS[@]}"; do
    if ! kill -0 "$FG_PID" 2>/dev/null; then
      echo '프로그램이 중단되었습니다. 원인을 확인하세요:'
      tail -n 12 runtime/real-service.log runtime/real-sensors.log runtime/real-cloud.log runtime/real-clear.log
      exit 1
    fi
  done
  FG_LAST_CLOUD=$(grep -E '\[CLOUD\] 전송 성공|\[REAL CLOUD\] 전송 실패' runtime/real-cloud.log | tail -n 1 || true)
  if [[ $FG_LAST_CLOUD == *'전송 실패'* && $FG_CLOUD_STATUS != error ]]; then
    echo '클라우드 전송 실패: 배포 UI가 최신 상태가 아닐 수 있습니다. runtime/real-cloud.log 확인.'
    FG_CLOUD_STATUS=error
  elif [[ $FG_LAST_CLOUD == *'전송 성공'* && $FG_CLOUD_STATUS == error ]]; then
    echo '클라우드 전송이 복구되었습니다.'
    FG_CLOUD_STATUS=ok
  fi
  if [[ $FG_CLEAR_WARNING == 0 ]] && grep -q '실제 화재 해제 연결 확인 필요' runtime/real-clear.log; then
    echo '관리자 해제 연결 오류: Vercel 설정과 runtime/real-clear.log를 확인하세요.'
    FG_CLEAR_WARNING=1
  fi
  sleep 2
done
