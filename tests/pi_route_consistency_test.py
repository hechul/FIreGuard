"""Exercise real Pi graph guidance for single and simultaneous sensor fires.

This checks logical route and LED consistency, not actual installation or safety.
Run with FIREGUARD_PI_PROJECT pointing at the extracted Pi project.
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
class PiRouteConsistencyTest(unittest.TestCase):
    def test_routes_follow_selected_led_edges_for_single_and_multiple_fires(self):
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
            sensors = [s for s in floor['sensors'] if s['type'] == 'flame']
            ids = [s['id'] for s in sensors]
            edges = {e['id']: e for e in floor['edges']}
            with tempfile.TemporaryDirectory() as tmp:
                # Pairs and triples test combined fire zones, not only single fires.
                for count in (1, 2, 3):
                    for i, fires in enumerate(itertools.combinations(ids, count)):
                        with self.subTest(fires=fires):
                            state = RealPiState(floor, Path(tmp) / f'{count}-{i}.json')
                            state.update(dict.fromkeys(ids, False))
                            state.update(dict.fromkeys(fires, True))
                            plan = calculate_all_zones(state.snapshot(), floor, layout)
                            chosen = {(e['from'], e['to']): e for e in plan['directedEdges']}
                            greens = set(plan['ledLogicalIndices'])
                            reds = set(plan['fireLedLogicalIndices'])
                            self.assertFalse(greens & reds)
                            self.assertEqual(set(plan['guidedNodes']), set(plan['routesByStart']))
                            self.assertFalse(set(plan['guidedNodes']) & set(plan['unreachableNodes']))
                            for start, route in plan['routesByStart'].items():
                                nodes = route['routeNodes']
                                self.assertEqual(nodes[0], start)
                                self.assertEqual(nodes[-1], route['destinationNode'])
                                self.assertEqual(len(nodes), len(set(nodes)))
                                self.assertFalse(set(nodes) & set(plan['blockedNodes']))
                                for src, dst in zip(nodes, nodes[1:]):
                                    self.assertIn((src, dst), chosen)
                                    segment = chosen[src, dst]
                                    edge = edges[segment['edgeId']]
                                    self.assertEqual({src, dst}, {edge['from'], edge['to']})
                                    self.assertTrue(segment['ledLogicalIndices'])
                                    self.assertTrue(set(segment['ledLogicalIndices']) <= greens)
                                    self.assertFalse(set(segment['ledLogicalIndices']) & reds)
        finally:
            hardware.__path__ = original
            sys.path.remove(str(project))


if __name__ == '__main__':
    unittest.main()
