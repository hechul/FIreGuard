#!/usr/bin/env python3
"""FireGuard prototype: choose a safe EXIT for every reachable node, not one start.

Multi-source Dijkstra is run from ALL available exits. A single successor per
node forms a directed forest; it prevents opposing directions at junctions.
Red or adjacent LEDs make the associated edge unavailable *before* routing.
No fallback destination is silently substituted for a real exit.

This is a prototype visualization only, not a certified evacuation system.
"""
from __future__ import annotations

from collections import defaultdict
import heapq
import math

from hardware.led_junctions import EDGE_SECTIONS, selected_edge_leds
from hardware.led_routes import (_active_sensors, _near_hazard_green,
                                 fire_led_indices, led_coordinates)
from pi_led_usb import logical_to_wire


# 상영관 내부에서 복도로 나오는 대피 방향만 허용한다.
# N38(1관 내부)은 남측 EXIT_S를 향하는 기존 양방향 연결을 그대로 유지한다.
# 출발점에서는 사용할 수 있지만 다른 구역의 대피 경로가 여기로 들어가면 안 된다.
CINEMA_OUTBOUND_ONLY_NODES = frozenset({'N12', 'N13', 'N36', 'N37'})



def _edge_leds(edge, floor, layout):
    if EDGE_SECTIONS.get(edge['id']) is None:
        return []
    return selected_edge_leds({
        'route': {'nodes': [edge['from'], edge['to']], 'edges': [edge['id']]}
    }, floor, layout)


