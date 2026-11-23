/* Reconstruct the latest incident from the event ledger, in recorded order.
   A sensor reading or latest heartbeat is not a dated incident event. */
(() => {
  const clock = new Intl.DateTimeFormat('ko-KR', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  });

  function sensorIds(event, sensors) {
    const ids = String(event.location + ' ' + event.change).match(/FLM-\d+/g);
    if (ids?.length) return [...new Set(ids)];
    const node = String(event.location).split(' / ')[0];
    return sensors.filter(s => s.node === node).map(s => s.id);
  }

  function incidentRows(state, plan) {
    const sensors = plan?.sensors || [];
    const active = new Set(Object.keys(state.flameSensors || {}).filter(id => state.flameSensors[id].active));
    const rows = [];
    let inIncident = active.size > 0;
    for (const event of state.events || []) {
      if (['MODE', 'RESET', 'SYSTEM'].includes(event.type)) break;
      if (!event.timestamp || Number.isNaN(Date.parse(event.timestamp))) continue;
      const fire = event.type === 'FIRE', clear = event.type === 'CLEAR';
      if (fire || clear) {
        const ids = sensorIds(event, sensors);
        // Local controls can repeat a clear on a sensor that was already idle.
        // Without an earlier matching FIRE, that click cannot start an incident.
        if (!inIncident && clear && !state.cloud?.enabled) {
          const earlier = state.events.slice(state.events.indexOf(event) + 1);
          const previous = earlier.find(item => ['MODE','RESET','SYSTEM'].includes(item.type) ||
            (['FIRE','CLEAR'].includes(item.type) && sensorIds(item, sensors).some(id => ids.includes(id))));
          if (previous?.type !== 'FIRE') continue;
        }
        if (!ids.length) continue;
        inIncident = true;
        const sites = [...new Set(ids.map(id => {
          const node = sensors.find(sensor => sensor.id === id)?.node;
          return plan?.nodes?.find(n => n.id === node)?.name || node || id;
        }))];
        rows.push({event, kind: fire ? 'fire' : 'clear', time:event.timestamp,
          title: sites.join(', ') + (fire ? ' 화재 감지' : ' 경보 해제'),
          detail: state.cloud?.enabled ? ids.join(' · ') : event.result || ids.join(' · ')});
        for (const id of ids) {
          if (clear) active.add(id);
          else active.delete(id);
        }
        if (fire && !active.size) break;
      } else if (inIncident && (event.type === 'LED' || event.type === 'ROUTE')) {
        rows.push({event, kind: event.type.toLowerCase(), time:event.timestamp,
          title: event.type === 'LED' ? 'LED 출력 보고' : '경로 계산 보고',
          detail: event.type === 'LED' ? event.location : event.result});
      }
    }
    return rows.reverse();
  }

  function render(state, plan) {
    const target = document.getElementById('incidentTimeline');
    const rows = incidentRows(state, plan);
    const eventMap = window.FireGuardEventMap;
    const key = JSON.stringify(rows.map(row => [row, eventMap?.canSelect(row.event), eventMap?.isSelected(row.event)]));
    if (target.dataset.timeline === key) return;
    target.dataset.timeline = key;
    target.replaceChildren();
    if (!rows.length) {
      const empty = document.createElement('p');
      empty.className = 'timeline-empty';
      empty.textContent = '수신된 화재 대응 기록이 없습니다.';
      target.append(empty);
      return;
    }
    for (const row of rows) {
      const selectable = eventMap?.canSelect(row.event);
      const item = document.createElement(selectable ? 'button' : 'div');
      if (selectable) {
        item.type = 'button';
        item.title = '지도에서 위치 보기';
        item.setAttribute('aria-pressed', String(eventMap.isSelected(row.event)));
        item.addEventListener('click', () => eventMap.select(row.event));
      }
      item.className = 'incident-step';
      item.dataset.kind = row.kind;
      const time = document.createElement('time');
      time.className = 'timeline-time';
      time.dateTime = row.time;
      time.title = new Date(row.time).toLocaleString('ko-KR');
      time.textContent = clock.format(new Date(row.time));
      const title = document.createElement('strong');
      title.className = 'timeline-title';
      title.textContent = row.title;
      const detail = document.createElement('small');
      detail.className = 'timeline-detail';
      detail.textContent = row.detail || '';
      item.append(time, title, detail);
      target.append(item);
    }
  }
  window.FireGuardTimeline = {render};
})();
