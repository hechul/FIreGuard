# FireGuard — Vercel + Supabase 배포

클라우드에서는 Pi 보고를 저장하고 실시간 표시합니다. 배포 화면은 REAL 관제 전용이며 시뮬레이션·지도 편집·장비 제어 API는 잠겨 있습니다. 기존 로컬 실행은 기존 시연 동작과 센서 설정을 유지합니다. **클라우드 매핑은 최신 하드웨어 설정인 FLM-01~11입니다.**

클라우드 매핑의 코드 기준은 `config/cloud_sensors.json`입니다. DB의 `sensors`는 같은 매핑의 메타데이터 사본이며, 현재 서버는 시작할 때 DB에서 매핑을 덮어 읽지 않습니다. 배치를 바꿀 때는 버전을 올리고 설정 파일·SQL 매핑·Pi 설정을 함께 변경합니다. Supabase Table Editor에서 센서 행만 바꾸면 서버 지도에는 반영되지 않습니다.

## 1. Supabase 준비

1. Supabase 프로젝트를 생성합니다.
2. SQL Editor에서 `supabase/migrations/202610300001_cloud.sql` 내용을 실행합니다.
3. `sensors`, `device_state`, `events` 세 테이블과 `ingest_telemetry` 함수가 생성됐는지 확인합니다.
4. `sensors`에는 `flame-20261030-v1` 매핑 11개가 있어야 합니다. `device_state`는 첫 보고 전까지 비어 있는 것이 정상입니다.
5. SQL은 `device_state`와 `events`를 Realtime publication에 추가합니다.

이 구성은 **공개 캡스톤 관제 화면**을 전제로 합니다. 공개 키 사용자는 센서 설정·현재 보고·이벤트를 읽을 수 있고 쓰기와 수신 RPC는 서버용 키에만 허용됩니다. 따라서 장치 토큰·개인정보·비밀 데이터는 telemetry나 이벤트에 넣지 않습니다. 비공개 화면이 필요하면 로그인과 사용자별 RLS 정책을 추가한 후 공개합니다.

## 2. 환경변수

`.env.example`을 참고해 로컬 `.env` 또는 Vercel 프로젝트 환경변수에 설정합니다. 비밀 키는 채팅·Git·브라우저 코드에 넣지 않습니다.

| 이름 | 위치/용도 |
|---|---|
| `FIREGUARD_CLOUD=1` | 로컬에서 클라우드 모드 테스트. Vercel 배포에서는 자동 활성화 |
| `SUPABASE_URL` | 프로젝트 URL |
| `SUPABASE_ANON_KEY` | 브라우저 공개 키. publishable 또는 legacy anon |
| `SUPABASE_SERVICE_ROLE_KEY` | 서버 전용 키. secret 또는 legacy service_role |
| `FIREGUARD_DEVICE_TOKEN` | 서버·Pi 공유 장치 토큰. 최소 32자 |
| `FIREGUARD_DEVICE_ID=pi-01` | 수신을 허용할 Pi 식별자 |
| `FIREGUARD_STALE_SECONDS=15` | 새 보고가 없으면 오래된 상태로 표시할 시간 |

장치 토큰 생성 예시:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

발급한 값을 로컬 `.env`, Vercel, Pi에 각각 설정합니다. `SUPABASE_SERVICE_ROLE_KEY`와 `FIREGUARD_DEVICE_TOKEN`은 `NEXT_PUBLIC_` 같은 브라우저 노출용 변수로 만들지 않습니다. UI에 전달되는 키는 `SUPABASE_ANON_KEY`뿐입니다.

## 3. 로컬에서 먼저 확인

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
```

`.env`에 `FIREGUARD_CLOUD=1`과 프로젝트 환경변수를 넣은 상태에서 실행합니다. 브라우저로 `http://127.0.0.1:8080`을 열면 첫 보고 전에는 장비 상태 확인 대기로 보여야 합니다. DB 연결을 준비하지 않았다면 설정 오류가 표시되며 정상 장비 상태로 보이지 않습니다.

## 4. Vercel 배포

1. Git 저장소를 Vercel에 연결하고 프로젝트 루트를 이 폴더로 지정합니다.
2. Flask 자동 인식으로 `app.py`를 배포합니다. 별도 프런트엔드 재작성은 필요하지 않습니다.
3. 위 환경변수를 배포 환경에 등록하고 배포합니다. Git 변경이 반영된 브랜치를 선택합니다.
4. Vercel Deployment Protection을 사용 중이면 Pi가 API에 접근할 수 있도록 운영 배포의 보호 설정을 확인합니다. 장치 토큰 인증은 계속 유지합니다.
5. 배포 주소의 `/api/cloud/config`, `/api/state`, `/api/floorplan`과 정적 JS/CSS가 응답하는지 확인합니다.

