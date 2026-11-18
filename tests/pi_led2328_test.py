"""Western corridor is guided only while the whole route remains available."""
import os
import sys
import unittest
from pathlib import Path
import hardware


@unittest.skipUnless(os.environ.get('FIREGUARD_PI_PROJECT'), 'Pi project not supplied')
class WesternCorridorTest(unittest.TestCase):
    def test_n4_continuous_and_descender_fire_excludes_corridor(self):
        project = Path(os.environ['FIREGUARD_PI_PROJECT']).resolve()
        original = hardware.__path__
        hardware.__path__ = list(original) + [str(project / 'hardware')]
        sys.path.append(str(project))
        try:
            from hardware.led_routes import load_files
            from hardware.real_ticket_overlay import ticket_floorplan, enable_ticket_led_mapping, cinema_five_layout
            from hardware.all_zone_routes import calculate_all_zones
            from pi_led_usb import logical_to_wire
            layout, floor = load_files()
            floor = ticket_floorplan(floor)
            enable_ticket_led_mapping(floor)
            layout = cinema_five_layout(layout, floor)
            def plan(*ids):
                return calculate_all_zones({'flameSensors': {i: {'active': True, 'connected': True} for i in ids}}, floor, layout)
            result = plan('FLM-04')
            edge = next(e for e in result['directedEdges'] if e['edgeId'] == 'E31')
            self.assertEqual((edge['from'], edge['to']), ('N23', 'N3'))
            self.assertEqual([logical_to_wire(i) for i in edge['ledLogicalIndices']], list(range(29, 21, -1)))
            self.assertEqual(result['routesByStart']['N23']['exitNode'], 'EXIT_W')
            east = next(e for e in result['directedEdges'] if e['edgeId'] == 'E04')
            self.assertEqual((east['from'], east['to']), ('N33', 'N31'))
            self.assertEqual([logical_to_wire(i) for i in east['ledLogicalIndices']], [41, 42, 43, 44])
            self.assertEqual(result['routesByStart']['N33']['exitNode'], 'EXIT_S')
            blocked = plan('FLM-04', 'FLM-03')
            self.assertFalse(set(range(23, 29)) & set(blocked['ledWireIndices']))
            self.assertTrue(set(range(23, 29)) <= set(blocked['fireLedWireIndices']))
            blocked_east = plan('FLM-04', 'FLM-10')
            self.assertFalse({42, 43} & set(blocked_east['ledWireIndices']))
        finally:
            hardware.__path__ = original
            sys.path.remove(str(project))
