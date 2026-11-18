"""Five-pixel prototype markers; no GPIO or physical mapping assumptions."""
import unittest
from all_zone_fallback_test import load_module


class CompactFireTest(unittest.TestCase):
    def setUp(self):
        self.m = load_module()
        self.m.led_coordinates = lambda layout: [(i, 0, 'S1' if i < 10 else 'S2', i)
                                                  for i in range(20)]
        self.floor = {'nodes': [{'id': 'A', 'x': 5, 'y': 0},
                                {'id': 'B', 'x': 14, 'y': 0}],
                      'sensors': [{'id': 'F1', 'node': 'A'}, {'id': 'F2', 'node': 'B'}]}

    def test_center_and_two_each_side(self):
        self.assertEqual(self.m.compact_fire_leds('F1', self.floor, {}), {3, 4, 5, 6, 7})

    def test_manual_logical_anchor_precedes_estimated_position(self):
        self.m.led_junctions.LABELS_1BASED = {'A': {'S1': 8}}
        self.assertEqual(self.m.compact_fire_leds('F1', self.floor, {}), {5, 6, 7, 8, 9})

    def test_does_not_spill_into_unrelated_next_section(self):
        self.floor['nodes'][0]['x'] = 9
        self.assertEqual(self.m.compact_fire_leds('F1', self.floor, {}), {7, 8, 9})

    def test_invalid_manual_anchor_fails_closed(self):
        self.m.led_junctions.LABELS_1BASED = {'A': {'S1': 100}}
        with self.assertRaises(ValueError):
            self.m.compact_fire_leds('F1', self.floor, {})

    def test_multiple_fires_union_and_block_their_nodes(self):
        self.floor.update(exits=[{'id': 'EXIT_W'}], edges=[
            {'id': 'E1', 'from': 'A', 'to': 'EXIT_W', 'weight': 1},
            {'id': 'E2', 'from': 'B', 'to': 'EXIT_W', 'weight': 1},
            {'id': 'E3', 'from': 'C', 'to': 'EXIT_W', 'weight': 1}])
        self.floor['nodes'].append({'id': 'C', 'x': 19, 'y': 0})
        plan = self.m.calculate_all_zones({'fires': ['F1', 'F2']}, self.floor, {}, compact_fire=True)
        self.assertEqual(set(plan['fireLedLogicalIndices']), {3,4,5,6,7,12,13,14,15,16})
        self.assertEqual(plan['blockedNodes'], ['A', 'B'])
        self.assertFalse(set(plan['fireLedLogicalIndices']) & set(plan['ledLogicalIndices']))
        self.assertFalse({'A', 'B'} & set(plan['routesByStart']))
