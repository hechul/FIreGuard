# 실제 모형 LED 테스트 — S1~S15 / 155개

2026-10-26 사용자 확인: 데이터는 S1 → S2 → … → S15. 전원 보강 위치는 S9에서 **S10으로 변경**.
LRS-100-5 한 대가 S1과 S10의 +5V/GND에 공급한다. 전원 위치 변경은 LED 인덱스를 바꾸지 않는다.
이 코드는 Raspberry Pi 4와 Raspberry Pi OS용 단독 점등 시험이다. 대시보드 자동 경로 연동은 아직 아니다.

## 1. 전원을 끈 상태에서 배선 확인

LRS AC 입력은 접지·단자 덮개·코드 고정을 완료한 상태여야 한다. 아래는 DC/GPIO 배선만 설명한다.
Pi는 USB-C 어댑터로 별도 공급한다. LED 전원의 +5V를 Pi 5V 핀에 연결하지 않는다.

보유한 SparkFun TXS0108E를 이용한 짧은 배선 시험:

| 연결점 | 대상 |
|---|---|
| Pi 3.3V (물리 1번) | TXS VA와 OE |
| Pi BCM18 (물리 12번) | TXS A1 |
| LRS +V | TXS VB, S1 +5V, S10 +5V |
| LRS -V | TXS GND, Pi GND(물리 6번), S1 GND, S10 GND |
| TXS B1 | 330Ω 저항 → S1 DIN |

TXS의 두 GND 핀은 공통 접지로 연결한다. OE는 VA(3.3V)에 연결하며, 5V 또는 GND에 연결하지 않는다.
핀헤더는 납땜해야 한다. GPIO18이 다른 용도로 사용 중인지 실제 배선도 확인한다.
저항은 S1 DIN 가까이에 둔다. 제어기에서 첫 LED까지 데이터선은 짧게 하고 GND를 함께 배선한다.
TXS0108E는 배선의 정전용량에 민감하다. 시험 가능 구성이지만 장거리 NeoPixel 신호의 안정성을 보장하지 않는다.
불규칙한 깜빡임이 있으면 전원/접합/데이터선을 확인하고 74AHCT125 기반 단방향 버퍼 사용을 검토한다.
74AHCT125로 바꾸면 OE 극성이 다르므로 이 표를 그대로 사용하지 않는다.

구간 사이: +5V→+5V, GND→GND, DOUT→다음 DIN. S15 DOUT 미연결.
S10의 전원 보강은 +5V/GND에만 추가한다. S9 DOUT→S10 DIN은 그대로 유지한다.
S10은 4개 구간이지만 전원 주입 접합부에는 다른 LED 구간의 전류도 흐른다.
기존 가는 전선·커넥터·22AWG 연결부의 부담이 전원 보강만으로 자동 해결되지는 않는다.
155개 × 60mA를 보수적으로 계산하면 9.3A이다. 실제 소비량은 제품·색·밝기에 따라 다르다.
이 테스트의 낮은 밝기는 과전류 보호나 최대 밝기에서의 배선 검증을 대신하지 않는다.

## 2. 파일을 Pi로 복사

`led_demo_test.py`, `led_segments.json`, 이 안내서를 Pi의 같은 폴더(예: `~/fireguard-led`)로 복사한다.
다음 명령은 Windows가 아닌 **라즈베리파이 터미널**에서 실행한다.

```bash
cd ~/fireguard-led
sudo apt update
sudo apt install python3-venv
python3 -m venv .venv-led --system-site-packages
.venv-led/bin/python -m pip install rpi_ws281x adafruit-blinka adafruit-circuitpython-neopixel
```

GPIO18의 PWM과 내장 오디오 충돌을 피하기 위해 OS 설정을 확인한다.
최근 OS는 `/boot/firmware/config.txt`, 구버전은 `/boot/config.txt`이다.
사용 중인 파일을 백업한 뒤 `sudo nano`로 열어 `dtparam=audio=on`을 `dtparam=audio=off`로 바꾸고 재부팅한다.
해당 설정은 내장 오디오 사용에 영향을 준다. 임의로 두 파일을 모두 수정하지 않는다.
다른 LED 제어 프로그램은 종료하고 한 프로그램만 GPIO18을 사용하게 한다.

## 3. 테스트 순서

기본 밝기 5%, 최대 허용 10%. 종료 시 전체 소등을 시도한다. 실제 발광 여부는 눈으로 확인한다.

### 첫 LED 색상 확인

```bash
sudo .venv-led/bin/python led_demo_test.py first
```

첫 LED 하나만 빨강 → 초록 → 파랑으로 각 2초 점등한다.
색이 바뀌어 보이면 배선에 손대기 전 `--order RGB`로 색 순서 설정을 시험한다.

