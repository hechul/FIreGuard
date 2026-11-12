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
    def test_fallback_path_is_preserved_and_not_called_an_exit(self):
        data = report()
        plan = data['allZone']
        plan.update(availableExits=[], fallbackDestinations=['N5'],
                    guidedNodes=['N13', 'N35', 'N28'], unreachableNodes=[],
                    directedEdges=[
                        {'edgeId':'E15', 'from':'N13', 'to':'N35', 'exitNode':'N5'},
                        {'edgeId':'E30', 'from':'N35', 'to':'N28', 'exitNode':'N5'},
                        {'edgeId':'E21', 'from':'N28', 'to':'N5', 'exitNode':'N5'}])
        result = validate_hardware_telemetry(data, FLOOR, data['deviceId'])
        self.assertEqual(result['hardware']['allZone']['fallbackDestinations'], ['N5'])
        self.assertEqual(result['hardware']['allZone']['availableExits'], [])

    def test_fallback_must_be_configured_unblocked_and_reached(self):
        data = report()
        plan = data['allZone']
        plan.update(availableExits=[], fallbackDestinations=['N5'], guidedNodes=['N28'],
                    unreachableNodes=[], directedEdges=[{'edgeId':'E21', 'from':'N28', 'to':'N5', 'exitNode':'N5'}])
        for mutate in (lambda d: d['allZone'].update(fallbackDestinations=['N13']),
                       lambda d: d['allZone']['directedEdges'][0].update(exitNode='N6'),
                       lambda d: d.update(blockedNodes=['N5']),
                       lambda d: d['allZone'].update(guidedNodes=['N28','N5'])):
            candidate = deepcopy(data); mutate(candidate)
            with self.assertRaises(ValueError):
                validate_hardware_telemetry(candidate, FLOOR, candidate['deviceId'])

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
        self.assertEqual(state['overallStatus'], 'normal')

    def test_fire_with_all_zone_plan_is_not_misreported_as_no_route(self):
        data = report()
        data['flame']['FLM-10']['active'] = True
        data['blockedNodes'] = ['N10']
        data['allZone']['routeStatus'] = 'partial'
        data['allZone']['unreachableNodes'] = ['N31']
        normalized = validate_hardware_telemetry(data, FLOOR, data['deviceId'])
        now = datetime.now(timezone.utc).isoformat()
        row = {'telemetry': normalized, 'received_at': now, 'observed_at': now, 'sequence': 1}
        state = project_state(FLOOR, row, [], data['deviceId'])
        self.assertTrue(state['realFireDetected'])
        self.assertEqual(state['overallStatus'], 'fire')
        self.assertEqual(state['cloud']['hardware']['allZone']['routeStatus'], 'partial')

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
