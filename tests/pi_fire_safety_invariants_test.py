"""Prototype regression checks for measured fire zones and active routes.

The Pi archive must be supplied explicitly.  These are software checks only;
they cannot establish the measured LED positions or safe human evacuation.
"""
import itertools
import os
import sys
import tempfile
import unittest
from pathlib import Path

import hardware
from hardware.real_pi_service import RealPiState

PROJECT = os.environ.get('FIREGUARD_PI_PROJECT')


@unittest.skipUnless(PROJECT, 'FIREGUARD_PI_PROJECT is not set')
class PiFireSafetyInvariantsTest(unittest.TestCase):
    def test_single_and_multi_fire_never_guide_through_red_or_blocked_nodes(self):
        project = Path(PROJECT).resolve()
        original = hardware.__path__
        hardware.__path__ = list(original) + [str(project / 'hardware')]
        sys.path.append(str(project))
        try:
            from hardware.led_routes import load_files, led_coordinates, _near_hazard_green
            from hardware.all_zone_routes import calculate_all_zones

            layout, floor = load_files()
            sensors = [s for s in floor['sensors'] if s['type'] == 'flame']
            ids = [s['id'] for s in sensors]
            self.assertEqual(len(ids), 11)
            by_id = {s['id']: s['node'] for s in sensors}
            pixels = {p[3]: p for p in led_coordinates(layout)}
            # Explicit ranges documented in the partner's measured mapping.
            measured = {
                'FLM-01': set(range(0, 4)) | set(range(29, 36)),
                'FLM-07': set(range(4, 7)),
                'FLM-10': set(range(36, 43)),
                'FLM-11': set(range(82, 96)),
            }
            with tempfile.TemporaryDirectory() as directory:
                for count in (1, 2):
                    for ordinal, fires in enumerate(itertools.combinations(ids, count)):
                        with self.subTest(fires=fires):
                            state = RealPiState(floor, Path(directory) / f'{count}-{ordinal}.json')
                            state.update({sid: False for sid in ids})
                            state.update({sid: True for sid in fires})
                            plan = calculate_all_zones(state.snapshot(), floor, layout)
                            red = set(plan['fireLedLogicalIndices'])
                            green = set(plan['ledLogicalIndices'])
                            self.assertFalse(red & green)
                            for sensor in fires:
                                if sensor in measured:
                                    self.assertTrue(measured[sensor] <= red,
                                                    f'{sensor} measured red zone was lost')
                            red_coords = [pixels[i] for i in red]
                            for index in green:
                                self.assertFalse(_near_hazard_green(pixels[index], red_coords),
                                                 f'green LED {index} near reported fire {fires}')
                            blocked_nodes = {by_id[sensor] for sensor in fires}
                            for route in plan['routesByStart'].values():
                                self.assertFalse(blocked_nodes & set(route['routeNodes']))
                            for edge in plan['directedEdges']:
                                self.assertNotIn(edge['edgeId'], plan['blockedEdges'])
                                self.assertNotIn(edge['edgeId'], plan['ledExcludedEdges'])
        finally:
            hardware.__path__ = original
            sys.path.remove(str(project))


if __name__ == '__main__':
    unittest.main()