### 155개가 연결된 순서 확인

```bash
sudo .venv-led/bin/python led_demo_test.py scan --limit 155 --delay 0.2
```

한 번에 한 개씩 약 31초간 순서대로 켠다. S1부터 S15까지 이어지는지 확인한다.
중간부터 꺼지면 그 직전 구간의 DOUT 접합과 다음 DIN, 전원부터 확인한다.

### S1~S15를 한 구간씩 확인

```bash
sudo .venv-led/bin/python led_demo_test.py segments --hold 2
```

터미널에 표시된 S번호와 실제 점등 구간이 맞아야 한다.

### 특정 구간 색상 및 방향

```bash
sudo .venv-led/bin/python led_demo_test.py segment --segment S10 --color red --hold 5
sudo .venv-led/bin/python led_demo_test.py chase --segment S3
sudo .venv-led/bin/python led_demo_test.py chase --segment S3 --reverse
```

기본 chase는 그 구간 DIN에서 DOUT 순서, reverse는 반대 점등 순서다. 데이터 배선 방향은 바꾸지 않는다.

### 구간 일부를 포함한 수동 경로 시험

```bash
sudo .venv-led/bin/python led_demo_test.py path --path "S3:0:4,-S2,-S1" --cycles 3
```

위는 **문법 예시이며 확인된 실제 탈출 경로가 아니다**. 교차점과 방향을 확인한 뒤 값을 정한다.
`S3:0:4` = S3의 DIN 기준 지역 인덱스 0~4 (끝 포함), `-S2` = S2 역순, `S2` = S2 정순.
`S3:4:0`처럼 부분 구간의 역순도 가능하다. 하나의 LED를 중복 지정하는 경로는 거부한다.
S2/S3/S9/S14처럼 긴 스트립의 중간에서 길이 갈라지는 곳은 소프트웨어상 부분 범위로 나눠야 한다.

### 강제 소등 명령

```bash
sudo .venv-led/bin/python led_demo_test.py off
```

Ctrl+C도 소등을 시도한다. 강제 종료·신호 단절·전원 문제에서는 소등을 보장하지 않는다.
전송 프레임은 원래 구매한 300개 분량으로 잡아 남는 슬롯도 OFF로 보낸다. 실제 점등 대상은 155개이다.
사진에서 실제 픽셀 수를 자동 추정한 것이 아니라 사용자가 센 구간별 개수를 사용한다.

## 인덱스

| 구간 | 개수 | 코드 인덱스(0부터) |
|---|---:|---|
| S1 | 4 | 0~3 |
| S2 | 25 | 4~28 |
| S3 | 30 | 29~58 |
| S4 | 4 | 59~62 |
| S5 | 4 | 63~66 |
| S6 | 4 | 67~70 |
| S7 | 4 | 71~74 |
| S8 | 14 | 75~88 |
| S9 | 23 | 89~111 |
| S10 | 4 | 112~115 |
| S11 | 5 | 116~120 |
| S12 | 7 | 121~127 |
| S13 | 5 | 128~132 |
| S14 | 18 | 133~150 |
| S15 | 4 | 151~154 |

## FireGuard 연동 가능 범위

현재 서버 `route_service.py`의 경로 결과에는 nodes/edges/exitId가 있다.
이를 실제 LED 인덱스 범위와 방향에 대응시키면 선택 경로 초록 표시, 방향 이동, 위험 구간 빨강 표시가 가능하다.
배선 순서가 탈출 방향과 같을 필요는 없다. 한 프레임에 각 LED의 색을 따로 보낼 수 있다.
추가로 필요한 것은 실제 교차점의 지역 LED 인덱스, 각 구간의 정방향이 향하는 위치, 웹 그래프와 모형의 대응표다.
긴 스트립 하나를 여러 논리 구간으로 나눌 수 있으므로 다시 자를 필요는 없다.
이번 파일은 하드웨어 시험 도구이며 센서와 자동 연동하거나 안전한 경로를 계산하지 않는다.

## 참고 자료

- https://learn.adafruit.com/neopixels-on-raspberry-pi/python-usage
- https://learn.adafruit.com/neopixels-on-raspberry-pi/raspberry-pi-wiring
- https://learn.sparkfun.com/tutorials/level-shifter---8-channel-txs0108e-hookup-guide/all?print=1
- https://learn.sparkfun.com/tutorials/level-shifter---8-channel-txs0108e-hookup-guide/troubleshooting
- https://www.ti.com/product/TXS0108E

로컬에서는 모의 픽셀로 인덱스/역방향/오류 시 소등을 검증하며, 실제 Pi 점등 검증은 별도 진행해야 한다.
