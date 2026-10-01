# FireGuard 영화관 통합 관제 UI v4

영화관 2층 피난도를 디지털 트윈 배경으로 사용하고, Flask + Flask-SocketIO + Dijkstra 기반으로 화재/연기/방화셔터 상태와 대피 경로를 실시간 표시하는 캡스톤 시연용 프로젝트입니다.

## v4 핵심 변경

- 목업 디자인에 맞춘 다크 관제 대시보드 전면 재설계
- 영화관 평면도를 발표용 도면(Schematic) 스타일로 재설계하고 Node / Edge / Exit / Sensor 오버레이
- MQ-2 **5개** 반영
  - MQ2-01 팝콘팩토리 N15
  - MQ2-02 중앙복도 N5
  - MQ2-03 매표소 N1
  - MQ2-04 4관 앞 N9
  - MQ2-05 동측 비상구 앞 N3
- 지도 Node 직접 클릭 → 화재 발생/해제/출발 위치 설정
- Quick Scenario + Auto Demo
- REAL / SIMULATION 모드 분리
- 장비 관리 / Routing / Event Log / QR Mobile 화면
- 방화셔터 및 일반 Edge 수동 차단
- 외부 서버 단절 시 `LOCAL FAIL-SAFE` 상태 표시
- 브라우저 ↔ Flask Socket.IO 단절 시 polling fallback
- 실제 Raspberry Pi 연동을 위한 `/api/hardware/*` REST API 추가
- Windows에서 Flask 미설치 문제를 줄이기 위한 `setup_and_run.bat` 제공

## 가장 쉬운 실행 방법

### 처음 한 번

`setup_and_run.bat` 더블클릭

가상환경을 만들고 필요한 패키지를 설치한 뒤 자동으로 브라우저를 엽니다.

### 이후 실행

`start_dashboard.bat` 더블클릭

또는 PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

접속 주소:

```text
http://127.0.0.1:5000
```

## 발표용 시연 순서

1. SIMULATION / 정상 상태 확인
2. `동측출구 화재` 클릭
3. N3가 위험 Node로 차단되고 다른 Exit로 Dijkstra 재계산되는지 확인
4. `서버 단절` 클릭
5. `LOCAL FAIL-SAFE` 표시 확인
6. `서버 복구` 클릭
7. Events 화면에서 전체 이벤트 순서 확인

또는 Dashboard의 `AUTO DEMO`를 누르면 자동으로 진행합니다.

## 실제 Raspberry Pi 연동 API

### Flame

```http
POST /api/hardware/flame
Content-Type: application/json

{"sensorId":"FLM-07","active":true}
```

### MQ-2

```http
POST /api/hardware/mq2
Content-Type: application/json

{"sensorId":"MQ2-04","value":731}
```

### 여러 센서 한 번에

```http
POST /api/hardware/batch
Content-Type: application/json

{
  "flame":{"FLM-07":true},
  "mq2":{"MQ2-04":731,"MQ2-02":120},
  "shutters":{"SH-01":false}
}
```

하드웨어 API가 들어오면 운영 모드는 자동으로 `REAL`로 변경됩니다.

## 파일 구조

```text
FireGuard_Cinema_UI_v4/
├─ app.py
├─ state_manager.py
├─ route_service.py
├─ requirements.txt
├─ setup_and_run.bat
├─ start_dashboard.bat
├─ templates/
│  ├─ dashboard.html
│  └─ mobile.html
├─ static/
│  ├─ css/dashboard.css
│  ├─ js/dashboard.js
│  ├─ data/floorplan.json
│  └─ images/
│     ├─ cinema_floorplan.png
│     └─ qr_n1.png
└─ docs/
   └─ UI_REFERENCE.png
```

## 주의

현재 `Supabase` 표시는 실제 Supabase SDK 연결 상태가 아니라 **외부 관제/DB 통신 링크를 시뮬레이션하는 상태값**입니다. 실제 Supabase 저장은 프로젝트 키와 스키마가 확정된 뒤 별도 연결하면 됩니다.


## v4 UI 재설계

- 기존 사진형 영화관 맵을 대시보드 내부의 **도면형 SVG 평면도**로 교체
- 메인 상태 `SAFE / FIRE / LOCAL FAIL-SAFE`를 대형 배너로 표시
- 중앙 Digital Twin 영역 확대
- 센서 수치를 크게 표시: Flame **15개**, MQ-2 **5개**
- Quick Demo를 발표용 5개 버튼으로 단순화
- 영화관 Node 클릭 시 화재 발생/해제/출발 위치 지정
- 화면 전체 글자와 카드 크기를 확대해 프로젝터 발표 가독성 개선
- Flask/Socket.IO/Dijkstra/하드웨어 API 구조는 v3 그대로 유지
