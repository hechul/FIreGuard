"""Read-only N4 plan inspection using the actual partner Pi project.

Run from the updated checkout: python tools/inspect_n4_leds.py --pi-project /path/to/node1
No GPIO, serial, cloud requests, or tokens are accessed.
"""
import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pi-project', required=True)
    parser.add_argument('--fires', nargs='+', default=['FLM-04'],
                        choices=[f'FLM-{i:02}' for i in range(1,12)])
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    project = Path(args.pi_project).resolve()
    required = ['hardware/led_routes.py', 'hardware/led_junctions.py',
                'hardware/led_layout_162.json', 'static/data/floorplan.json', 'pi_led_usb.py']
    missing = [name for name in required if not (project / name).is_file()]
    if missing:
        parser.error('Missing Pi dependencies: ' + ', '.join(missing))
    sys.path.insert(0, str(root))
    import hardware
    hardware.__path__ = list(hardware.__path__) + [str(project / 'hardware')]
    sys.path.append(str(project))
    from hardware.led_routes import load_files
    from hardware.led_junctions import EDGE_SECTIONS
    from hardware.real_ticket_overlay import calibrated_floorplan, enable_calibrated_led_mapping, cinema_five_layout
    from hardware.all_zone_routes import calculate_all_zones, _edge_leds
    from pi_led_usb import logical_to_wire
    layout, floor = load_files()
    floor = calibrated_floorplan(floor)
    enable_calibrated_led_mapping(floor)
    layout = cinema_five_layout(layout, floor)
    snapshot = {'flameSensors': {sid: {'active': True, 'connected': True} for sid in args.fires}}
    for compact in (False, True):
        plan = calculate_all_zones(snapshot, floor, layout, compact_fire=compact)
        red, green = set(plan['fireLedLogicalIndices']), set(plan['ledLogicalIndices'])
        report = {'activeSensors': args.fires, 'compactFire': compact, 'redLogical1Based': sorted(i+1 for i in red),
                  'redWireSlots': plan['fireLedWireIndices'], 'routes': plan['routesByStart'],
                  'ledExcludedEdges': plan['ledExcludedEdges'], 'partialEdges': plan.get('partialEdges', []),
                  'requestedLogical1Based': []}
        for label in [*range(39,41), *range(5,8), *range(30,37), 20,65,66, *range(71,79), *range(120,124), *range(129,141)]:
            idx = label-1
            edges = [e['id'] for e in floor['edges'] if idx in _edge_leds(e, floor, layout)]
            report['requestedLogical1Based'].append({
                'label': label, 'wireSlot': logical_to_wire(idx),
                'state': 'red' if idx in red else 'green' if idx in green else 'off',
                'mappedEdges': edges,
                'sections': sorted({EDGE_SECTIONS[e] for e in edges if EDGE_SECTIONS[e]}),
                'excludedEdges': sorted(set(edges) & set(plan['ledExcludedEdges'])),
                'selectedDirections': [e for e in plan['directedEdges'] + plan.get('coverageEdges', []) + plan.get('partialEdges', [])
                                       if idx in e['ledLogicalIndices']]})
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
