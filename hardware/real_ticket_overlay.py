"""Non-destructive prototype overlay for the measured ticket-office branch.

The original Pi floorplan is kept intact on disk. The source is the existing
dashboard N40/E38 geometry and the friend's S10 manual inspection record;
Arduino optical output and evacuation suitability still require site checks.
"""
from copy import deepcopy

TICKET_NODE = {'id': 'N40', 'name': '매표소 내부', 'x': 443.0, 'y': 409.93}
TICKET_EDGE = {'id': 'E38', 'from': 'N14', 'to': 'N40', 'weight': 1.3654}


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
