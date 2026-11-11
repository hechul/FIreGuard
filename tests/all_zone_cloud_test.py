"""All-zone Pi plans remain separate from acknowledged physical output."""
import unittest
from copy import deepcopy
from datetime import datetime, timezone

from cloud_bridge_contract_test import FLOOR, sample
from cloud_model import validate_hardware_telemetry, project_state
from route_service import FloorGraph


def report():
    data = sample('01_REAL_NORMAL.json')
    graph = FloorGraph(FLOOR)
    nodes = ['N4', 'N27', 'N25', 'N2', 'N23', 'N20', 'EXIT_NW']
    edges = []
    for start, end in zip(nodes, nodes[1:]):
        edge_id = next(e for other, _, e in graph.adjacency[start] if other == end)
        edges.append({'edgeId': edge_id, 'from': start, 'to': end, 'exitNode': 'EXIT_NW'})
    data.update(startNode=None, routeStatus='no_route', routeNodes=[], routeEdges=[],
                exitNode=None, destinationNode=None, destinationType=None,
                routeCost=None, routeMode='none', allZone={
                    'routingMode': 'all_zones_to_exits', 'routeStatus': 'ok',
                    'availableExits': ['EXIT_NW'], 'guidedNodes': nodes[:-1],
                    'unreachableNodes': [], 'directedEdges': edges, 'ledExcludedEdges': [],
                })
    return data


class AllZoneCloudTest(unittest.TestCase):
    def test_preserves_plan_and_legacy_neutral_route(self):
        data = report()
        normalized = validate_hardware_telemetry(data, FLOOR, data['deviceId'])
        self.assertEqual(normalized['hardware']['allZone'], data['allZone'])
        self.assertIsNone(normalized['route'])
        now = datetime.now(timezone.utc).isoformat()
        row = {'telemetry': normalized, 'received_at': now, 'observed_at': now, 'sequence': 1}
        state = project_state(FLOOR, row, [], data['deviceId'])
        self.assertEqual(state['cloud']['routeSource'], 'pi')
        self.assertIsNone(state['startNode'])
        self.assertEqual(state['cloud']['hardware']['allZone'], data['allZone'])

    def test_bad_plans_rejected(self):
        mutations = [
            lambda d: d['allZone'].update(secret='bad'),
            lambda d: d['allZone']['directedEdges'][0].update(edgeId='E999'),
            lambda d: d['allZone']['directedEdges'][0].update(to='N23'),
            lambda d: d['allZone']['directedEdges'][0].update(exitNode='EXIT_E'),
            lambda d: d['allZone']['ledExcludedEdges'].append('E26'),
            lambda d: d['allZone']['guidedNodes'].append({}),
            lambda d: d.update(startNode='N4'),
            lambda d: d.update(ledStatus='active', ledCommandAck=False),
            lambda d: d['flame']['FLM-04'].update(active=True, connected=False),
        ]
        for mutate in mutations:
            data = report()
            mutate(data)
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    validate_hardware_telemetry(data, FLOOR, data['deviceId'])

    def test_offline_latched_fire_invalidates_intersecting_plan(self):
        data = report()
        normalized = validate_hardware_telemetry(data, FLOOR, data['deviceId'])
        normalized['flame']['FLM-04'] = True
        normalized['hardware']['flame']['FLM-04']['connected'] = False
        now = datetime.now(timezone.utc).isoformat()
        row = {'telemetry': normalized, 'received_at': now, 'observed_at': now, 'sequence': 1}
        state = project_state(FLOOR, row, [], data['deviceId'])
        self.assertEqual(state['cloud']['routeSource'], 'pi_unverified')

    def test_legacy_report_still_accepted(self):
        data = sample('01_REAL_NORMAL.json')
        self.assertNotIn('allZone', validate_hardware_telemetry(data, FLOOR, data['deviceId'])['hardware'])


if __name__ == '__main__':
    unittest.main()