`vercel.json`의 빌드 명령은 `static/`을 생성물 `public/static/`으로 복사합니다. 템플릿의 기존 `/static/...` URL을 유지하면서 Vercel CDN이 파일을 제공합니다. Python 함수에는 템플릿·지도·설정 파일이 포함됩니다. `cloudflared.exe`는 함수 패키지에서 제외합니다. 생성물 `public/`과 `.vercel/`은 Git에서 제외합니다.

서버는 Supabase REST API를 사용해 요청마다 최신 상태를 읽습니다. 프로세스 메모리를 클라우드의 최신 상태 저장소로 사용하지 않습니다. UI의 실시간 변경 알림은 Supabase Realtime이 담당하고, 재연결 시 최신 상태를 다시 읽습니다. 주기적 조회도 유지해 통신 단절과 오래된 보고를 표시합니다.

## 5. Pi 없이 샘플 전송

`tools/send_telemetry.py`는 GPIO에 접근하지 않는 **가짜 장치 전송 도구**입니다. 전송 내용은 REAL 화면과 이력에 반영되므로 별도 테스트 프로젝트/장치에서 사용합니다. 운영 중인 Pi와 같은 deviceId로 동시에 전송하지 않습니다.

먼저 전송 없이 본문만 확인합니다.

```bash
.venv/bin/python tools/send_telemetry.py --api https://YOUR_APP.vercel.app --active FLM-08 --dry-run
```

다음 명령은 `.env` 또는 환경변수의 장치 토큰을 사용해 실제 API에 샘플 화재를 전송합니다.

```bash
.venv/bin/python tools/send_telemetry.py --api https://YOUR_APP.vercel.app --active FLM-08 --repeat 5 --count 3
```

정상 복귀는 `--active` 없이 전송합니다.

```bash
.venv/bin/python tools/send_telemetry.py --api https://YOUR_APP.vercel.app
```

각 명령 실행은 새 bootId를 만듭니다. 프로세스 안에서는 같은 bootId와 증가하는 sequence를 사용합니다. 계속 보고하지 않으면 기본 15초 후 UI는 수신 지연/연결 끊김을 표시합니다. LED 기본값은 `unknown`이므로 센서가 감지됐다는 이유로 적용 완료가 표시되지 않습니다.

Pi 경로/LED 결과 샘플을 보내려면 실제 지도에 맞는 경로 JSON을 `--route-file`, 구간 배열 JSON을 `--led-segments-file`로 제공할 수 있습니다. `--led-status applied`는 경로 파일을 필수로 요구합니다. 샘플 전송은 실제 LED를 켜지 않습니다.

## 6. 검증 기준

- FLM-08 보고 → DB `device_state` 갱신 → N8 강조 → 이벤트 표시
- 정상 복귀 보고 → 강조 해제와 CLEAR 이벤트
- LED 결과 없음 → 미확인. 올바른 경로와 applied 보고 → Pi 출력 적용 완료
- 같은 bootId·sequence 재전송 → 상태/이벤트 중복 없음
- 오래된 순번이나 시각 → 최신 상태 유지
- 마지막 보고 후 제한 시간 경과 → 오래된 상태 표시. 센서 정상으로 추정하지 않음
- 브라우저 새로고침/재연결 → DB에서 최신 상태 복구
- 인증 없는 쓰기·시뮬레이션·지도 편집 → 거부
- 2D와 3D 센서 위치·경로가 같은 상태를 표시

LED 실물 구간과 3D 선분의 대응은 아직 확정하지 않았습니다. 이 단계에서는 보고된 S1~S15를 텍스트로 표시하며 3D LED는 중립색입니다. 하드웨어 담당자와 대응표를 확정한 뒤 구간별 색 표시를 연결합니다.

## 하드웨어 담당자 전달물

`docs/HARDWARE_CLOUD_API.md`, 배포 주소, 공유 장치 토큰을 별도 안전한 경로로 전달합니다. GPIO 수집 코드 수정·Pi의 로컬 경로 계산·LED 제어·장비 자동 시작은 하드웨어 담당 영역입니다. 본 배포는 서버가 원격 LED 명령을 내리는 기능을 포함하지 않습니다.

## 공식 문서

- [Vercel Flask 배포 및 public 정적 파일](https://vercel.com/docs/frameworks/backend/flask)
- [Supabase Postgres Changes](https://supabase.com/docs/guides/realtime/postgres-changes)
- [Supabase RLS](https://supabase.com/docs/guides/database/postgres/row-level-security)
