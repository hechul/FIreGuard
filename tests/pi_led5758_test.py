"""N29 corridor preference using the supplied Pi prototype data."""
import os
import sys
import unittest
from pathlib import Path
import hardware


@unittest.skipUnless(os.environ.get('FIREGUARD_PI_PROJECT'), 'Pi project not supplied')
class Corridor5758Test(unittest.TestCase):
    def test_n4_guides_gap_and_n8_fire_keeps_it_red(self):
        project = Path(os.environ['FIREGUARD_PI_PROJECT']).resolve()
        old = hardware.__path__
        hardware.__path__ = list(old) + [str(project / 'hardware')]
        sys.path.append(str(project))
        try:
            from hardware.led_routes import load_files
            from hardware.real_ticket_overlay import ticket_floorplan, enable_ticket_led_mapping, cinema_five_layout
            from hardware.all_zone_routes import calculate_all_zones
            from hardware.real_device_runtime import prepare_guide_commands
            from pi_led_usb import logical_to_wire
            layout, floor = load_files()
            floor = ticket_floorplan(floor)
            enable_ticket_led_mapping(floor)
            layout = cinema_five_layout(layout, floor)
            def plan(*ids):
                return calculate_all_zones({'flameSensors': {s: {'active': True, 'connected': True} for s in ids}}, floor, layout)
            n4 = plan('FLM-04')
            edge = next(e for e in n4['directedEdges'] if e['edgeId'] == 'E29')
            self.assertEqual((edge['from'], edge['to']), ('N29', 'N8'))
            self.assertEqual([logical_to_wire(i) for i in edge['ledLogicalIndices']], [56, 57, 58, 59])
            self.assertEqual(n4['routesByStart']['N29']['exitNode'], 'EXIT_W')
            self.assertIn('SEG 56 57 58 59', prepare_guide_commands(n4, logical_to_wire))
            blocked = plan('FLM-04', 'FLM-08')
            self.assertFalse({57, 58} & set(blocked['ledWireIndices']))
            self.assertTrue({57, 58} <= set(blocked['fireLedWireIndices']))
        finally:
            hardware.__path__ = old
            sys.path.remove(str(project))


if __name__ == '__main__':
    unittest.main()
