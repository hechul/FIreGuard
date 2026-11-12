"""Optional exhaustive Pi-archive simulation; no GPIO, serial, or physical light.

FIREGUARD_PI_PROJECT=/path/to/friends/node1 .venv/bin/python -m unittest discover -s tests -p 'pi_allzone_scenarios_test.py' -v
"""
import itertools
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

import hardware
from cloud_model import cloud_floorplan, validate_hardware_telemetry
from hardware.real_allzone_reporter import make_payload
from hardware.real_device_runtime import prepare_guide_commands
from hardware.real_pi_service import RealPiState

PROJECT = os.environ.get('FIREGUARD_PI_PROJECT')
ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(PROJECT, 'FIREGUARD_PI_PROJECT is not set')
class PiAllZoneScenariosTest(unittest.TestCase):
    def test_all_single_and_pair_fire_snapshots(self):
        project=Path(PROJECT).resolve()
        for filename in ('hardware/led_routes.py','hardware/led_junctions.py',
                         'hardware/cloud_telemetry.py','pi_led_usb.py',
                         'hardware/led_layout_162.json','static/data/floorplan.json'):
            self.assertTrue((project/filename).is_file(), f'Missing Pi dependency: {filename}')
        original=hardware.__path__
        hardware.__path__=list(original)+[str(project/'hardware')]
        sys.path.append(str(project))
        try:
            from hardware.led_routes import load_files
            from hardware.cloud_telemetry import build_payload
            from hardware.all_zone_routes import calculate_all_zones
            from pi_led_usb import logical_to_wire
            layout,floor=load_files()
            server=cloud_floorplan(json.loads((ROOT/'static/data/floorplan.json').read_text()))
            ids=[s['id'] for s in floor['sensors'] if s['type']=='flame']
            self.assertEqual(len(ids),11)
            failures=[]; tested=0; fallback_count=0
            with tempfile.TemporaryDirectory() as directory:
                for count in (1,2):
                    for number,fires in enumerate(itertools.combinations(ids,count)):
                        try:
                            pi=RealPiState(floor,Path(directory)/f'fire-{count}-{number}.json')
                            pi.update({sid:False for sid in ids})
                            pi.update({sid:True for sid in fires})
                            snap=pi.snapshot()
                            plan=calculate_all_zones(snap,floor,layout)
                            commands=prepare_guide_commands(plan,logical_to_wire)
                            self.assertEqual(commands[0],'BEGIN')
                            self.assertTrue(commands[-1].startswith('GUIDE '))
                            # Synthetic ACK: this is not a hardware test.
                            payload=build_payload(snap,floor,layout,device_id='pi-01',
                                boot_id=str(uuid4()),sequence=1,led_status='active',
                                command_ack=True,commanded_path=plan['ledWireIndices'],
                                commanded_fire=plan['fireLedWireIndices'])
                            normalized=validate_hardware_telemetry(make_payload(payload,plan),server,'pi-01')
                            self.assertEqual(normalized['hardware']['allZone']['unreachableNodes'],plan['unreachableNodes'])
                            tested+=1; fallback_count+=bool(plan['fallbackDestinations'])
                        except Exception as exc:
                            failures.append(f'{fires}: {type(exc).__name__}: {exc}')
            self.assertFalse(failures, '\n'.join(failures))
            self.assertEqual(tested,66)
            self.assertGreater(fallback_count,0)
        finally:
            hardware.__path__=original
            sys.path.remove(str(project))

if __name__=='__main__': unittest.main()
