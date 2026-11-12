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
# Fingerprints from the supplied 2026-11-09 sender and its reference files.
# Do not silently accept a different sensor/graph calibration.
HARDWARE_SENSOR_VERSION = 'flame11-5cce6a933e'
HARDWARE_GRAPH_VERSION = 'graph-7e06ff7ced'
HARDWARE_LED_VERSION = 'led162-usb163-shift20-dfea4ba7d3'
HARDWARE_LED_VERSIONS = {HARDWARE_LED_VERSION, 'led162-usb163-shift20-da2de217fd'}

HARDWARE_FIELDS = {
    'deviceId', 'bootId', 'sequence', 'observedAt', 'mappingVersion',
    'graphMappingVersion', 'ledMappingVersion', 'operationMode', 'startNode',
    'flame', 'blockedNodes', 'blockedEdges', 'routeNodes', 'routeEdges',
    'exitNode', 'destinationNode', 'destinationType', 'routeCost', 'routeMode',
    'routeStatus', 'plannedLedLogicalIndices', 'plannedLedIndices',
    'plannedFireLogicalIndices', 'plannedFireLedIndices', 'ledIndices',
    'ledLogicalIndices', 'fireLedIndices', 'fireLedLogicalIndices', 'ledStatus',
    'ledCommandAck', 'ledError', 'ledMappingError', 'physicalLedCount',
    'arduinoSlotCount', 'arduinoIndexBase', 'source',
}

ALL_ZONE_FIELDS = {'routingMode', 'routeStatus', 'availableExits', 'guidedNodes',
                   'unreachableNodes', 'directedEdges', 'ledExcludedEdges'}


def validate_all_zone(value, graph, blocked_nodes, blocked_edges):
    """Validate a Pi-calculated directed evacuation forest, not LED output."""
    if not isinstance(value, dict) or set(value) not in (ALL_ZONE_FIELDS, ALL_ZONE_FIELDS | {'fallbackDestinations'}):
        raise ValueError('전체 구역 경로 보고 형식이 잘못되었습니다.')
    if value['routingMode'] != 'all_zones_to_exits':
        raise ValueError('전체 구역 경로 모드가 잘못되었습니다.')

    def unique_ids(key, allowed):
        entries = value[key]
        if (not isinstance(entries, list) or len(entries) > len(allowed)
                or any(not isinstance(item, str) or item not in allowed for item in entries)
                or len(set(entries)) != len(entries)):
            raise ValueError(f'전체 구역 {key} 형식이 잘못되었습니다.')
        return set(entries)

    exits = unique_ids('availableExits', graph.exits)
    fallback = unique_ids('fallbackDestinations', graph.fallbacks) if 'fallbackDestinations' in value else set()
    if any(graph.fallbacks[x].get('available', True) is not True or x not in graph.nodes for x in fallback):
        raise ValueError('사용할 수 없는 보조 대피지점입니다.')
    guided = unique_ids('guidedNodes', graph.nodes)
    unreachable = unique_ids('unreachableNodes', graph.nodes)
    excluded = unique_ids('ledExcludedEdges', graph.edges)
    blocked_nodes, blocked_edges = set(blocked_nodes), set(blocked_edges)
    if (guided & unreachable or fallback & (guided | unreachable) or (guided | exits | fallback) & blocked_nodes
            or any(graph.exits[e].get('available', True) is not True for e in exits)):
        raise ValueError('차단된 노드 또는 출구가 전체 구역 경로에 포함되었습니다.')
    expected = 'no_route' if not guided else 'partial' if unreachable else 'ok'
    if value['routeStatus'] != expected:
        raise ValueError('전체 구역 경로 상태가 노드 목록과 일치하지 않습니다.')
    directed = value['directedEdges']
    if not isinstance(directed, list) or len(directed) != len(guided):
        raise ValueError('전체 구역 간선 수가 잘못되었습니다.')
    successor, used_edges = {}, set()
    for item in directed:
        if not isinstance(item, dict) or set(item) != {'edgeId', 'from', 'to', 'exitNode'}:
            raise ValueError('전체 구역 간선 형식이 잘못되었습니다.')
        edge_id, src, dst, dest = (item[k] for k in ('edgeId', 'from', 'to', 'exitNode'))
        if not all(isinstance(x, str) for x in (edge_id, src, dst, dest)):
            raise ValueError('전체 구역 간선 식별자가 잘못되었습니다.')
        edge = graph.edges.get(edge_id)
        if (not edge or src not in guided or src in successor or edge_id in used_edges
                or dst not in graph.adjacency or dst in blocked_nodes or dest not in exits | fallback
                or edge_id in blocked_edges or edge_id in excluded
                or {edge['from'], edge['to']} != {src, dst}):
            raise ValueError('전체 구역 간선 연결이 잘못되었습니다.')
        successor[src] = (dst, dest)
        used_edges.add(edge_id)
    if set(successor) != guided:
        raise ValueError('전체 구역 출발점과 간선이 일치하지 않습니다.')
    for start in guided:
        current, visited, exit_id = start, set(), successor[start][1]
        while current not in exits | fallback:
            if current in visited or current not in successor or successor[current][1] != exit_id:
                raise ValueError('전체 구역 경로가 출구에 도달하지 못합니다.')
            visited.add(current)
            current = successor[current][0]
        if current != exit_id:
            raise ValueError('전체 구역 목적지가 일치하지 않습니다.')
    return deepcopy(value)