def calculate_all_zones(snapshot: dict, floor: dict, layout: dict, *,
                        _extra_blocked_edges=frozenset()) -> dict:
    """Return all-zone plan independent of snapshot['startNode'] and ['route'].

    planned green indices are unique 0-based logical LEDs. A global UNO FLOW
    sequence is *not* per-branch synchronized: inspect directedEdges for exact
    intended direction. Physical direction has to be verified branch-by-branch.
    """
    known_nodes = {item['id'] for item in floor['nodes']}
    exits = {item['id'] for item in floor['exits'] if item.get('available', True)}
    all_vertices = known_nodes | {x['id'] for x in floor['exits']}
    edges = {item['id']: item for item in floor['edges']}
    if set(EDGE_SECTIONS) != set(edges):
        raise ValueError('교차점/그래프 간선 매핑 불일치: LED 출력 취소')

    sensor_nodes = {s['node'] for s in floor['sensors']
                    if s['id'] in _active_sensors(snapshot)}
    base_blocked_nodes = set(snapshot.get('blockedNodes') or []) | sensor_nodes
    base_blocked_edges = set(snapshot.get('blockedEdges') or [])
    if not base_blocked_nodes <= all_vertices or not base_blocked_edges <= set(edges):
        raise ValueError('알 수 없는 차단 노드/간선')
    overrides = snapshot.get('edgeWeightOverrides') or {}
    for eid, weight in overrides.items():
        if eid not in edges or not isinstance(weight, (int,float)) or not math.isfinite(weight) or weight <= 0:
            raise ValueError(f'잘못된 간선 가중치: {eid}')

    red, _ = fire_led_indices(snapshot, floor, layout)
    pixels = led_coordinates(layout)
    led_by_idx = {item[3]: item for item in pixels}
    red_pixels = [led_by_idx[i] for i in red]
    # All graph edges used for guidance must have *real* mapped LED locations.
    edge_pixels = {}
    visual_blocked = set()
    unmapped = set()
    for eid, edge in edges.items():
        index_list = _edge_leds(edge, floor, layout)
        edge_pixels[eid] = index_list
        if not index_list:
            unmapped.add(eid)
        elif red and any(i in red or _near_hazard_green(led_by_idx[i], red_pixels)
                             for i in index_list):
            visual_blocked.add(eid)
    # No green route should be published through red, a nearby hazardous LED,
    # or a corridor whose physical LED location cannot be represented.
    blocked_edges = base_blocked_edges | visual_blocked | unmapped | set(_extra_blocked_edges)
    valid_exits = exits - base_blocked_nodes

    # 아래 adjacency는 *출구에서 역방향으로 탐색하기 위한* 역방향 인접 리스트다.
    # adjacency[at]의 neighbor는 실제 대피 시 neighbor -> at 로 이동한다.
    # 따라서 내부 전용 출발 노드가 at이면 그곳으로 들어오는 방향을 추가하면 안 된다.
    # 반대로 neighbor가 내부 노드인 경우에는 내부 -> 복도 진출을 허용한다.
    adjacency = defaultdict(list)
    for eid, edge in edges.items():
        if eid in blocked_edges or edge['from'] in base_blocked_nodes or edge['to'] in base_blocked_nodes:
            continue
        weight = float(overrides.get(eid, edge['weight']))
        if not math.isfinite(weight) or weight <= 0:
            raise ValueError(f'비정상 가중치: {eid}')
        a, b = edge['from'], edge['to']
        if a not in CINEMA_OUTBOUND_ONLY_NODES:
            adjacency[a].append((b, weight, eid))  # 실제 b -> a
        if b not in CINEMA_OUTBOUND_ONLY_NODES:
            adjacency[b].append((a, weight, eid))  # 실제 a -> b

    # Multi-source Dijkstra: every node picks one unique successor toward an exit.
    # Tie-break deterministically by exit, successor and edge ID.
    distances = {}
    exit_for = {}
    successor = {}
    heap = []
    for dest in sorted(valid_exits):
        distances[dest] = 0.0
        exit_for[dest] = dest
        heapq.heappush(heap, (0.0, dest, dest))
    while heap:
        cost, chosen_exit, at = heapq.heappop(heap)
        if abs(cost-distances.get(at, float('inf'))) > 1e-9 or chosen_exit != exit_for[at]:
            continue
        for neighbor, weight, eid in adjacency[at]:
            cand = cost + weight
            new_key = (round(cand, 10), chosen_exit, at, eid)
            old_key = (round(distances.get(neighbor, float('inf')), 10),
                       exit_for.get(neighbor, '~'),
                       successor.get(neighbor, ('~','~'))[0],
                       successor.get(neighbor, ('~','~'))[1])
            if new_key < old_key:
                distances[neighbor] = cand
                exit_for[neighbor] = chosen_exit
                successor[neighbor] = (at, eid)
                heapq.heappush(heap, (cand, chosen_exit, neighbor))

    reachable = sorted(known_nodes & distances.keys() - base_blocked_nodes)
    unreachable = sorted(known_nodes - base_blocked_nodes - set(reachable))
    route_by_start = {}
    directed_edges = []
    led_distance = {}
    led_directions = defaultdict(set)
    for node in reachable:
        chain = [node]
        used = set()
        cursor = node
        while cursor not in valid_exits:
            if cursor in used or cursor not in successor:
                raise ValueError(f'경로 방향 트리 오류: {node}')
            used.add(cursor)
            cursor = successor[cursor][0]
            chain.append(cursor)
        # 사용자가 명시한 상영관 4곳은 경로의 첫 노드로만 등장할 수 있다.
        # N38은 제한 대상에서 제외하며 기존 입/출입 경로를 유지한다.
        if set(chain[1:]) & CINEMA_OUTBOUND_ONLY_NODES:
            raise ValueError(f'상영관 내부 진입 경로 생성 차단: {node}')
        route_by_start[node] = {'exitNode': exit_for[node],
                                'routeNodes': chain, 'cost': round(distances[node], 6)}

    # Each successor edge occurs exactly once, regardless of the number of
    # distinct starts that eventually merge into it.
    for node in reachable:
        nxt, eid = successor[node]
        indices = _edge_leds({'id': eid, 'from':node, 'to':nxt}, floor, layout)
        if not indices:
            raise ValueError('경로 간선 LED 매핑 불가')
        weight = float(overrides.get(eid, edges[eid]['weight']))
        for j, idx in enumerate(indices):
            if idx in red or (red and _near_hazard_green(led_by_idx[idx], red_pixels)):
                raise ValueError(f'위험구역 경유 LED {idx}: 안전 경로 계산 실패')
            # High distance from exit = earlier in a global UNO FLOW sequence.
            # Prefer larger distance for shared junction pixels.
            location_cost = distances[nxt] + weight*(1 - (j + 0.5)/len(indices))
            led_distance[idx] = max(led_distance.get(idx, float('-inf')), location_cost)
            led_directions[idx].add((node,nxt))
        directed_edges.append({'edgeId':eid, 'from':node,'to':nxt,
                               'exitNode':exit_for[node], 'ledLogicalIndices':indices})

    # A logical LED must not carry opposite directions at the same time.
    # Shared junction anchor pixels are fine when the directions agree.
    opposing = []
    for idx, references in led_directions.items():
        signs = set()
        for src, dst in references:
            edge = next(e for e in directed_edges if e['from'] == src and e['to'] == dst)
            sequence = edge['ledLogicalIndices']
            if len(sequence) >= 2:
                signs.add(1 if sequence[-1] > sequence[0] else -1)
        if len(signs) > 1:
            opposing.append(idx)
    if opposing:
        # Do not publish ambiguous directions. Remove participating physical
        # edges and re-run the multi-exit calculation until conflicts vanish.
        conflicting_edges = {e['edgeId'] for e in directed_edges
                             if set(e['ledLogicalIndices']) & set(opposing)}
        newly_forbidden = conflicting_edges - set(_extra_blocked_edges)
        if not newly_forbidden:
            raise ValueError(f'해소 불가능한 역방향 LED 충돌: {sorted(opposing)}')
        return calculate_all_zones(snapshot, floor, layout,
                                   _extra_blocked_edges=frozenset(set(_extra_blocked_edges) | newly_forbidden))

    ordered_leds = sorted(led_distance, key=lambda i: (-led_distance[i], i))
    if len(ordered_leds) != len(set(ordered_leds)) or (set(ordered_leds) & red):
        raise ValueError('LED 경로 중복/화재 구간 충돌')
    return {
        'routingMode': 'all_zones_to_exits',
        'startNode': None,
        'routeStatus': ('ok' if reachable and not unreachable else
                        'partial' if reachable else 'no_route'),
        'activeSensorIds': sorted(_active_sensors(snapshot)),
        'blockedNodes': sorted(base_blocked_nodes),
        'blockedEdges': sorted(base_blocked_edges),
        'ledExcludedEdges': sorted(visual_blocked | unmapped | set(_extra_blocked_edges)),
        'directionConflictExcludedEdges': sorted(_extra_blocked_edges),
        'unmappedEdges': sorted(unmapped),
        'availableExits': sorted(valid_exits),
        'guidedNodes': reachable,
        'unreachableNodes': unreachable,
        'routesByStart': route_by_start,
        'directedEdges': directed_edges,
        'ledLogicalIndices': ordered_leds,
        'ledWireIndices': [logical_to_wire(i) for i in ordered_leds],
        'fireLedLogicalIndices': sorted(red),
        'fireLedWireIndices': [logical_to_wire(i) for i in sorted(red)],
        'flowLimitation': 'Uno FLOW 단일 배열은 다중 분기 애니메이션을 독립 동기화하지 못함',
    }
