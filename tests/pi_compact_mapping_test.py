"""Read-only planner checks against user-supplied Pi files, including on Windows."""
import ast
from copy import deepcopy
from itertools import combinations
import json
import os
from pathlib import Path
import sys
import unittest
from uuid import uuid4

import hardware

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get('FIREGUARD_PI_PROJECT'), 'Pi project not supplied')
class CompactMappingTest(unittest.TestCase):
    def test_actual_mapping_and_all_fire_combinations(self):
        project = Path(os.environ['FIREGUARD_PI_PROJECT']).resolve()
        old_path = list(hardware.__path__)
        hardware.__path__ = old_path + [str(project / 'hardware')]
        sys.path.append(str(project))
        try:
            from hardware.led_routes import load_files
            from hardware.led_junctions import EDGE_SECTIONS, LABELS_1BASED
            from hardware.real_ticket_overlay import calibrated_floorplan, enable_calibrated_led_mapping, cinema_five_layout
            from hardware.all_zone_routes import calculate_all_zones, compact_fire_leds
            from pi_led_usb import logical_to_wire
            from hardware.cloud_telemetry import build_payload
            from hardware.real_allzone_reporter import make_payload
            from cloud_model import cloud_floorplan, validate_hardware_telemetry
            server = cloud_floorplan(json.loads((ROOT / 'static/data/floorplan.json').read_text(encoding='utf-8')))
            original_edges, original_labels = deepcopy(EDGE_SECTIONS), deepcopy(LABELS_1BASED)
            self.addCleanup(lambda: (EDGE_SECTIONS.clear(), EDGE_SECTIONS.update(original_edges),
                                     LABELS_1BASED.clear(), LABELS_1BASED.update(original_labels)))
            layout, floor = load_files()
            floor = calibrated_floorplan(floor)
            enable_calibrated_led_mapping(floor)
            layout = cinema_five_layout(layout, floor)

            # Execute the production pure serializer without importing Linux
            # fcntl/serial runtime on Windows. No lock/device behavior is mocked.
            tree = ast.parse((ROOT / 'hardware/real_device_runtime.py').read_text(encoding='utf-8'))
            func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'prepare_guide_commands')
            namespace = {}
            exec(compile(ast.Module(body=[func], type_ignores=[]), '<production-guide-serializer>', 'exec'), namespace)
            serialize = namespace['prepare_guide_commands']
            sensors = {s['id']: s['node'] for s in floor['sensors'] if s['type'] == 'flame'}
            self.assertEqual(len(sensors), 11)
            zones = {sid: compact_fire_leds(sid, floor, layout) for sid in sensors}
            def plan(fires):
                return calculate_all_zones({'flameSensors': {sid: {'active': True, 'connected': True} for sid in fires}},
                                           floor, layout, compact_fire=True)
            n4 = plan(['FLM-04'])
            self.assertFalse({117,118} & set(n4['ledLogicalIndices']))
            n2 = plan(['FLM-02'])
            self.assertEqual(n2['fireLedLogicalIndices'], list(range(150,155)))
            self.assertTrue(set(range(158,162)) <= set(n2['ledLogicalIndices']))
            self.assertIn('N41', n2['routesByStart']['N37']['routeNodes'])
            self.assertNotIn('N2', n2['routesByStart']['N37']['routeNodes'])
            self.assertIn('SEG 162 161 160 159', serialize(n2, logical_to_wire))
            n3 = plan(['FLM-03'])
            self.assertTrue(set(range(114,119)) <= set(n3['ledLogicalIndices']))
            shop = next(e for e in n3['coverageEdges'] if e['edgeId'] == 'E35')
            self.assertEqual((shop['from'], shop['to']), ('N27','N25'))
            self.assertEqual(n4['fireLedLogicalIndices'], [108,109,110,111,112])
            self.assertEqual(n4['routesByStart']['N40']['routeNodes'][:3], ['N40','N14','N9'])
            self.assertIn('SEG 123 122 121 120', serialize(n4, logical_to_wire))
            requested = [39,40,5,6,7,*range(30,37),20,*range(120,124)]
            self.assertTrue({i-1 for i in requested} <= set(n4['ledLogicalIndices']))
            self.assertTrue({22,23,24,25,26,27,28,41,42,43} <= set(n4['ledWireIndices']),
                            'Existing west and south corridor guidance must remain lit')
            self.assertEqual({e['edgeId'] for e in n4['coverageEdges']}, {'E01','E02','E09'})
            self.assertTrue({64,65} <= set(n4['ledLogicalIndices']))
            self.assertTrue(set(range(128,140)) <= set(n4['ledLogicalIndices']), 'Popcorn exit path')
            self.assertTrue(set(range(158,162)) <= set(n4['ledLogicalIndices']), 'N4: room 5 LEDs 159-162')
            self.assertIn('SEG 162 161 160 159', serialize(n4, logical_to_wire))
            self.assertEqual(n4['routesByStart']['N19']['routeNodes'][:4], ['N19','N15','N27','N25'])
            s2 = next(e for e in n4['directedEdges'] if e['edgeId'] == 'E39')
            self.assertEqual(s2['ledLogicalIndices'], [7,6,5,4])
            self.assertEqual((s2['from'],s2['to']), ('N7','EXIT_S2'))
            both = plan(['FLM-04', 'FLM-09'])
            self.assertNotIn('N40', both['routesByStart'])
            self.assertFalse(set(range(119,123)) & set(both['ledLogicalIndices']))
            two = plan(['FLM-07','FLM-09'])
            self.assertEqual(set(two['fallbackDestinations']), {'N5','N6'})
            self.assertEqual(two['routesByStart']['N28']['destinationNode'],'N5')
            self.assertEqual(two['routesByStart']['N29']['destinationNode'],'N6')
            self.assertTrue(set(range(70,78)) <= set(two['ledLogicalIndices']))
            three = plan(['FLM-07','FLM-08','FLM-09'])
            self.assertEqual(three['routesByStart']['N13']['routeNodes'],['N13','N35','N28','N5'])
            self.assertEqual(zones['FLM-08'],set(range(56,61)), 'N8 route anchor 59, not coordinate pixel 54')
            for result in (two,three):
                self.assertIn(19,result['ledLogicalIndices'], 'Logical LED 20 can leave away from N7')
                self.assertEqual(result['partialEdges'],[{'edgeId':'E10','towardNode':'N3',
                    'exitNode':'EXIT_NW','ledLogicalIndices':list(range(10,22))}])
                self.assertFalse({64,65} & set(result['ledLogicalIndices']), 'Do not guide through burning N7')
            self.assertEqual(plan(['FLM-07','FLM-03'])['partialEdges'],[], 'No stub when far endpoint burns')
            manual = calculate_all_zones({'flameSensors':{'FLM-07':{'active':True,'connected':True}},
                                         'blockedEdges':['E10']},floor,layout,compact_fire=True)
            self.assertEqual(manual['partialEdges'],[], 'Manual closure covers the entire corridor')
            tested = 0
            for count in range(1,12):
                for fires in combinations(sensors, count):
                    with self.subTest(fires=fires):
                        result = plan(fires)
                        red = set(result['fireLedLogicalIndices'])
                        green = set(result['ledLogicalIndices'])
                        self.assertEqual(red, set().union(*(zones[sid] for sid in fires)))
                        self.assertLessEqual(len(red), 5 * len(fires))
                        self.assertFalse(red & green)
                        if 'FLM-04' in fires:
                            self.assertFalse({117,118} & green)
                        self.assertNotIn(20, result['ledWireIndices'] + result['fireLedWireIndices'])
                        for route in result['routesByStart'].values():
                            self.assertFalse(set(route['routeNodes']) & {sensors[sid] for sid in fires})
                            self.assertEqual(len(route['routeNodes']), len(set(route['routeNodes'])))
                        commands = serialize(result, logical_to_wire)
                        self.assertEqual(commands[-1], 'GUIDE 200 0 6 0 0 0 12')
                        if 'N37' in result['routesByStart']:
                            self.assertTrue(set(range(158,162)) <= green,
                                            'Room 5 guidance must include corridor LED 159')
                        self.assertEqual(bool(green & set(range(158,162))),
                                         set(range(158,162)) <= green,
                                         'Room 5 must not lose its endpoint alone')
                        self.assertTrue(commands[-1].startswith('GUIDE '))
                        wire_segments = [list(map(int,c.split()[1:])) for c in commands if c.startswith('SEG ')]
                        self.assertEqual({i for seg in wire_segments for i in seg}, set(result['ledWireIndices']))
                        self.assertLessEqual(sum(map(len,wire_segments)),163)
                        self.assertLessEqual(len(wire_segments),40)
                        for stub in result['partialEdges']:
                            self.assertIn(stub['towardNode'],result['routesByStart'])
                            self.assertEqual(result['routesByStart'][stub['towardNode']]['exitNode'],stub['exitNode'])
                            self.assertFalse(red & set(stub['ledLogicalIndices']))
                        snapshot = {'operationMode': 'real', 'startNode': None, 'route': None,
                                    'flameSensors': {sid: {'active': sid in fires, 'connected': True,
                                                          'updatedAt': None} for sid in sensors},
                                    'blockedNodes': result['blockedNodes'], 'blockedEdges': []}
                        payload = build_payload(snapshot, floor, layout, device_id='pi-01',
                                                boot_id=str(uuid4()), sequence=1, led_status='active',
                                                command_ack=True, commanded_path=result['ledWireIndices'],
                                                commanded_fire=result['fireLedWireIndices'])
                        accepted = validate_hardware_telemetry(make_payload(payload, result), server, 'pi-01')
                        self.assertEqual(accepted['hardware']['fireLedLogicalIndices'], sorted(red))
                        tested += 1
            self.assertEqual(tested, 2047)
        finally:
            hardware.__path__ = old_path
            sys.path.remove(str(project))