def validate_hardware_telemetry(data, floorplan, device_id, now=None):
    """Validate the Pi's USB bridge report before canonicalizing it for the DB.

    The extension is whitelisted: stored telemetry is publicly readable. Planned
    LED indices and acknowledged commands remain independent of blocked edges.
    """
    if not isinstance(data, dict) or set(data) not in (HARDWARE_FIELDS, HARDWARE_FIELDS | {'allZone'}):
        raise ValueError('하드웨어 보고 필드가 확정된 규격과 다릅니다.')
    if data['operationMode'] != 'real':
        raise ValueError('시뮬레이션 데이터는 실제 장비 관제에 저장할 수 없습니다.')
    if (data['mappingVersion'] != HARDWARE_SENSOR_VERSION
            or data['graphMappingVersion'] != HARDWARE_GRAPH_VERSION
            or not isinstance(data['ledMappingVersion'], str)
            or data['ledMappingVersion'] not in HARDWARE_LED_VERSIONS):
        raise ValueError('센서, 지도 또는 LED 매핑 버전이 서버와 다릅니다.')
    if (data['source'] != 'raspberry-pi' or type(data['physicalLedCount']) is not int
            or data['physicalLedCount'] != 162 or type(data['arduinoSlotCount']) is not int
            or data['arduinoSlotCount'] != 163 or type(data['arduinoIndexBase']) is not int
            or data['arduinoIndexBase'] != 0):
        raise ValueError('장비 또는 LED 설정이 서버와 다릅니다.')
    sensors = {s['id']: s for s in floorplan['sensors']}
    flame = data['flame']
    if not isinstance(flame, dict) or set(flame) != set(sensors):
        raise ValueError('센서 11개 전체가 필요합니다.')
    for sid, value in flame.items():
        if (not isinstance(value, dict) or set(value) != {'node', 'active', 'connected', 'updatedAt'}
                or value['node'] != sensors[sid]['node'] or type(value['active']) is not bool
                or type(value['connected']) is not bool):
            raise ValueError(f'{sid} 센서 상태 또는 위치가 잘못되었습니다.')
        if value['updatedAt'] is not None:
            timestamp(value['updatedAt'])
    graph = FloorGraph(floorplan)
    for key, valid in (('blockedNodes', graph.adjacency), ('blockedEdges', graph.edges)):
        values = data[key]
        if (not isinstance(values, list) or not all(isinstance(v, str) and v in valid for v in values)
                or len(set(values)) != len(values)):
            raise ValueError(f'{key} 형식이 잘못되었습니다.')
    if any(v['active'] and v['connected'] and v['node'] not in data['blockedNodes'] for v in flame.values()):
        raise ValueError('화재 센서의 노드가 차단 목록에 없습니다.')
    if 'allZone' in data:
        if any(v['active'] and v['node'] not in data['blockedNodes'] for v in flame.values()):
            raise ValueError('마지막 화재 센서 노드가 차단 목록에 없습니다.')
        validate_all_zone(data['allZone'], graph, data['blockedNodes'], data['blockedEdges'])
        if data['startNode'] is not None or data['routeStatus'] != 'no_route':
            raise ValueError('전체 구역 보고에는 단일 출발 경로를 포함할 수 없습니다.')
    status = data['ledStatus']
    if status not in ('not_running', 'preview', 'off', 'active', 'disconnected', 'error') or type(data['ledCommandAck']) is not bool:
        raise ValueError('LED 상태 또는 ACK가 잘못되었습니다.')
    if status == 'active' and not data['ledCommandAck']:
        raise ValueError('LED active는 Arduino 응답 확인이 필요합니다.')
    for key in ('ledError', 'ledMappingError'):
        if data[key] is not None and (not isinstance(data[key], str) or len(data[key]) > 256):
            raise ValueError(f'{key} 형식이 잘못되었습니다.')
    pairs = (('plannedLedLogicalIndices','plannedLedIndices'),
             ('plannedFireLogicalIndices','plannedFireLedIndices'),
             ('ledLogicalIndices','ledIndices'), ('fireLedLogicalIndices','fireLedIndices'))
    for logical, wire in pairs:
        values, slots = data[logical], data[wire]
        if (not isinstance(values, list) or len(values) > 162
                or any(type(i) is not int or not 0 <= i < 162 for i in values)
                or not isinstance(slots, list) or any(type(i) is not int for i in slots)
                or slots != [i if i < 20 else i + 1 for i in values]):
            raise ValueError(f'{logical}와 {wire}의 LED 번호 변환이 잘못되었습니다.')
    if (status != 'active' or not data['ledCommandAck']) and any(data[k] for k in ('ledIndices', 'ledLogicalIndices', 'fireLedIndices', 'fireLedLogicalIndices')):
        raise ValueError('확인되지 않은 LED 출력을 적용 완료로 보고할 수 없습니다.')
    route = None
    if data['routeStatus'] == 'ok':
        nodes, edges = data['routeNodes'], data['routeEdges']
        if not isinstance(nodes, list) or len(nodes) < 2 or not isinstance(edges, list):
            raise ValueError('경로 노드 또는 간선이 잘못되었습니다.')
        dest = data['destinationNode']
        if data['routeMode'] not in ('exit', 'fallback') or (data['routeMode'] == 'exit' and data['exitNode'] != dest) or (data['routeMode'] == 'fallback' and data['exitNode'] is not None):
            raise ValueError('경로 목적지 유형이 잘못되었습니다.')
        if any(e in data['blockedEdges'] for e in edges) or any(n in data['blockedNodes'] for n in nodes):
            raise ValueError('경로가 차단된 노드 또는 간선을 통과합니다.')
        route = {'id': f"pi:{data['sequence']}", 'nodes': nodes, 'edges': edges,
                 'destinationId': dest}
        if data['routeCost'] is not None:
            route['cost'] = data['routeCost']
    elif (data['routeStatus'] != 'no_route' or data['routeNodes'] != [] or data['routeEdges'] != []
          or data['exitNode'] is not None or data['destinationNode'] is not None
          or data['routeCost'] is not None or data['routeMode'] != 'none'):
        raise ValueError('경로 없음 상태와 경로 정보가 일치하지 않습니다.')
    start = data['startNode']
    if start is not None and (not isinstance(start, str) or start not in graph.nodes):
        raise ValueError('알 수 없는 출발 노드입니다.')
    if route and start is None:
        raise ValueError('경로에 출발 노드가 필요합니다.')
    canonical = {'deviceId': data['deviceId'], 'bootId': data['bootId'],
                 'sequence': data['sequence'], 'observedAt': data['observedAt'],
                 'mappingVersion': MAPPING_VERSION,
                 'flame': {sid: value['active'] for sid, value in flame.items()},
                 'startNode': start or 'N33', 'route': route,
                 'led': {'status': 'unknown'}}
    normalized = validate_telemetry(canonical, floorplan, device_id, now)
    if route and (normalized['route']['routeMode'] != data['routeMode']
                  or normalized['route']['destinationType'] != data['destinationType']):
        raise ValueError('경로 목적지의 유형이 지도와 다릅니다.')
    normalized['hardware'] = deepcopy(data)
    return normalized


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
    hardware = telemetry.get('hardware') if telemetry else None
    model.start_node = preview_start or (telemetry.get('startNode', 'N33') if telemetry else 'N33')
    for sid, value in model.flame_sensors.items():
        report = (hardware.get('flame', {}).get(sid, {}) if hardware else {})
        connected = bool(telemetry) and report.get('connected', True) and not stale
        active = bool(telemetry and telemetry['flame'].get(sid))
        value.update(active=active, connected=connected,
                     latched=active and not connected,
                     updatedAt=report.get('updatedAt') or (row['observed_at'] if row else None))
    if hardware:
        model.manual_blocked_edges = set(hardware.get('blockedEdges', []))
    model._recompute()
    source = 'server_preview' if telemetry else 'none'
    if telemetry and preview_start is None and (telemetry.get('route') or hardware):
        model.route = telemetry.get('route')
        source = 'pi'
    result = model.snapshot()
    if hardware and preview_start is None:
        # N33 is only an internal fallback needed to initialize the model. A Pi
        # that reports no start must not be presented as having selected it.
        result['startNode'] = hardware['startNode']
        # The Pi's current graph blocks and last-known danger from an offline
        # sensor are different facts. Keep both visible; do not let a sensor
        # disconnect erase its last known fire from the map.
        reported = set(hardware['blockedNodes'])
        last_danger = {s['node'] for s in floorplan['sensors']
                       if result['flameSensors'][s['id']]['active']
                       and not result['flameSensors'][s['id']]['connected']}
        result['blockedNodes'] = sorted(reported | last_danger)
        result['blockedEdges'] = hardware['blockedEdges']
        all_zone = hardware.get('allZone')
        if all_zone:
            # A valid all-zone plan intentionally has no legacy single-start
            # route. Do not mistake that empty field for no safe route.
            result['overallStatus'] = ('no_route' if all_zone['routeStatus'] == 'no_route'
                                       else 'fire' if result['realFireDetected'] else 'normal')
        if all_zone and any(edge['from'] in last_danger or edge['to'] in last_danger
                            for edge in all_zone['directedEdges']):
            source = 'pi_unverified'
        if result['route'] and last_danger.intersection(result['route']['nodes']):
            result['route'] = None
            result['routeMode'] = 'none'
            result['fallbackActive'] = False
            result['selectedExitName'] = result['selectedDestinationName'] = result['selectedDestinationType'] = None
            result['overallStatus'] = 'no_route'
            source = 'pi_unverified'
    result['updatedAt'] = received
    result['connections'] = {'pi': bool(row) and not stale, 'server': True}
    result['failSafeActive'] = False  # Do not infer physical fail-safe operation from cloud silence.
    if not row:
        result['overallStatus'] = 'unknown'
        result['route'] = None
        result['routeMode'] = 'none'
        result['selectedExitName'] = result['selectedDestinationName'] = None
    result['sensorCounts']['offline'] = sum(not value['connected'] for value in result['flameSensors'].values())
    result['shutters'] = {sid: {'closed': False, 'connected': False, 'updatedAt': None} for sid in model.shutters}
    equipment = []
    for sensor in floorplan['sensors']:
        sensor_value = result['flameSensors'][sensor['id']]
        active = sensor_value['active']
        sensor_offline = not sensor_value['connected']
        equipment.append({'id': sensor['id'], 'category': '센서', 'name': sensor['name'],
                          'location': sensor['node'], 'value': ('1' if active else '0') if row else '-',
                          'status': 'offline' if sensor_offline else 'danger' if active else 'normal',
                          'stateLabel': '마지막 수신값 · 통신 끊김' if sensor_offline and row else '미수신' if not row else '화재 감지' if active else '정상',
                          'lastSeen': row['observed_at'] if row else None})
    result['equipment'] = equipment
    result['events'] = [{'timestamp': e['observed_at'], 'type': e['type'],
                         'location': e.get('payload', {}).get('sensorId', device_id),
                         'change': {'FIRE': '화재 감지', 'CLEAR': '화재 해제', 'LED': 'LED 출력 보고'}.get(e['type'], e['type']),
                         'result': json.dumps(e.get('payload', {}), ensure_ascii=False)} for e in events]
    result['cloud'] = {'enabled': True, 'deviceId': device_id, 'hasTelemetry': bool(row), 'stale': stale,
                       'receivedAt': received, 'observedAt': row['observed_at'] if row else None,
                       'sequence': row['sequence'] if row else None, 'mappingVersion': MAPPING_VERSION,
                       'routeSource': source, 'led': deepcopy(telemetry.get('led') or {'status': 'unknown', 'segments': []}) if telemetry else {'status': 'unknown', 'segments': []},
                       'hardware': deepcopy(hardware) if hardware else None}
    return result
