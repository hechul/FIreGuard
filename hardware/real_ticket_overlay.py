"""Non-destructive prototype overlay for the measured ticket-office branch.

The original Pi floorplan is kept intact on disk. The source is the existing
dashboard N40/E38 geometry and the friend's S10 manual inspection record;
Arduino optical output and evacuation suitability still require site checks.
"""
from copy import deepcopy

TICKET_NODE = {'id': 'N40', 'name': '매표소 내부', 'x': 443.0, 'y': 409.93}
TICKET_EDGE = {'id': 'E38', 'from': 'N14', 'to': 'N40', 'weight': 1.3654}
S2_EXIT = {'id': 'EXIT_S2', 'name': 'S2 하단 출구', 'x': 107.07, 'y': 590.0, 'available': True}
S2_EDGE = {'id': 'E39', 'from': 'N7', 'to': 'EXIT_S2', 'weight': 0.5}
ROOM5_JUNCTION = {'id':'N41', 'name':'5관 복도 분기점', 'x':240.0, 'y':263.5}


def calibrated_floorplan(floor):
    """Separate room-5 junction LED 148 from FLM-02 at measured LED 153.

    Keep FLM-02 attached to N2. N41 takes the old room/corridor junction;
    E34/E40 split the old corridor without changing its total weight.
    Coordinates are a drawing interpolation, not a physical distance survey.
    """
    result = prototype_floorplan(floor)
    nodes = {n['id']: n for n in result['nodes']}
    edges = {e['id']: e for e in result['edges']}
    if 'N41' in nodes or 'E40' in edges:
        if (nodes.get('N41') != ROOM5_JUNCTION or
                {k:edges.get(k) for k in ('E23','E33','E34','E40')} != {
                    'E23':{'id':'E23','from':'N23','to':'N41','weight':2.6586},
                    'E33':{'id':'E33','from':'N41','to':'N1','weight':0.41},
                    'E34':{'id':'E34','from':'N41','to':'N2','weight':1.497},
                    'E40':{'id':'E40','from':'N2','to':'N25','weight':1.1976}}
                or nodes.get('N2',{}).get('x') != 314.85 or nodes['N2'].get('y') != 263.5):
            raise ValueError('5관 센서 분리 지도 버전이 예상과 다릅니다')
        return result
    if (not {'N2','N1','N23','N25'} <= nodes.keys() or
            (nodes['N2']['x'],nodes['N2']['y']) != (240.0,263.5) or
            any(edges.get(eid) != expected for eid,expected in {
                'E23':{'id':'E23','from':'N23','to':'N2','weight':2.6586},
                'E33':{'id':'E33','from':'N2','to':'N1','weight':0.41},
                'E34':{'id':'E34','from':'N2','to':'N25','weight':2.6946}}.items())):
        raise ValueError('5관 원본 분기점이 예상과 다릅니다')
    result['nodes'].append(deepcopy(ROOM5_JUNCTION))
    nodes['N2']['x'] = 314.85
    edges['E23']['to'] = 'N41'
    edges['E33']['from'] = 'N41'
    edges['E34'].update({'from':'N41','to':'N2','weight':1.497})
    result['edges'].append({'id':'E40','from':'N2','to':'N25','weight':1.1976})
    return result


def legacy_room5_floorplan(floor):
    """Restore pre-calibration topology for reports from older Pi senders."""
    result = deepcopy(floor)
    if not any(n['id'] == 'N41' for n in result['nodes']):
        return result
    result['nodes'] = [n for n in result['nodes'] if n['id'] != 'N41']
    next(n for n in result['nodes'] if n['id'] == 'N2')['x'] = 240.0
    result['edges'] = [e for e in result['edges'] if e['id'] != 'E40']
    edges = {e['id']:e for e in result['edges']}
    edges['E23']['to'] = 'N2'
    edges['E33']['from'] = 'N2'
    edges['E34'].update({'from':'N2','to':'N25','weight':2.6946})
    return result


def enable_calibrated_led_mapping(floor):
    from hardware.led_junctions import EDGE_SECTIONS, LABELS_1BASED
    if calibrated_floorplan(floor) != floor:
        raise ValueError('5관 센서 분리 지도를 먼저 적용해야 합니다')
    enable_prototype_led_mapping(floor)
    if EDGE_SECTIONS.get('E40','S14') != 'S14':
        raise ValueError('5관 센서 간선 LED 매핑 충돌')
    EDGE_SECTIONS['E40'] = 'S14'
    # Original Pi files remain unchanged; update this process's calibration.
    if LABELS_1BASED.get('N2',{}).get('S14') not in (148,153):
        raise ValueError('5관 센서 원본 앵커가 예상과 다릅니다')
    LABELS_1BASED.setdefault('N2',{})['S14'] = 153
    LABELS_1BASED['N2'].pop('S15',None)
    LABELS_1BASED.setdefault('N41',{})['S14'] = 148


