# N4 미점등 수정 — 2026-11-18

기준 main: `681148c156f9a3d583fe0a5cfbf38bcd107c0bba`. 이 변경은 로컬 소프트웨어 검증을 완료했다. GitHub 반영과 별도로 서버 배포 revision 확인 및 Pi 적용·실물 시험이 필요하다.

후속 수정은 `9191bc0` 적용 후 보고된 매점/화장실/65–66/20번 현상을 대상으로 한다. 후속 수정의 push/서버 배포/Pi 적용은 별도 단계다.

## 실제 Pi 자료

사용자 제공 `C:\Users\socce\Downloads\node1.7z`의 필요한 Python/JSON 파일을 `tmp/pi-source/node1`에 추출해 사용했다. 원본과 Pi 의존 파일은 수정하지 않았다. 별도 `FireGuard_node1_JSON_공유.zip`은 `tmp/pi-json`에 추출했다.

두 압축의 레이아웃과 도면은 각각 SHA-256이 동일하다.

- layout: `9cf039f8e5e6f36e73a0bfeb06b1bbd0d1553e9e6ce72c4b2c01db06e3b8070b`
- floorplan: `325741909869d6454757664460c3da8b0b02b646714a4ce0575b1cd87001fada`
- `all_zone_preview.json`은 FLM-01 예시이므로 N4 실측 로그로 취급하지 않았다.

## 변경 결과

번호는 1-based 논리 번호다. 실물 표기와 raw 슬롯은 현장에서 구분해야 한다.

| 구간 | N4 단독 화재 계산 결과 |
|---|---|
| 39–40 | E02 추가 분기: N33→N10→동측 출구, LED 41→38 |
| 5–7 | E39: N7→EXIT_S2, LED 8→5 |
| 30–36 | E01 추가 분기: N23→N20→북서 출구, LED 29→36 |
| 20 | 기존 E10 안내에 포함. 전송 슬롯은 19 |
| 120–123 | 매표소 N40→N14, LED 123→120 |
| 65–66 | E09 추가 안내: N7→서측 출구. N7 화재 때는 계속 차단 |
| 팝콘 매장 129–140 | N19→N15→N27→N25를 거쳐 출구 안내 |
| N4 빨강 | 109–113, 총 5개 |

시연 옵션 `--lab-guide-led`에서 센서별 중심 ±2개를 빨강으로 표시한다. Pi 수기 앵커를 우선하며 없으면 경로 안내와 동일한 `anchor_for_node` 보간을 사용한다. N8은 잘못된 좌표 중심 54번 대신 경로 앵커 59번을 사용하므로 빨강이 57–61번이다. 구간 끝에서는 다른 가지로 넘어가지 않으므로 3–4개일 수 있다. 일반/verified 모드는 기존 빨간 범위를 유지한다.

시연 모드에서는 수기/보간 LED 번호와 불일치하는 화면 좌표의 20px 이격 검사를 적용하지 않는다. 명시된 빨간 LED와 화재 노드, 수동 폐쇄를 기준으로 경로를 차단한다. 이는 시연 표현 변경이지 실제 안전 이격거리의 측정/승인이 아니다. 일반/verified 모드는 기존 이격 검사를 유지한다. N4+N9에서는 매표소 안내가 계속 차단된다.

기존 한 노드당 한 방향의 경로 트리는 유지한다. E01/E02/E09의 미사용 통로는 별도 `coverageEdges`로 보고하며 출구 도달, 전체 경로의 무순환, LED 반대 방향 충돌을 검사한다. 추가 안내 때문에 기존 23–28 및 42–43 등의 안내가 사라지지 않도록 검사했다.

7+9 화재에서는 N28→N5(화장실1), N29→N6(화장실2)가 모두 안내된다. 7+8+9 화재에서는 N13→N35→N28→N5가 유지되고 N8을 통과하지 않는다. 반대편에서 N6에 접근 가능한 구역은 별도로 화장실2 안내를 유지한다.

7번 화재 시 E10 전체 경로는 차단하지만, 빨강 이후의 복도 부분에서 N3를 거쳐 실제 출구에 도달할 수 있으면 `partialEdges`로 해당 부분만 안내한다. 7+9 및 7+8+9 조합은 논리 11→22번이며 논리 20번(raw 19)을 포함한다. N3 화재나 E10 수동 폐쇄 때는 이 안내도 금지한다. 전체 E10을 지나는 경로 또는 화살표로 표시하지 않는다.

