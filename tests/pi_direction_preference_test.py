"""Prototype branch preferences using the supplied Pi project (no hardware)."""
import os
import sys
import unittest
from pathlib import Path

import hardware


@unittest.skipUnless(os.environ.get('FIREGUARD_PI_PROJECT'), 'Pi project not supplied')
class DirectionPreferenceTest(unittest.TestCase):
    def test_preferred_branches_and_fire_fallback(self):
        project = Path(os.environ['FIREGUARD_PI_PROJECT']).resolve()
        old = hardware.__path__
        hardware.__path__ = list(old) + [str(project / 'hardware')]
        sys.path.append(str(project))
        try:
            from hardware.led_routes import load_files
            from hardware.real_ticket_overlay import ticket_floorplan, enable_ticket_led_mapping
            from hardware.all_zone_routes import calculate_all_zones
            layout, floor = load_files()
            floor = ticket_floorplan(floor)
            enable_ticket_led_mapping(floor)

            def plan(*ids):
                return calculate_all_zones({'flameSensors': {
                    sid: {'active': True, 'connected': True} for sid in ids}}, floor, layout)

            single = plan('FLM-04')
            self.assertEqual(single['routesByStart']['N3']['routeNodes'][:2], ['N3', 'N7'])
            self.assertEqual(single['routesByStart']['N31']['routeNodes'],
                             ['N31', 'N38', 'N11', 'EXIT_S'])
            segments = {e['edgeId']: [i + 1 for i in e['ledLogicalIndices']]
                        for e in single['directedEdges']}
            self.assertEqual(segments['E13'], list(range(83, 89)))
            self.assertEqual(segments['E20'], list(range(88, 95)))
            self.assertEqual(segments['E16'], [94, 95, 96])
            self.assertEqual(segments['E10'], list(range(22, 7, -1)))
            self.assertNotIn('N3', plan('FLM-03')['routesByStart'])
            self.assertNotIn('N7', plan('FLM-04', 'FLM-07')['routesByStart'].get('N3', {}).get('routeNodes', []))
            self.assertNotIn('N11', plan('FLM-04', 'FLM-11')['routesByStart'].get('N31', {}).get('routeNodes', []))
        finally:
            hardware.__path__ = old
            sys.path.remove(str(project))


if __name__ == '__main__':
    unittest.main()
