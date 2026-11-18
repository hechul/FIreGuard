"""Verify the supplied room-5 prototype mapping against the Pi archive."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from copy import deepcopy
from uuid import uuid4

import hardware
from cloud_model import cloud_floorplan, validate_hardware_telemetry
from hardware.real_pi_service import RealPiState
from hardware.real_ticket_overlay import ticket_floorplan, enable_ticket_led_mapping, cinema_five_layout
from hardware.real_allzone_reporter import make_payload

PROJECT = os.environ.get('FIREGUARD_PI_PROJECT')
ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(PROJECT, 'FIREGUARD_PI_PROJECT is not set')
class RoomFiveTest(unittest.TestCase):
    def test_n4_fire_room5_has_exit_guidance_and_cloud_accepts_mapping(self):
        old_path = hardware.__path__
        hardware.__path__ = list(old_path) + [str(Path(PROJECT) / 'hardware')]
        sys.path.append(PROJECT)
        try:
            from hardware.led_routes import load_files
            from hardware.led_junctions import EDGE_SECTIONS, LABELS_1BASED
            from hardware.cloud_telemetry import mapping_versions, build_payload
            from hardware.all_zone_routes import calculate_all_zones
            from hardware.real_device_runtime import prepare_guide_commands
            from pi_led_usb import logical_to_wire
            old_edges, old_labels = deepcopy(EDGE_SECTIONS), deepcopy(LABELS_1BASED)
            self.addCleanup(lambda: (EDGE_SECTIONS.clear(), EDGE_SECTIONS.update(old_edges),
                                     LABELS_1BASED.clear(), LABELS_1BASED.update(old_labels)))
            layout, floor = load_files()
            floor = ticket_floorplan(floor)
            enable_ticket_led_mapping(floor)
            original = deepcopy(layout)
            layout = cinema_five_layout(layout, floor)
            self.assertNotEqual(layout, original)
            self.assertEqual(mapping_versions(layout, floor)[1], 'led162-usb163-shift20-ca3ff6b9c6')
            with tempfile.TemporaryDirectory() as tmp:
                state = RealPiState(floor, Path(tmp) / 'state.json')
                ids = [s['id'] for s in floor['sensors'] if s['type'] == 'flame']
                state.update(dict.fromkeys(ids, False))
                state.update({'FLM-04': True})
                plan = calculate_all_zones(state.snapshot(), floor, layout)
                self.assertEqual(plan['routesByStart']['N37']['routeNodes'][:3], ['N37', 'N1', 'N2'])
                segment = next(e for e in plan['directedEdges'] if e['edgeId'] == 'E25')
                self.assertEqual(segment['ledLogicalIndices'], [161, 160, 159, 158])
                self.assertIn('SEG 162 161 160 159', prepare_guide_commands(plan, logical_to_wire))
                payload = build_payload(state.snapshot(), floor, layout, device_id='pi-01',
                    boot_id=str(uuid4()), sequence=1, led_status='not_running')
                server = cloud_floorplan(json.loads((ROOT / 'static/data/floorplan.json').read_text()))
                validate_hardware_telemetry(make_payload(payload, plan), server, 'pi-01')
        finally:
            hardware.__path__ = old_path
            sys.path.remove(PROJECT)
