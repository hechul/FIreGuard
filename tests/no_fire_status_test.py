"""An absent evacuation plan is not a fire evacuation failure when idle."""
from copy import deepcopy
from datetime import datetime, timezone
import unittest

from cloud_bridge_contract_test import FLOOR, sample
from cloud_model import validate_hardware_telemetry, project_state
from state_manager import SimulationState


class NoFireStatusTest(unittest.TestCase):
    def test_local_no_fire_without_route_is_normal(self):
        model = SimulationState(deepcopy(FLOOR))
        model.route = None
        self.assertEqual(model.snapshot()['overallStatus'], 'normal')
        sensor = next(iter(model.flame_sensors.values()))
        sensor.update(active=True, connected=True)
        self.assertEqual(model.snapshot()['overallStatus'], 'no_route')
        sensor.update(active=False)
        self.assertEqual(model.snapshot()['overallStatus'], 'normal')

    def test_cloud_idle_empty_plan_and_fire_empty_plan(self):
        for all_zone in (False, True):
            for fire in (False, True):
                with self.subTest(all_zone=all_zone, fire=fire):
                    data = sample('01_REAL_NORMAL.json')
                    data['flame']['FLM-04']['active'] = fire
                    data['blockedNodes'] = ['N4'] if fire else []
                    data.update(startNode=None, routeStatus='no_route', routeNodes=[], routeEdges=[],
                                exitNode=None, destinationNode=None, destinationType=None,
                                routeCost=None, routeMode='none')
                    if all_zone:
                        data['allZone'] = {'routingMode':'all_zones_to_exits', 'routeStatus':'no_route',
                            'availableExits':[], 'guidedNodes':[], 'unreachableNodes':[],
                            'directedEdges':[], 'ledExcludedEdges':[]}
                    normalized = validate_hardware_telemetry(data,FLOOR,data['deviceId'])
                    now = datetime.now(timezone.utc).isoformat()
                    row = {'telemetry':normalized,'received_at':now,'observed_at':now,'sequence':1}
                    state = project_state(FLOOR,row,[],data['deviceId'])
                    self.assertEqual(state['overallStatus'],'no_route' if fire else 'normal')
                    self.assertIsNone(state['route'])

    def test_cloud_without_telemetry_stays_unknown(self):
        self.assertEqual(project_state(FLOOR,None,[],'pi-01')['overallStatus'],'unknown')
