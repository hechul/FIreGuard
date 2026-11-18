#!/usr/bin/env python3
"""FireGuard prototype: choose a safe EXIT for every reachable node, not one start.

Multi-source Dijkstra is run from ALL available exits. A single successor per
node forms a directed forest; it prevents opposing directions at junctions.
Red LEDs make the associated edge unavailable before routing. Legacy mode
also applies drawing-coordinate clearance; compact lab mode uses anchors.
Fallback destinations are explicitly marked, never represented as exits.

This is a prototype visualization only, not a certified evacuation system.
"""
from __future__ import annotations

from collections import defaultdict
import heapq
import math

from hardware.led_junctions import EDGE_SECTIONS, selected_edge_leds
import hardware.led_junctions as led_junctions
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


def compact_fire_leds(sensor_id, floor, layout):
    """Prototype marker: center +/- two LEDs within one physical section.

    Use the same manual/interpolated anchors as route LED selection. Drawing
    coordinates only choose among incident sections, not an independent index.
    Never cross a section boundary merely because wire indices are adjacent.
    """
    sensor = next(s for s in floor['sensors'] if s['id'] == sensor_id)
    node = next(n for n in floor['nodes'] if n['id'] == sensor['node'])
    pixels = led_coordinates(layout)
    if not pixels:
        raise ValueError('화재 표시 LED 좌표가 없습니다')
    anchors = getattr(led_junctions, 'LABELS_1BASED', {}).get(node['id'], {})
    candidates = [p for p in pixels if anchors.get(p[2]) == p[3] + 1]
    if anchors and not candidates:
        raise ValueError('화재 노드 LED 앵커가 레이아웃과 일치하지 않습니다')
    if not candidates:
        sections = {EDGE_SECTIONS.get(e['id']) for e in floor.get('edges', [])
                    if node['id'] in (e['from'], e['to'])} - {None}
        if not sections:
            raise ValueError('화재 노드에 연결된 LED 구간이 없습니다')
        indices = {led_junctions.anchor_for_node(node['id'], sid, floor, layout)
                   for sid in sections}
        candidates = [p for p in pixels if p[2] in sections and p[3] in indices]
    center = min(candidates,
                 key=lambda p: ((p[0]-node['x'])**2 + (p[1]-node['y'])**2, p[3]))
    return {p[3] for p in pixels if p[2] == center[2] and abs(p[3]-center[3]) <= 2}


