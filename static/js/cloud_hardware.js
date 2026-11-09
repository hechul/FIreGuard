/* Display a Pi's plans separately from acknowledged Arduino commands. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.FireGuardHardwareDisplay = factory();
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const visibleList = (values, offset = 0) => {
    if (!Array.isArray(values)) return '미보고';
    if (!values.length) return '없음';
    const shown = values.slice(0, 30).map(value => value + offset).join(', ');
    return `${shown}${values.length > 30 ? ` 외 ${values.length - 30}개` : ''} (${values.length}개)`;
  };

  function describe(hardware) {
    if (!hardware || typeof hardware !== 'object') return null;
    const plannedRoute = visibleList(hardware.plannedLedLogicalIndices, 1);
    const plannedFire = visibleList(hardware.plannedFireLogicalIndices, 1);
    const ack = hardware.ledCommandAck === true;
    const statusNames = {
      not_running: 'LED 프로그램 미실행', preview: '미리보기', off: '소등 보고',
      active: '경로 출력 명령', disconnected: 'Arduino 연결 끊김', error: 'Arduino 제어 오류',
    };
    const status = statusNames[hardware.ledStatus] || '상태 미확인';
    const acknowledged = ack
      ? `Arduino 마지막 명령 OK · ${status} · 실물 발광은 별도 미확인`
      : `${status} · Arduino 명령 OK 미확인`;
    const applied = ack
      ? `OK 확인 논리 LED(도면 번호) · 경로 ${visibleList(hardware.ledLogicalIndices, 1)} / 화재 ${visibleList(hardware.fireLedLogicalIndices, 1)}. Arduino 전송 슬롯 · 경로 ${visibleList(hardware.ledIndices)} / 화재 ${visibleList(hardware.fireLedIndices)}.`
      : 'Arduino OK로 확인된 LED 명령 없음 · 실제 점등 여부 미확인';
    return {
      status: acknowledged,
      planned: `Pi 계산 계획 논리 LED(도면 번호) · 경로 ${plannedRoute} / 화재 ${plannedFire}.`,
      applied,
      note: '제공된 매핑 기준 N28과 N35는 도면 LED 62번을 공유합니다. 실물 위치·방향은 검증 중입니다.',
    };
  }

  return { describe };
}));
