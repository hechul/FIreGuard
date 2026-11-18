"""Pi prototype N4 corridor regression; not a physical safety test."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

import hardware
from hardware.real_pi_service import RealPiState

PROJECT = os.environ.get('FIREGUARD_PI_PROJECT')


@unittest.skipUnless(PROJECT, 'FIREGUARD_PI_PROJECT is not set')
class N4CorridorTest(unittest.TestCase):
    def test_corridor_open_for_n4_but_blocked_by_independent_n9_fire(self):
        project = Path(PROJECT).resolve()
        original = hardware.__path__
        hardware.__path__ = list(original) + [str(project / 'hardware')]
        sys.path.append(str(project))
        try:
            from hardware.led_routes import load_files
            from hardware.all_zone_routes import calculate_all_zones
            from hardware.real_ticket_overlay import ticket_floorplan, enable_ticket_led_mapping
            layout, floor = load_files()
            floor = ticket_floorplan(floor)
            enable_ticket_led_mapping(floor)
            ids = [s['id'] for s in floor['sensors'] if s['type'] == 'flame']
            with tempfile.TemporaryDirectory() as tmp:
                def plan(fires, filename):
                    state = RealPiState(floor, Path(tmp) / filename)
                    state.update(dict.fromkeys(ids, False))
                    state.update(dict.fromkeys(fires, True))
                    return calculate_all_zones(state.snapshot(), floor, layout)

                n4 = plan(['FLM-04'], 'n4')
                self.assertEqual(n4['routesByStart']['N14']['routeNodes'][:3], ['N14', 'N9', 'N31'])
                self.assertNotIn(106, n4['fireLedLogicalIndices'])
                self.assertIn(106, n4['ledLogicalIndices'])

                both = plan(['FLM-04', 'FLM-09'], 'both')
                self.assertIn(106, both['fireLedLogicalIndices'])
                self.assertIn('E18', both['ledExcludedEdges'])
                self.assertNotIn(106, both['ledLogicalIndices'])

                other = plan(['FLM-04', 'FLM-10'], 'other')
                self.assertEqual(other['routesByStart']['N14']['routeNodes'][:2], ['N14', 'N9'])
                self.assertFalse(set(other['ledLogicalIndices']) & set(other['fireLedLogicalIndices']))
        finally:
            hardware.__path__ = original
            sys.path.remove(str(project))
