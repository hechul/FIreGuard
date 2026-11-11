import unittest
from io import BytesIO
from hardware.real_allzone_reporter import make_payload, _check_ingest_result


class RealAllZoneReporterTests(unittest.TestCase):
    def test_http_success_does_not_imply_database_acceptance(self):
        _check_ingest_result(BytesIO(b'{"ok":true,"accepted":true}'))
        for body in (b'{"ok":true,"accepted":false,"reason":"stale"}',
                     b'{"ok":true}', b'invalid json'):
            with self.subTest(body=body), self.assertRaises(RuntimeError):
                _check_ingest_result(BytesIO(body))

    def test_partial_preserved_without_invented_single_route(self):
        base = {'startNode':'N4', 'routeNodes':['N4','EXIT'], 'ledIndices':[21],
                'ledLogicalIndices':[20], 'ledCommandAck':True}
        plan = {'routeStatus':'partial', 'availableExits':['EXIT'], 'guidedNodes':['N4'],
                'unreachableNodes':['N5'], 'blockedEdges':['E1'], 'ledExcludedEdges':['E2'],
                'directedEdges':[{'edgeId':'E3','from':'N4','to':'EXIT','exitNode':'EXIT',
                                  'ledLogicalIndices':[20]}],
                'ledLogicalIndices':[20], 'ledWireIndices':[21],
                'fireLedLogicalIndices':[5], 'fireLedWireIndices':[5]}
        payload = make_payload(base, plan)
        self.assertIsNone(payload['startNode'])
        self.assertEqual(payload['routeNodes'], [])
        self.assertEqual(payload['allZone']['routeStatus'], 'partial')
        self.assertEqual(payload['allZone']['unreachableNodes'], ['N5'])
        self.assertEqual(payload['allZone']['ledExcludedEdges'], ['E1', 'E2'])
        self.assertEqual(payload['ledIndices'], [21])
        self.assertEqual(payload['plannedLedLogicalIndices'], [20])

    def test_missing_plan_does_not_reuse_single_route(self):
        payload = make_payload({'routeNodes':['N1'], 'ledIndices':[], 'ledCommandAck':False}, None)
        self.assertNotIn('allZone', payload)
        self.assertEqual(payload['plannedLedIndices'], [])
        self.assertEqual(payload['routeNodes'], [])

if __name__ == '__main__': unittest.main()
