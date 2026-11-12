"""Pi ticket-office overlay: optional real archive integration, never uses GPIO."""
import json
import itertools
import os
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import hardware
from cloud_model import cloud_floorplan, validate_hardware_telemetry
from hardware.real_ticket_overlay import ticket_floorplan, enable_ticket_led_mapping
from hardware.real_pi_service import RealPiState
from hardware.real_allzone_reporter import make_payload
from hardware.real_device_runtime import prepare_guide_commands

ROOT = Path(__file__).resolve().parents[1]
PROJECT = os.environ.get('FIREGUARD_PI_PROJECT')


class TicketOverlayUnitTest(unittest.TestCase):
    def test_non_destructive_and_idempotent(self):
        floor = {'nodes': [{'id': 'N14'}], 'edges': []}
        original = deepcopy(floor)
        changed = ticket_floorplan(floor)
        self.assertEqual(floor, original)
        self.assertEqual(ticket_floorplan(changed), changed)
        self.assertEqual(changed['nodes'][-1]['id'], 'N40')
        self.assertEqual(changed['edges'][-1]['id'], 'E38')

    def test_wrong_or_incomplete_topology_is_rejected(self):
        for floor in ({'nodes': [], 'edges': []},
                      {'nodes': [{'id': 'N14'}, {'id': 'N40'}], 'edges': []},
                      {'nodes': [{'id': 'N14'}, {'id': 'N40'}],
                       'edges': [{'id': 'E38', 'from': 'N14', 'to': 'N40'}]}):
            with self.subTest(floor=floor), self.assertRaises(ValueError):
                ticket_floorplan(floor)


