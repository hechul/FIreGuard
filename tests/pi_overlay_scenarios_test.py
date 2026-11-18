"""Exercise the Pi's current room-5 overlay with combined sensor fires.

This checks planning and serialization only; it cannot measure LED light.
"""
from copy import deepcopy
from itertools import combinations
import os
from pathlib import Path
import sys
import unittest

import hardware


@unittest.skipUnless(os.environ.get('FIREGUARD_PI_PROJECT'), 'Pi project not supplied')
class OverlayScenariosTest(unittest.TestCase):
    def test_single_and_pair_fires_have_consistent_safe_guide_commands(self):
        project = Path(os.environ['FIREGUARD_PI_PROJECT']).resolve()
        original = hardware.__path__
        hardware.__path__ = list(original) + [str(project / 'hardware')]
        sys.path.append(str(project))
        try:
            from hardware.led_junctions import EDGE_SECTIONS, LABELS_1BASED
            from hardware.led_routes import load_files
            from hardware.real_ticket_overlay import ticket_floorplan, enable_ticket_led_mapping, cinema_five_layout
            from hardware.all_zone_routes import calculate_all_zones
            from hardware.real_device_runtime import prepare_guide_commands
            from pi_led_usb import logical_to_wire

            old_edges, old_labels = deepcopy(EDGE_SECTIONS), deepcopy(LABELS_1BASED)
            self.addCleanup(lambda: (EDGE_SECTIONS.clear(), EDGE_SECTIONS.update(old_edges),
                                     LABELS_1BASED.clear(), LABELS_1BASED.update(old_labels)))
            layout, floor = load_files()
            floor = ticket_floorplan(floor)
            enable_ticket_led_mapping(floor)
            layout = cinema_five_layout(layout, floor)
            sensors = [s['id'] for s in floor['sensors'] if s['type'] == 'flame']
            self.assertEqual(len(sensors), 11)
            for count in (1, 2):
                for fires in combinations(sensors, count):
                    with self.subTest(fires=fires):
                        snapshot = {'flameSensors': {sid: {'active': True, 'connected': True} for sid in fires}}
                        plan = calculate_all_zones(snapshot, floor, layout)
                        green = set(plan['ledLogicalIndices'])
                        red = set(plan['fireLedLogicalIndices'])
                        self.assertFalse(green & red)
                        commands = prepare_guide_commands(plan, logical_to_wire)
                        segments = [c for c in commands if c.startswith('SEG ')]
                        actual_wire = {int(i) for c in segments for i in c.split()[1:]}
                        self.assertEqual(actual_wire, {logical_to_wire(i) for i in green})
                        for start, route in plan['routesByStart'].items():
                            self.assertEqual(route['routeNodes'][0], start)
                            self.assertEqual(route['routeNodes'][-1], route['destinationNode'])
                            self.assertFalse(set(route['routeNodes']) & set(plan['blockedNodes']))
        finally:
            hardware.__path__ = original
            sys.path.remove(str(project))


if __name__ == '__main__':
    unittest.main()