def calculate_all_zones(snapshot: dict, floor: dict, layout: dict, *,
                        compact_fire=False, _extra_blocked_edges=frozenset()) -> dict:
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

    # The team confirmed the N14–N9 corridor is usable for an N4-only
    # prototype fire. The legacy coordinate estimate extends FLM-04 red one
    # pixel into that corridor (logical 106); do not let that extrapolation
    # close the entire corridor. Other active sensors keep their own full red
    # zones and clearance, even when FLM-04 is active at the same time.
    # This is an installation-specific prototype assumption, not a real-life
    # assessment of smoke, fire spread or corridor safety.
    active_sensors = set(_active_sensors(snapshot))
    red_by_sensor = {}
    for sensor_id in active_sensors:
        single = dict(snapshot)
        single['flameSensors'] = {sensor_id: (snapshot.get('flameSensors') or {}).get(
            sensor_id, {'active': True, 'connected': True})}
        if compact_fire:
            red_by_sensor[sensor_id] = compact_fire_leds(sensor_id, floor, layout)
        else:
            red_by_sensor[sensor_id], _ = fire_led_indices(single, floor, layout)
    if not compact_fire and 'FLM-04' in red_by_sensor:
        corridor = edges.get('E18')
        if (not corridor or {corridor['from'], corridor['to']} != {'N14', 'N9'}
                or 106 not in _edge_leds(corridor, floor, layout)):
            raise ValueError('N4 인접 통로 매핑이 예상과 다름: LED 출력 취소')
        red_by_sensor['FLM-04'].discard(106)
    red = set().union(*red_by_sensor.values()) if red_by_sensor else set()
    # Site correction: these two S9 tip LEDs look like inward shop guidance
    # during an N4 fire. Suppress green only; another sensor's red still wins.
    suppressed_green = {117,118} if compact_fire and 'FLM-04' in active_sensors else set()
    pixels = led_coordinates(layout)
    led_by_idx = {item[3]: item for item in pixels}
    sensor_red_pixels = {sid: [led_by_idx[i] for i in indices]
                         for sid, indices in red_by_sensor.items()}
    # Compact mode is a model demonstration: the explicit red LEDs and graph
    # fire nodes define exclusions. Do not add the legacy screen-space radius
    # to manually calibrated indices; the two coordinate systems disagree.
    # Verified/legacy mode retains its original clearance policy.
    def hazardous(eid, idx):
        if idx in red:
            return True
        if compact_fire:
            return False
        return any(_near_hazard_green(led_by_idx[idx], sensor_pixels)
                   for sid, sensor_pixels in sensor_red_pixels.items()
                   if not (sid == 'FLM-04' and eid == 'E18'))
    # All graph edges used for guidance must have *real* mapped LED locations.
    edge_pixels = {}
    visual_blocked = set()
    unmapped = set()
    for eid, edge in edges.items():
        index_list = _edge_leds(edge, floor, layout)
        edge_pixels[eid] = index_list
        if not index_list:
            unmapped.add(eid)
        elif any(hazardous(eid, i) for i in index_list):
            visual_blocked.add(eid)
    # No complete route may cross a red LED or an unmapped corridor. Legacy
    # mode also excludes its drawing-coordinate clearance zone.
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
    def search(destinations, protected=frozenset()):
        for dest in sorted(destinations):
            distances[dest] = 0.0
            exit_for[dest] = dest
            heapq.heappush(heap, (0.0, dest, dest))
        while heap:
            cost, chosen_exit, at = heapq.heappop(heap)
            if abs(cost-distances.get(at, float('inf'))) > 1e-9 or chosen_exit != exit_for[at]:
                continue
            for neighbor, weight, eid in adjacency[at]:
                if neighbor in protected:
                    continue
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

    search(valid_exits)
    exit_reachable = frozenset(distances)
    fallback_config = {x['id']: x for x in floor.get('fallbackDestinations', [])
                       if isinstance(x, dict) and x.get('id') in known_nodes
                       and x.get('available', True) is True
                       and x.get('type') in ('toilet', 'descender')}
    fallback_roots = set(fallback_config) - base_blocked_nodes - set(exit_reachable)
    search(fallback_roots, exit_reachable)
    terminals = valid_exits | fallback_roots

    # These prototype branches have physical exit-direction markings: the
    # descender corridor points toward N7 and the 1관 branch toward EXIT_S.
    # Prefer them only when the complete target path already reaches the
    # intended available exit without returning through the source node.
    for source, target, edge_id, desired_exit in (
        ('N3', 'N7', 'E10', exit_for.get('N7') if exit_for.get('N7') in {'EXIT_W', 'EXIT_S2'} else 'EXIT_W'),
        # Keep the western vertical corridor continuous toward N7 when its
        # entire downstream route is available and avoids the hazard.
        ('N23', 'N3', 'E31', exit_for.get('N7') if exit_for.get('N7') in {'EXIT_W', 'EXIT_S2'} else 'EXIT_W'),
        ('N31', 'N38', 'E13', 'EXIT_S'),
        # Join the east corridor to the already available south exit route.
        ('N33', 'N31', 'E04', 'EXIT_S'),
        # Keep the N29–N8 corridor lit toward the west exit when that whole
        # route is available; never use the preference across a blocked edge.
        ('N29', 'N8', 'E29', exit_for.get('N8') if exit_for.get('N8') in {'EXIT_W', 'EXIT_S2'} else 'EXIT_W'),
    ):
        if (source not in successor or exit_for.get(target) != desired_exit
                or not any(n == source and e == edge_id for n, _, e in adjacency[target])):
            continue
        chain = {source}
        cursor = target
        while cursor in successor and cursor not in chain:
            chain.add(cursor)
            cursor = successor[cursor][0]
        if cursor in chain or cursor != desired_exit:
            continue
        successor[source] = (target, edge_id)
        # A changed successor also changes the distance and destination of
        # every upstream node; never publish the previous Dijkstra values.
        for node in list(successor):
            walk = []
            cursor = node
            visited = set()
            while cursor in successor:
                if cursor in visited:
                    raise ValueError('방향 우선 경로 순환')
                visited.add(cursor)
                nxt, eid = successor[cursor]
                walk.append((cursor, eid))
                cursor = nxt
            if cursor not in terminals:
                raise ValueError('방향 우선 경로 목적지 없음')
            cost = 0.0
            for at, eid in reversed(walk):
                cost += float(overrides.get(eid, edges[eid]['weight']))
                distances[at] = cost
                exit_for[at] = cursor

    reachable = sorted((known_nodes & distances.keys()) - base_blocked_nodes - terminals)
    unreachable = sorted(known_nodes - base_blocked_nodes - set(reachable) - fallback_roots)
    route_by_start = {}
    directed_edges = []
    led_distance = {}
    for node in reachable:
        chain = [node]
        used = set()
        cursor = node
        while cursor not in terminals:
            if cursor in used or cursor not in successor:
                raise ValueError(f'경로 방향 트리 오류: {node}')
            used.add(cursor)
            cursor = successor[cursor][0]
            chain.append(cursor)
        # 사용자가 명시한 상영관 4곳은 경로의 첫 노드로만 등장할 수 있다.
        # N38은 제한 대상에서 제외하며 기존 입/출입 경로를 유지한다.
        if set(chain[1:]) & CINEMA_OUTBOUND_ONLY_NODES:
            raise ValueError(f'상영관 내부 진입 경로 생성 차단: {node}')
        destination = exit_for[node]
        route_by_start[node] = {'exitNode': destination if destination in valid_exits else None,
                                'destinationNode': destination,
                                'destinationType': 'exit' if destination in valid_exits else fallback_config[destination]['type'],
                                'routeNodes': chain, 'cost': round(distances[node], 6)}

    # Each successor edge occurs exactly once, regardless of the number of
    # distinct starts that eventually merge into it.
    for node in reachable:
        nxt, eid = successor[node]
        indices = [i for i in _edge_leds({'id': eid, 'from':node, 'to':nxt}, floor, layout)
                   if i not in suppressed_green]
        if not indices:
            raise ValueError('경로 간선 LED 매핑 불가')
        weight = float(overrides.get(eid, edges[eid]['weight']))
        for j, idx in enumerate(indices):
            if hazardous(eid, idx):
                raise ValueError(f'위험구역 경유 LED {idx}: 안전 경로 계산 실패')
            # High distance from exit = earlier in a global UNO FLOW sequence.
            # Prefer larger distance for shared junction pixels.
            location_cost = distances[nxt] + weight*(1 - (j + 0.5)/len(indices))
            led_distance[idx] = max(led_distance.get(idx, float('-inf')), location_cost)
        directed_edges.append({'edgeId':eid, 'from':node,'to':nxt,
                               'exitNode':exit_for[node], 'ledLogicalIndices':indices})

    # Two paths may converge on a single shared junction LED from either
    # numerical direction. Only reverse traversal of the same LED pair is a
    # genuine physical direction conflict (also enforced by GUIDE preflight).
    pairs = defaultdict(set)
    for edge in directed_edges:
        seq = edge['ledLogicalIndices']
        for a, b in zip(seq, seq[1:]):
            if a != b:
                pairs[(a, b)].add(edge['edgeId'])
    opposing = {(a, b) for a, b in pairs if (b, a) in pairs}
    if opposing:
        # Do not publish ambiguous directions. Removing every participating edge
        # also cuts branches that could still guide people after just one edge
        # is rerouted. Remove the least-used edge, then recalculate the entire
        # forest and check for conflicts again.
        conflicting_edges = set().union(*(pairs[pair] for pair in opposing))
        newly_forbidden = conflicting_edges - set(_extra_blocked_edges)
        if not newly_forbidden:
            raise ValueError(f'해소 불가능한 역방향 LED 충돌: {sorted(opposing)}')
        use_count = defaultdict(int)
        for route in route_by_start.values():
            for src, dst in zip(route['routeNodes'], route['routeNodes'][1:]):
                if src in successor and successor[src][0] == dst:
                    use_count[successor[src][1]] += 1
        edge_to_remove = min(newly_forbidden, key=lambda eid: (use_count[eid], eid))
        return calculate_all_zones(snapshot, floor, layout,
                                   compact_fire=compact_fire,
                                   _extra_blocked_edges=frozenset(set(_extra_blocked_edges) | {edge_to_remove}))

    # A forest chooses one outgoing edge at each node, leaving some usable
    # corridors between exit catchments dark. Represent these as explicit
    # additional exit-reaching branches, never as a second primary successor.
    # All branches together must remain acyclic and agree on LED pair direction.
    coverage_edges = []
    outgoing = defaultdict(set)
    for edge in directed_edges:
        outgoing[edge['from']].add(edge['to'])
    def reaches(start, goal):
        todo, visited = [start], set()
        while todo:
            at = todo.pop()
            if at == goal:
                return True
            if at not in visited:
                visited.add(at)
                todo.extend(outgoing[at])
        return False
    if compact_fire:
        for eid in ('E01', 'E02', 'E09', 'E35'):
            edge = edges.get(eid)
            if not edge or eid in blocked_edges or any(e['edgeId'] == eid for e in directed_edges):
                continue
            a, b = edge['from'], edge['to']
            for src, dst in sorted(((a,b), (b,a)), key=lambda p: (distances.get(p[1], math.inf), p)):
                if (src not in reachable or dst not in set(reachable) | valid_exits or dst in CINEMA_OUTBOUND_ONLY_NODES
                        or exit_for[dst] not in valid_exits or reaches(dst, src)):
                    continue
                seq = _edge_leds({'id':eid, 'from':src, 'to':dst}, floor, layout)
                if not seq or any(hazardous(eid, i) for i in seq):
                    continue
                seq = [i for i in seq if i not in suppressed_green]
                if not seq:
                    continue
                if any((b,a) in pairs for a,b in zip(seq,seq[1:]) if a != b):
                    continue
                coverage_edges.append({'edgeId':eid, 'from':src, 'to':dst,
                                       'exitNode':exit_for[dst], 'ledLogicalIndices':seq})
                outgoing[src].add(dst)
                for a,b in zip(seq,seq[1:]):
                    if a != b:
                        pairs[(a,b)].add(eid)
                for j, idx in enumerate(seq):
                    cost = distances[dst] + float(overrides.get(eid, edge['weight'])) * (1-(j+.5)/len(seq))
                    led_distance[idx] = max(led_distance.get(idx, -math.inf), cost)
                break

    # A fire at N7 closes the complete E10 graph edge. People already on its
    # far side can still leave toward N3. Describe only the maximal non-red
    # suffix that joins that node's exit route, never an N7-through-fire route.
    partial_edges = []
    if (compact_fire and 'N7' in sensor_nodes and 'N3' in reachable
            and exit_for['N3'] in valid_exits and 'E10' not in base_blocked_edges
            and edges.get('E10', {}).get('id') == 'E10'
            and {edges['E10']['from'], edges['E10']['to']} == {'N7', 'N3'}):
        seq = _edge_leds({'id':'E10', 'from':'N7', 'to':'N3'}, floor, layout)
        suffix = []
        for idx in reversed(seq):
            if idx in red:
                break
            suffix.append(idx)
        suffix.reverse()
        if (len(suffix) >= 2 and len(suffix) < len(seq)
                and not any((b,a) in pairs for a,b in zip(suffix,suffix[1:]))):
            partial_edges.append({'edgeId':'E10', 'towardNode':'N3', 'exitNode':exit_for['N3'],
                                  'ledLogicalIndices':suffix})
            for j,idx in enumerate(suffix):
                led_distance[idx] = max(led_distance.get(idx,-math.inf),
                                        distances['N3'] + (len(suffix)-j)*1e-3)

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
        'fallbackDestinations': sorted({edge['exitNode'] for edge in directed_edges if edge['exitNode'] in fallback_roots}),
        'guidedNodes': reachable,
        'unreachableNodes': unreachable,
        'routesByStart': route_by_start,
        'directedEdges': directed_edges,
        **({'coverageEdges': coverage_edges} if compact_fire else {}),
        **({'partialEdges': partial_edges} if compact_fire else {}),
        'ledLogicalIndices': ordered_leds,
        'ledWireIndices': [logical_to_wire(i) for i in ordered_leds],
        'fireLedLogicalIndices': sorted(red),
        'fireLedWireIndices': [logical_to_wire(i) for i in sorted(red)],
        'flowLimitation': 'Uno FLOW 단일 배열은 다중 분기 애니메이션을 독립 동기화하지 못함',
    }
