"""Versioned hardware telemetry validation and disposable dashboard projections.

No cloud request relies on a previous Python process's memory.
"""
from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from route_service import FloorGraph
from state_manager import SimulationState

CONFIG = json.loads((Path(__file__).parent / 'config/cloud_sensors.json').read_text(encoding='utf-8'))
MAPPING_VERSION = CONFIG['mappingVersion']


def cloud_floorplan(floorplan):
    result = deepcopy(floorplan)
    result['sensors'] = deepcopy(CONFIG['sensors'])
    result['mappingVersion'] = MAPPING_VERSION
    return result


def timestamp(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError('observedAt은 timezone이 있는 ISO 날짜여야 합니다.')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('observedAt에 timezone이 필요합니다.')
    return parsed.astimezone(timezone.utc)


def validate_telemetry(data, floorplan, device_id, now=None):
    now = now or datetime.now(timezone.utc)
    if not isinstance(data, dict):
        raise ValueError('JSON 객체가 필요합니다.')
    allowed = {'deviceId', 'bootId', 'sequence', 'observedAt', 'mappingVersion', 'flame', 'startNode', 'route', 'led'}
    if set(data) - allowed:
        raise ValueError('지원하지 않는 필드가 있습니다.')
    if data.get('deviceId') != device_id:
        raise ValueError('등록되지 않은 deviceId입니다.')
    try:
        boot_id = str(UUID(data.get('bootId', '')))
    except (ValueError, TypeError, AttributeError):
        raise ValueError('bootId는 프로그램 시작 시 한 번 생성한 UUID여야 합니다.') from None
    sequence = data.get('sequence')
    if type(sequence) is not int or not 0 <= sequence <= 9007199254740991:
        raise ValueError('sequence는 0 이상의 안전한 정수여야 합니다.')
    observed = timestamp(data.get('observedAt'))
    age = (now - observed).total_seconds()
    if not -60 <= age <= 300:
        raise ValueError('observedAt이 현재 시각과 맞지 않습니다. Pi 시간을 동기화하세요.')
    if data.get('mappingVersion') != MAPPING_VERSION:
        raise ValueError('mappingVersion이 서버와 다릅니다.')
    sensors = {s['id']: s for s in floorplan['sensors']}
    flame = data.get('flame')
    if not isinstance(flame, dict) or set(flame) != set(sensors) or any(type(v) is not bool for v in flame.values()):
        raise ValueError('flame에 등록 센서 11개 전체의 boolean 상태가 필요합니다.')
    graph = FloorGraph(floorplan)
    start = data.get('startNode', 'N33')
    if not isinstance(start, str) or start not in graph.nodes:
        raise ValueError('알 수 없는 startNode입니다.')
    blocked = {sensors[sid]['node'] for sid, active in flame.items() if active}
    route = data.get('route')
    normalized_route = None
    if route is not None:
        if not isinstance(route, dict):
            raise ValueError('route는 객체 또는 null이어야 합니다.')
        rid = route.get('id')
        nodes, edges = route.get('nodes'), route.get('edges')
        if not isinstance(rid, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,80}', rid):
            raise ValueError('route.id 형식이 잘못되었습니다.')
        if (not isinstance(nodes, list) or not nodes or len(nodes) > 200
                or not all(isinstance(n, str) for n in nodes)
                or len(set(nodes)) != len(nodes) or nodes[0] != start
                or not isinstance(edges, list) or len(edges) != len(nodes) - 1
                or not all(isinstance(e, str) for e in edges)):
            raise ValueError('route의 노드/간선 연결이 잘못되었습니다.')
        destination = route.get('destinationId', route.get('exitId'))
        if not isinstance(destination, str) or destination != nodes[-1] or destination not in {*graph.exits, *graph.fallbacks}:
            raise ValueError('route의 목적지가 잘못되었습니다.')
        if any(n not in graph.adjacency or n in blocked for n in nodes):
            raise ValueError('route가 위험 노드 또는 알 수 없는 노드를 통과합니다.')
        cost = 0.0
        for i, eid in enumerate(edges):
            edge = graph.edges.get(eid)
            if not edge or {edge['from'], edge['to']} != {nodes[i], nodes[i+1]}:
                raise ValueError('route의 간선이 노드와 연결되지 않습니다.')
            cost += float(edge['weight'])
        supplied_cost = route.get('cost', cost)
        if type(supplied_cost) not in (int, float) or not math.isfinite(supplied_cost) or not math.isclose(supplied_cost, cost, rel_tol=1e-6, abs_tol=1e-6):
            raise ValueError('route 비용이 지도와 다릅니다.')
        fallback = graph.fallbacks.get(destination)
        normalized_route = {'id': rid, 'nodes': nodes[:], 'edges': edges[:], 'cost': cost,
                            'destinationId': destination, 'exitId': destination,
                            'routeMode': 'fallback' if fallback else 'exit',
                            'destinationType': fallback.get('type', 'fallback') if fallback else 'exit'}
    led = data.get('led', {'status': 'unknown'})
    if not isinstance(led, dict) or led.get('status') not in ('unknown', 'applied', 'error'):
        raise ValueError('led.status는 unknown/applied/error 중 하나여야 합니다.')
    route_id = led.get('routeId')
    if route_id is not None and (not isinstance(route_id, str) or len(route_id) > 80):
        raise ValueError('led.routeId 형식이 잘못되었습니다.')
    if led['status'] == 'applied' and (not normalized_route or route_id != normalized_route['id']):
        raise ValueError('LED 적용 완료에는 동일 routeId의 Pi 경로 보고가 필요합니다.')
    segments = led.get('segments', [])
    if not isinstance(segments, list) or len(segments) > 15:
        raise ValueError('LED 구간은 최대 15개입니다.')
    seen = set()
    clean_segments = []
    for segment in segments:
        if not isinstance(segment, dict):
            raise ValueError('LED 구간 형식이 잘못되었습니다.')
        sid = segment.get('id')
        color = segment.get('color')
        if (not isinstance(sid, str) or not re.fullmatch(r'S(?:[1-9]|1[0-5])', sid)
                or sid in seen or type(segment.get('on')) is not bool
                or not isinstance(color, str) or not re.fullmatch(r'#[0-9A-Fa-f]{6}', color)):
            raise ValueError('LED 구간 ID/색상/상태가 잘못되었습니다.')
        seen.add(sid)
        clean_segments.append({'id': sid, 'on': segment['on'], 'color': color.lower()})
    error = led.get('error')
    if error is not None and (not isinstance(error, str) or len(error) > 256):
        raise ValueError('LED 오류 설명은 256자 이하여야 합니다.')
    return {'deviceId': device_id, 'bootId': boot_id, 'sequence': sequence,
            'observedAt': observed.isoformat(), 'mappingVersion': MAPPING_VERSION,
            'flame': deepcopy(flame), 'startNode': start, 'route': normalized_route,
            'led': {'status': led['status'], 'routeId': route_id, 'segments': clean_segments, 'error': error}}


def project_state(floorplan, row, events, device_id, stale_seconds=15, now=None, preview_start=None):
    now = now or datetime.now(timezone.utc)
    telemetry = row['telemetry'] if row else None
    received = row['received_at'] if row else None
    stale = not row or max((now - timestamp(received)).total_seconds(),
                           (now - timestamp(row['observed_at'])).total_seconds()) > stale_seconds
    model = SimulationState(floorplan)
    model.set_operation_mode('real')
    model.start_node = preview_start or (telemetry.get('startNode', 'N33') if telemetry else 'N33')
    for sid, value in model.flame_sensors.items():
        value.update(active=bool(telemetry and telemetry['flame'].get(sid)), connected=bool(telemetry),
                     updatedAt=row['observed_at'] if row else None)
    model._recompute()
    source = 'server_preview' if telemetry else 'none'
    if telemetry and telemetry.get('route') and preview_start is None:
        model.route = telemetry['route']
        source = 'pi'
    result = model.snapshot()
    result['updatedAt'] = received
    result['connections'] = {'pi': bool(row) and not stale, 'server': True}
    result['failSafeActive'] = False  # Do not infer physical fail-safe operation from cloud silence.
    if not row:
        result['overallStatus'] = 'unknown'
        result['route'] = None
        result['routeMode'] = 'none'
        result['selectedExitName'] = result['selectedDestinationName'] = None
    for value in result['flameSensors'].values():
        value['connected'] = bool(row) and not stale
    result['sensorCounts']['offline'] = len(model.flame_sensors) if stale else 0
    result['shutters'] = {sid: {'closed': False, 'connected': False, 'updatedAt': None} for sid in model.shutters}
    equipment = []
    for sensor in floorplan['sensors']:
        active = result['flameSensors'][sensor['id']]['active']
        equipment.append({'id': sensor['id'], 'category': '센서', 'name': sensor['name'],
                          'location': sensor['node'], 'value': ('1' if active else '0') if row else '-',
                          'status': 'offline' if stale else 'danger' if active else 'normal',
                          'stateLabel': '마지막 수신값 · 통신 끊김' if stale and row else '미수신' if not row else '화재 감지' if active else '정상',
                          'lastSeen': row['observed_at'] if row else None})
    result['equipment'] = equipment
    result['events'] = [{'timestamp': e['observed_at'], 'type': e['type'],
                         'location': e.get('payload', {}).get('sensorId', device_id),
                         'change': {'FIRE': '화재 감지', 'CLEAR': '화재 해제', 'LED': 'LED 출력 보고'}.get(e['type'], e['type']),
                         'result': json.dumps(e.get('payload', {}), ensure_ascii=False)} for e in events]
    result['cloud'] = {'enabled': True, 'deviceId': device_id, 'hasTelemetry': bool(row), 'stale': stale,
                       'receivedAt': received, 'observedAt': row['observed_at'] if row else None,
                       'sequence': row['sequence'] if row else None, 'mappingVersion': MAPPING_VERSION,
                       'routeSource': source, 'led': deepcopy(telemetry.get('led') or {'status': 'unknown', 'segments': []}) if telemetry else {'status': 'unknown', 'segments': []}}
    return result
