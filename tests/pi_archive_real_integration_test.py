"""Optional integration against the actual friend's Pi project files.

Run with FIREGUARD_PI_PROJECT=/path/to/node1. This is still a simulated
Arduino acknowledgement; it does not test GPIO, serial or physical light.
"""
import json
import os
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import hardware
from cloud_model import cloud_floorplan, validate_hardware_telemetry
from hardware.real_allzone_reporter import make_payload
from hardware.real_device_runtime import RealLedController
from hardware.real_pi_service import RealPiState


PROJECT = os.environ.get('FIREGUARD_PI_PROJECT')


@unittest.skipUnless(PROJECT, 'FIREGUARD_PI_PROJECT is not set')
class PiArchiveRealIntegrationTest(unittest.TestCase):
    def test_real_fallback_planner_reporter_server_chain(self):
        project = Path(PROJECT).resolve()
        sys.path.append(str(project))
        original_path = hardware.__path__
        hardware.__path__ = list(original_path) + [str(project / 'hardware')]
        try:
            from hardware.led_routes import load_files
            from hardware.cloud_telemetry import build_payload
            from hardware.all_zone_routes import calculate_all_zones
            layout, floor = load_files()
            server_floor = cloud_floorplan(json.loads(
                (Path(__file__).resolve().parents[1] / 'static/data/floorplan.json').read_text()))
            with tempfile.TemporaryDirectory() as directory:
                pi = RealPiState(floor, Path(directory) / 'fire.json')
                pi.update({sid:False for sid in pi.sensor_nodes})
                pi.update({'FLM-03':True})
                snap = pi.snapshot()
                plan = calculate_all_zones(snap, floor, layout)
                self.assertIn('N5', plan['fallbackDestinations'])
                base = build_payload(snap, floor, layout, device_id='pi-01',
                    boot_id=str(uuid4()), sequence=1, led_status='not_running')
                payload = make_payload(base, plan)
                normalized = validate_hardware_telemetry(payload, server_floor, 'pi-01')
                self.assertEqual(normalized['hardware']['allZone']['fallbackDestinations'], ['N5'])
                self.assertTrue(any(edge['exitNode'] == 'N5' for edge in payload['allZone']['directedEdges']))
        finally:
            hardware.__path__ = original_path
            sys.path.remove(str(project))

    def test_two_fire_snapshots_with_planner_sender_and_server(self):
        project = Path(PROJECT).resolve()
        for filename in ('hardware/led_routes.py', 'hardware/led_junctions.py',
                         'hardware/cloud_telemetry.py', 'pi_led_usb.py',
                         'hardware/led_layout_162.json', 'static/data/floorplan.json'):
            self.assertTrue((project / filename).is_file(), f'Missing Pi dependency: {filename}')
        hardware_path = str(project / 'hardware')
        sys.path.append(str(project))
        original_path = hardware.__path__
        hardware.__path__ = list(original_path) + [hardware_path]
        try:
            from hardware.led_routes import load_files
            from hardware.cloud_telemetry import build_payload
            from pi_led_usb import logical_to_wire

            # The friend's loader resolves files relative to its source.
            layout, floor = load_files()
            layout = deepcopy(layout)
            # Test-only in-memory override; never writes or certifies real mapping.
            layout.update(verified=True, mapping_status='confirmed')
            server_floor = cloud_floorplan(json.loads(
                (Path(__file__).resolve().parents[1] / 'static/data/floorplan.json').read_text()))

            class FakeUno:
                def __init__(self, port, check): self.check = check
                def stop(self): pass
                def flow(self, path, red): self.check()
                def command(self, cmd): pass
                def close(self): pass

            with tempfile.TemporaryDirectory() as directory:
                pi = RealPiState(floor, Path(directory) / 'fire.json')
                pi.update({sid: False for sid in pi.sensor_nodes})
                pi.update({'FLM-07': True, 'FLM-10': True})
                pi.update({'FLM-07': False, 'FLM-10': False})
                snap = pi.snapshot()
                self.assertEqual(set(snap['realFireSensorIds']), {'FLM-07', 'FLM-10'})
                controller = RealLedController(pi.snapshot, floor, layout, enabled=True,
                    port='/dev/fake', uno_factory=FakeUno, translate=logical_to_wire)
                try:
                    result = controller.step(snap)
                    self.assertEqual(result['led_status'], 'active', result['led_error'])
                    self.assertTrue(result['command_ack'])
                    base = build_payload(snap, floor, layout, device_id='pi-01',
                        boot_id=str(uuid4()), sequence=1, **result)
                    payload = make_payload(base, controller.last_all_zone)
                    normalized = validate_hardware_telemetry(payload, server_floor, 'pi-01')
                    self.assertEqual(payload['allZone']['routeStatus'], 'partial')
                    self.assertTrue(payload['allZone']['unreachableNodes'])
                    self.assertTrue(payload['ledIndices'])
                    self.assertTrue(payload['fireLedIndices'])
                    self.assertEqual(normalized['hardware']['allZone'], payload['allZone'])
                finally:
                    controller.close()
        finally:
            hardware.__path__ = original_path
            sys.path.remove(str(project))


if __name__ == '__main__':
    unittest.main()