Arduino 저장 한도를 넘을 때만 여러 SEG에 중복된 교차점 끝점을 줄인다. 내부 픽셀이나 마지막 남은 픽셀은 제거하지 않는다.

S2 출구 위치 `(107.07, 590)`와 간선 가중치 `0.5`는 도면 표시/시연용 추정값이다. 실제 안전거리 측정값이 아니다. raw 슬롯 20 건너뛰기는 변경하지 않았다.

## 새 버전과 호환성

- 센서: `flame11-5cce6a933e`
- Pi 지도: `graph-690e1a64b5`
- LED: `led162-usb163-shift20-4a635eec44`

서버는 새 지도/LED 쌍을 허용하면서 기존 장치 버전도 유지한다. 웹은 S2 출구, 추가 분기 및 새 버전의 5관 위치를 표시한다. 기존 Supabase RPC는 hardware JSON을 저장하므로 이번 변경에 DB migration은 추가하지 않았다. 실제 운영 DB/배포 상태는 이번 작업에서 확인하지 않았다.

## 검증

- 실제 Pi 파일과 매표소/5관/S2 오버레이로 11개 센서의 2,047개 비어 있지 않은 화재 조합 통과.
- 후속 수정도 위 2,047조합을 다시 통과했다. N4 팝콘, 두 화장실, N8 앵커, 65–66, N7 반대쪽 복도의 20번 및 수동 폐쇄/N3 화재 시 부분 안내 금지를 명시적으로 검사했다.
- 빨강 합산, 화재 노드 차단, 순환/방향 충돌, GUIDE 직렬화, 40개 SEG/163개 저장 한도, 전체 LED 보존, 서버 텔레메트리 검증 포함.
- 새 출구/추가 분기의 웹 투영, 복도 중복 방지, 기존 도면 테스트 통과.
- 서버 계약 45개, 시뮬레이션 7개, 전체 구역 서버 7개 테스트 통과. 추가 분기 거부 조건 4개, 빨강 단위 5개, 직렬화 단위 2개도 통과.
- 전체 Windows 실행은 221개 중 202개 통과, 9개 skip, 10개 환경 오류(fcntl 미지원 8개, bash 실행 파일 없음 2개). 별도 추가한 직렬화 2개는 따로 통과했다. 전체 Linux 테스트 완료를 뜻하지 않는다.
- 실제 GPIO, 시리얼, 광학적 점등 및 이동 방향은 현장 검증 전이다. 테스트의 ACK는 합성 데이터다.

재현:

```bash
FIREGUARD_PI_PROJECT=/path/to/node1 python -m unittest discover -s tests -p pi_compact_mapping_test.py -v
python tools/inspect_n4_leds.py --pi-project /path/to/node1
```

Windows에서 순수 GUIDE 함수만 운영 코드 AST에서 분리해 테스트하므로 Linux 잠금/장치 동작을 모의 통과로 처리하지 않는다.

## 적용 순서 — 커밋/서버 배포 이후에 실행

1. 변경을 커밋하고 GitHub main에 반영한다.
2. Vercel의 `/api/health` revision이 해당 커밋인지 확인한다. 새 지도 허용이 서버에 반영되기 전에는 Pi를 업데이트하지 않는다.
3. Pi의 실행 터미널에서 Ctrl+C로 기존 모니터를 종료한 후 아래 5개 파일을 함께 복사한다.

```bash
git -C ~/FIreGuard pull --ff-only origin main
cp --backup=numbered ~/FIreGuard/hardware/{all_zone_routes.py,real_device_runtime.py,real_pi_service.py,real_ticket_overlay.py,real_allzone_reporter.py} ~/Desktop/node1/hardware/
cd ~/Desktop/node1
bash hardware/start_real_monitor.sh --lab-guide-led /dev/ttyACM0
```

원본 `led_routes.py`, `led_junctions.py`, `led_layout_162.json`, `cloud_telemetry.py`, `pi_led_usb.py`, 원본 도면은 덮어쓰지 않는다. N4 단독/복수 화재와 수동 해제 후 현장 LED 방향을 확인한다. 논리 20번은 raw 19와 대응하며 raw 20은 예약 슬롯이다.