def prototype_floorplan(floor):
    """User-confirmed exit at S2 LED 5; drawing position/weight are estimates."""
    result = ticket_floorplan(floor)
    exits, edges = result['exits'], result['edges']
    existing_exit = next((x for x in exits if x['id'] == 'EXIT_S2'), None)
    existing_edge = next((x for x in edges if x['id'] == 'E39'), None)
    if (existing_exit is None) != (existing_edge is None):
        raise ValueError('S2 출구 지도 연결이 불완전합니다')
    if existing_exit is None:
        if not any(n['id'] == 'N7' for n in result['nodes']):
            raise ValueError('S2 출구 입구 N7이 없습니다')
        exits.append(deepcopy(S2_EXIT))
        edges.append(deepcopy(S2_EDGE))
    elif existing_exit != S2_EXIT or existing_edge != S2_EDGE:
        raise ValueError('S2 출구 지도 버전이 예상과 다릅니다')
    return result


def enable_prototype_led_mapping(floor):
    from hardware.led_junctions import EDGE_SECTIONS, LABELS_1BASED
    enable_ticket_led_mapping(floor)
    if next((e for e in floor['edges'] if e['id'] == 'E39'), None) != S2_EDGE:
        raise ValueError('S2 출구 간선이 일치하지 않습니다')
    if EDGE_SECTIONS.get('E39', 'S2') != 'S2':
        raise ValueError('S2 출구 LED 매핑 충돌')
    if LABELS_1BASED.get('EXIT_S2', {'S2': 5}) != {'S2': 5}:
        raise ValueError('S2 출구 앵커 충돌')
    if LABELS_1BASED.get('N7', {}).get('S2') != 8:
        raise ValueError('S2 N7 앵커가 예상과 다릅니다')
    EDGE_SECTIONS['E39'] = 'S2'
    LABELS_1BASED['EXIT_S2'] = {'S2': 5}


def ticket_floorplan(floor):
    floor = deepcopy(floor)
    nodes, edges = floor.get('nodes'), floor.get('edges')
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError('매표소 경로: 도면 형식 오류')
    node = next((n for n in nodes if n.get('id') == 'N40'), None)
    edge = next((e for e in edges if e.get('id') == 'E38'), None)
    if (node is None) != (edge is None):
        raise ValueError('매표소 노드와 간선이 불완전합니다')
    if node is None:
        if not any(n.get('id') == 'N14' for n in nodes):
            raise ValueError('매표소 입구 N14가 없습니다')
        nodes.append(deepcopy(TICKET_NODE))
        edges.append(deepcopy(TICKET_EDGE))
    elif node != TICKET_NODE or edge != TICKET_EDGE:
        raise ValueError('매표소 지도 버전이 예상과 다릅니다')
    return floor


def enable_ticket_led_mapping(floor):
    """Add the known S10 association in this REAL process only."""
    from hardware.led_junctions import EDGE_SECTIONS
    if next((e for e in floor.get('edges', []) if e.get('id') == 'E38'), None) != TICKET_EDGE:
        raise ValueError('매표소 간선이 일치하지 않습니다')
    previous = EDGE_SECTIONS.get('E38', 'missing')
    if previous not in ('missing', 'S10'):
        raise ValueError('기존 매표소 LED 매핑과 충돌합니다')
    EDGE_SECTIONS['E38'] = 'S10'


def cinema_five_layout(layout, floor):
    """Prototype S15: physical LED 159 at corridor, 162 inside room 5.

    The N1/N2 split shares LED 159 because no independent junction LED was
    supplied. The physical positions remain subject to on-site verification.
    """
    from hardware.led_junctions import EDGE_SECTIONS, LABELS_1BASED
    result = deepcopy(layout)
    sections = result.get('sections', [])
    if not sections or (sections[-1].get('id'), sections[-1].get('count')) != ('S15', 4):
        raise ValueError('5관 LED 구간이 예상과 다릅니다')
    if sum(s.get('count', 0) for s in sections) != 162:
        raise ValueError('전체 LED 개수가 예상과 다릅니다')
    junction = 'N41' if any(n['id'] == 'N41' for n in floor['nodes']) else 'N2'
    edges = {e['id']: {e['from'], e['to']} for e in floor.get('edges', [])}
    if edges.get('E33') != {junction, 'N1'} or edges.get('E25') != {'N1', 'N37'}:
        raise ValueError('5관 간선이 예상과 다릅니다')
    nodes = {n['id']: n for n in floor.get('nodes', [])}
    if not {'N1', junction, 'N37'} <= nodes.keys():
        raise ValueError('5관 노드가 없습니다')
    if any(EDGE_SECTIONS.get(eid) not in (None, 'S15') for eid in ('E25', 'E33')):
        raise ValueError('5관 LED 매핑이 기존 매핑과 충돌합니다')
    sections[-1]['line'] = [[nodes[junction]['x'], nodes[junction]['y']],
                            [nodes['N37']['x'], nodes['N37']['y']]]
    sections[-1]['label'] = '5관 출입구 (현장 확인 필요)'
    sections[-1]['physical_direction'] = '하→상'
    EDGE_SECTIONS.update({'E33': 'S15', 'E25': 'S15'})
    for node, led in ((junction, 159), ('N1', 159), ('N37', 162)):
        LABELS_1BASED.setdefault(node, {})['S15'] = led
    return result
