# 클라우드 시험 요청 수신 점검 (드라이런)

이 브리지는 서버가 시험 요청을 Pi에 전달하는지 점검합니다. 실물 LED 제어, 로컬 시뮬레이션 변경, 실제 화재 보고는 하지 않습니다. 실제 화재를 독립적으로 감시하고 중단할 수 있는지 검증되기 전까지 실물 자동 시험은 잠겨 있습니다.

Pi 프로젝트 루트에 `hardware/cloud_sim_bridge.py`를 복사하고 로컬 Flask가 실행 중이며 SIMULATION 모드인지 확인합니다. 장치 토큰은 친구 본인의 Pi 터미널에서 입력합니다. 입력값은 화면에 표시되지 않습니다.

```bash
read -rs -p '장치 토큰 입력: ' FIREGUARD_DEVICE_TOKEN; echo
export FIREGUARD_DEVICE_TOKEN
python3 hardware/cloud_sim_bridge.py --cloud-url https://fire-guard-seven.vercel.app --dry-run
```

종료는 Ctrl+C입니다. 이 명령은 서버에 시험 명령 API가 설치된 경우에만 동작합니다. 시험 요청은 수신 검증 후 Pi가 계산한 예상 경로를 반환합니다. LED는 제어하지 않습니다. 토큰을 대화나 파일에 공유하지 마세요.

실제 시험을 구현하려면 로컬 실화재 감시가 SIM과 독립적으로 동작하는지, 화재 및 통신 장애 시 실행 중인 Arduino 명령이 즉시 중단되는지, 모드 전환과 명령 간 경합이 없는지 Pi와 Arduino에서 별도로 검증해야 합니다. 여러 프로세스가 같은 시리얼 포트를 동시에 제어해서는 안 됩니다.
