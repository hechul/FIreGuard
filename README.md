# FireGuard 영화관 통합 관제 UI v5

영화관 2층 피난도를 디지털 트윈 배경으로 사용하고, Flask + Flask-SocketIO + Dijkstra 기반으로 화재/연기/방화셔터 상태와 대피 경로를 실시간 표시하는 캡스톤 시연용 프로젝트입니다.

## v5 핵심 변경

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
FireGuard_Cinema_UI_v5/
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


## v5 UI 재설계

- 기존 사진형 영화관 맵을 대시보드 내부의 **도면형 SVG 평면도**로 교체
- 메인 상태 `SAFE / FIRE / LOCAL FAIL-SAFE`를 대형 배너로 표시
- 중앙 Digital Twin 영역 확대
- 센서 수치를 크게 표시: Flame **15개**, MQ-2 **5개**
- Quick Demo를 발표용 5개 버튼으로 단순화
- 영화관 Node 클릭 시 화재 발생/해제/출발 위치 지정
- 화면 전체 글자와 카드 크기를 확대해 프로젝터 발표 가독성 개선
- Flask/Socket.IO/Dijkstra/하드웨어 API 구조는 v3 그대로 유지


## v5 Soft UI Refresh

- 밝은 미니멀 UI로 전면 리스타일링
- Toss식 큰 정보 계층 + 당근식 따뜻한 포인트 + Notion식 중립 카드 구조를 혼합
- 핵심 기능/ID/API/Socket.IO/Dijkstra는 그대로 유지
- 영화관 schematic 도면을 밝은 paper-style로 변경
- QR 모바일 화면도 동일한 디자인 언어로 통일


## v5.1 조정 사항

- 대피 경로 화살표를 **초록색**으로 변경
- 화살표와 경로 선 굵기를 화면 크기에 따라 자동 조정하도록 개선
- 작은 화면에서는 화살표가 작아지고, 넓은 화면에서는 적당히 커지도록 반응형 비율 적용
- 기존 Flask / Socket.IO / Dijkstra 로직은 그대로 유지


## v5.2 조정 사항

- 대피 경로의 **화살표(arrow head) 제거**
- 경로는 초록색 애니메이션 선만 표시
- 경로 선 반응형 두께 조정은 유지


## v5.3 보조 대피 경로

정규 비상구를 가장 먼저 사용하고, 모든 정규 EXIT 경로가 차단된 경우에만
지정된 **보조 대피지점**으로 Dijkstra를 다시 수행합니다.

- `N16`: 서측 화장실 임시 대피지점
- `N17`: 중앙 화장실 임시 대피지점
- `N18`: 4관 좌측 완강기(임시 배치)
- `E21`, `E22`: 화장실 접근 간선
- `E23`: 완강기 접근 간선

Quick Demo:
- `출구 전부 차단 / 화장실 대피`
- `화장실도 차단 / 완강기 대피`

**중요:** 화장실과 완강기 경로는 캡스톤 시뮬레이션용 보조 대피 로직입니다.
실제 건물 적용 시 화장실의 방화·방연 성능, 피난구획, 완강기 설치 위치/사용 조건,
건물 방재계획 및 소방안전 검토를 기준으로 허용 지점을 확정해야 합니다.


## v5.4 Scenario Lab

예외상황 시연을 위해 시나리오 제어를 확장했습니다.

- MQ-2 주의 / 위험 임계값
- 매표소/4관/동측 출구 화재
- 복합 대형화재
- 방화셔터 및 이동 중 통로 폐쇄
- 인파 혼잡에 따른 동적 Edge 가중치 우회
- 정규 출구 → 화장실 → 완강기 → NO SAFE ROUTE 단계
- 서버 단절 / 화재 중 서버 단절
- Raspberry Pi 현장 제어기 단절
- 특정 센서 통신 장애

자세한 목록은 `SCENARIO_CATALOG.md` 참고.


## v5.4.1 화장실 위치 수정

폼보드 제작도 기준 좌표를 584 × 858 SVG 도면 비율로 환산해 화장실 표시를 수정했습니다.

- 제작도 화장실 1: `(180, 475)`, `80 × 75 mm`
  - SVG 표시: 약 `(175, 453)`, `78 × 72`
  - Fallback Node `N16`: `(214, 489)`
- 제작도 화장실 2: `(265, 475)`, `80 × 75 mm`
  - SVG 표시: 약 `(258, 453)`, `78 × 72`
  - Fallback Node `N17`: `(297, 489)`

기존 Dijkstra/Fallback 로직은 변경하지 않고 화면 배치만 실제 제작도에 더 가깝게 정렬했습니다.


## v5.4.2 화장실 픽토그램 위치 수정

- 기존 복도/매표소 쪽에 잘못 표시되던 `🚻` 아이콘 2개 제거
- `화장실 1`, `화장실 2` 박스 내부 상단 중앙에 각각 배치
- 화장실 명칭과 `Toilet` 텍스트는 아이콘 아래로 정렬
- N16/N17 Fallback Node 및 Dijkstra 로직은 변경 없음


## v5.4.3 Visual Map Editor

왼쪽 메뉴의 `QR / 모바일` 아래에 **맵 편집(Map Editor)** 메뉴를 추가했습니다.

### Node 이동
- `Node 이동` 모드 선택
- Node 원 또는 EXIT 사각형을 드래그
- 좌측 도면 위에서 위치를 눈으로 맞출 수 있음
- 오른쪽 Inspector에서 X/Y 숫자로도 직접 입력 가능

### Edge 이동
- `Edge 이동` 모드 선택
- Edge 선을 드래그
- Edge 자체는 독립 좌표가 없으므로 FROM/TO 두 Node를 같은 거리만큼 같이 이동
- 연결 관계, Weight, Dijkstra 로직은 변경하지 않음

### 편의 기능
- 5px Grid Snap ON/OFF
- 실행 취소
- 저장값 다시 불러오기
- 현재 선택 항목 Inspector
- 저장 전 `UNSAVED`, 저장 후 `SAVED` 표시

### 저장
`저장` 버튼을 누르면 `/api/floorplan/layout`을 통해
`static/data/floorplan.json`의 Node/Exit 좌표에 영구 반영합니다.

Cloudflare로 사이트를 공개한 상태에서도 편집 페이지가 노출되므로,
외부 공유 중에는 임의 사용자가 좌표를 저장하지 않도록 주의하세요.
