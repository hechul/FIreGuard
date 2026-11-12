"""Prototype fallback routes: explicit destinations, primary exit always preferred."""
import importlib.util
import itertools
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_module():
    junctions = types.ModuleType('hardware.led_junctions')
    junctions.EDGE_SECTIONS = {'E1':'S', 'E2':'S', 'E3':'S'}
    junctions.selected_edge_leds = lambda s, f, l: {'E1':[1], 'E2':[2], 'E3':[3]}[s['route']['edges'][0]]
    routes = types.ModuleType('hardware.led_routes')
    routes._active_sensors = lambda snapshot: set(snapshot.get('fires', []))
    routes._near_hazard_green = lambda led, red: False
    routes.fire_led_indices = lambda s,f,l: (set(), None)
    routes.led_coordinates = lambda layout: [(0,0,0,i) for i in range(162)]
    serial = types.ModuleType('pi_led_usb')
    serial.logical_to_wire = lambda i: i if i < 20 else i+1
    spec = importlib.util.spec_from_file_location('fallback_routing_under_test', ROOT/'hardware/all_zone_routes.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'hardware.led_junctions':junctions, 'hardware.led_routes':routes, 'pi_led_usb':serial}):
        spec.loader.exec_module(module)
    return module


class FallbackRouteTest(unittest.TestCase):
    def setUp(self):
        self.module=load_module()
        self.floor={'nodes':[{'id':'N13'}, {'id':'A'}, {'id':'N5'}],
                    'exits':[{'id':'EXIT_W'}],
                    'edges':[{'id':'E1','from':'N13','to':'A','weight':1},
                             {'id':'E2','from':'A','to':'EXIT_W','weight':100},
                             {'id':'E3','from':'A','to':'N5','weight':1}],
                    'sensors':[{'id':'F5','node':'N5'}],
                    'fallbackDestinations':[{'id':'N5','type':'toilet','available':True}]}
    def plan(self, blocked=(), fires=()):
        return self.module.calculate_all_zones({'blockedEdges':list(blocked), 'blockedNodes':[], 'fires':list(fires)}, self.floor, {})
    def test_exit_precedes_shorter_fallback(self):
        result=self.plan()
        self.assertEqual(result['routesByStart']['N13']['destinationNode'],'EXIT_W')
        self.assertEqual(result['fallbackDestinations'],[])
    def test_blocked_exit_uses_marked_fallback(self):
        result=self.plan(['E2'])
        route=result['routesByStart']['N13']
        self.assertEqual(route['routeNodes'],['N13','A','N5'])
        self.assertIsNone(route['exitNode'])
        self.assertEqual(route['destinationType'],'toilet')
        self.assertEqual(result['fallbackDestinations'],['N5'])
        self.assertNotIn('N5',result['guidedNodes'])
    def test_fire_at_fallback_disables_it(self):
        result=self.plan(['E2'], ['F5'])
        self.assertNotIn('N13',result['routesByStart'])
        self.assertIn('N13',result['unreachableNodes'])
        self.assertEqual(result['fallbackDestinations'],[])

    def test_all_edge_block_combinations_terminate_at_reported_destination(self):
        for size in range(4):
            for blocked in itertools.combinations(('E1','E2','E3'), size):
                with self.subTest(blocked=blocked):
                    result=self.plan(blocked)
                    for start, route in result['routesByStart'].items():
                        self.assertEqual(route['routeNodes'][0], start)
                        self.assertEqual(route['routeNodes'][-1], route['destinationNode'])
                        self.assertNotIn(route['destinationNode'], result['unreachableNodes'])
                        self.assertFalse(set(blocked) & {e['edgeId'] for e in result['directedEdges']})

    def test_direction_conflict_recalculates_and_never_reuses_excluded_edge(self):
        mapping={'E1':[1,2], 'E2':[2,3], 'E3':[3,2]}
        self.module._edge_leds=lambda edge, floor, layout: mapping[edge['id']]
        result=self.plan(['E2'])
        excluded=set(result['directionConflictExcludedEdges'])
        self.assertTrue(excluded)
        self.assertFalse(excluded & {edge['edgeId'] for edge in result['directedEdges']})
        self.assertIn('N13',result['unreachableNodes'])

if __name__=='__main__': unittest.main()