@unittest.skipUnless(PROJECT, 'FIREGUARD_PI_PROJECT is not set')
class PiTicketOverlayTest(unittest.TestCase):
    def test_ticket_overlay_all_single_and_double_fire_reports(self):
        project = Path(PROJECT).resolve()
        path, old = str(project), hardware.__path__
        sys.path.append(path)
        hardware.__path__ = list(old) + [str(project / 'hardware')]
        try:
            from hardware.led_routes import load_files
            from hardware.led_junctions import EDGE_SECTIONS
            from hardware.cloud_telemetry import build_payload
            from hardware.all_zone_routes import calculate_all_zones
            from pi_led_usb import logical_to_wire
            before = deepcopy(EDGE_SECTIONS)
            self.addCleanup(lambda: (EDGE_SECTIONS.clear(), EDGE_SECTIONS.update(before)))
            layout, floor = load_files()
            floor = ticket_floorplan(floor)
            enable_ticket_led_mapping(floor)
            server = cloud_floorplan(json.loads((ROOT/'static/data/floorplan.json').read_text()))
            ids = [s['id'] for s in floor['sensors'] if s['type'] == 'flame']
            scenarios = list(itertools.combinations(ids, 1)) + list(itertools.combinations(ids, 2))
            self.assertEqual(len(scenarios), 66)
            with tempfile.TemporaryDirectory() as tmp:
                for number, fires in enumerate(scenarios):
                    with self.subTest(fires=fires):
                        pi = RealPiState(floor, Path(tmp)/str(number))
                        pi.update({sid:False for sid in ids})
                        pi.update({sid:True for sid in fires})
                        snapshot = pi.snapshot()
                        plan = calculate_all_zones(snapshot, floor, layout)
                        commands = prepare_guide_commands(plan, logical_to_wire)
                        segments = [cmd.split()[1:] for cmd in commands if cmd.startswith('SEG ')]
                        self.assertLessEqual(len(segments), 40)
                        self.assertLessEqual(sum(map(len, segments)), 163)
                        payload = build_payload(snapshot, floor, layout, device_id='pi-01',
                            boot_id=str(uuid4()), sequence=1, led_status='not_running')
                        normalized = validate_hardware_telemetry(make_payload(payload, plan), server, 'pi-01')
                        self.assertEqual(normalized['hardware']['allZone']['unreachableNodes'], plan['unreachableNodes'])
        finally:
            hardware.__path__ = old
            sys.path.remove(path)

    def test_new_ticket_branch_and_legacy_cloud_compatibility(self):
        project = Path(PROJECT).resolve()
        path, old = str(project), hardware.__path__
        sys.path.append(path)
        hardware.__path__ = list(old) + [str(project / 'hardware')]
        try:
            from hardware.led_routes import load_files
            from hardware.led_junctions import EDGE_SECTIONS, selected_edge_leds
            from hardware.cloud_telemetry import build_payload, mapping_versions, graph_mapping_version
            from hardware.all_zone_routes import calculate_all_zones
            from pi_led_usb import logical_to_wire
            layout, original = load_files()
            source = deepcopy(original)
            before = deepcopy(EDGE_SECTIONS)
            server = cloud_floorplan(json.loads((ROOT/'static/data/floorplan.json').read_text()))
            new = ticket_floorplan(original)
            enable_ticket_led_mapping(new)
            self.addCleanup(lambda: (EDGE_SECTIONS.clear(), EDGE_SECTIONS.update(before)))
            self.assertEqual(original, source)
            self.assertEqual(mapping_versions(layout, new), ('flame11-5cce6a933e', 'led162-usb163-shift20-c5a4392f78'))
            self.assertEqual(graph_mapping_version(new), 'graph-e434bafc81')
            outward = selected_edge_leds({'route': {'nodes':['N40','N14'], 'edges':['E38']}}, new, layout)
            self.assertEqual(outward, [122, 121, 120, 119])
            with tempfile.TemporaryDirectory() as tmp:
                pi = RealPiState(new, Path(tmp)/'fire.json')
                pi.update({sid:False for sid in pi.sensor_nodes})
                pi.update({'FLM-07':True})
                snap = pi.snapshot()
                plan = calculate_all_zones(snap, new, layout)
                self.assertEqual(plan['routesByStart']['N40']['routeNodes'][:2], ['N40','N14'])
                self.assertTrue(set(outward).issubset(plan['ledLogicalIndices']))
                commands = prepare_guide_commands(plan, logical_to_wire)
                self.assertIn('SEG 123 122 121 120', commands)
                base = build_payload(snap, new, layout, device_id='pi-01', boot_id=str(uuid4()),
                                     sequence=1, led_status='not_running')
                report = make_payload(base, plan)
                accepted = validate_hardware_telemetry(report, server, 'pi-01')
                self.assertIn('N40', accepted['hardware']['allZone']['guidedNodes'])
                bad = deepcopy(report)
                bad['graphMappingVersion'] = 'graph-7e06ff7ced'
                with self.assertRaises(ValueError):
                    validate_hardware_telemetry(bad, server, 'pi-01')
                bad = deepcopy(report)
                bad['ledMappingVersion'] = 'led162-usb163-shift20-da2de217fd'
                with self.assertRaises(ValueError):
                    validate_hardware_telemetry(bad, server, 'pi-01')
                for malformed in ([], {}, None, 7):
                    bad = deepcopy(report)
                    bad['ledMappingVersion'] = malformed
                    with self.subTest(malformed=malformed), self.assertRaises(ValueError):
                        validate_hardware_telemetry(bad, server, 'pi-01')
            # The server continues to accept the existing Pi version. Keep
            # E38 disabled for this isolated legacy snapshot, then restore it.
            EDGE_SECTIONS.clear()
            EDGE_SECTIONS.update(before)
            with tempfile.TemporaryDirectory() as tmp:
                legacy = RealPiState(original, Path(tmp)/'legacy.json')
                legacy.update({sid:False for sid in legacy.sensor_nodes})
                base = build_payload(legacy.snapshot(), original, layout,
                    device_id='pi-01', boot_id=str(uuid4()), sequence=1, led_status='not_running')
                validated = validate_hardware_telemetry(make_payload(base, None), server, 'pi-01')
                self.assertEqual(validated['hardware']['graphMappingVersion'], 'graph-7e06ff7ced')
        finally:
            hardware.__path__ = old
            sys.path.remove(path)
