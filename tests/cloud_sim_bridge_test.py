import unittest
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from hardware.cloud_sim_bridge import report_result, run_command, validate_command


def command():
    return {'id': 'test', 'claimToken': 'secret', 'startNode': 'N1', 'fireNode': 'N7',
            'expiresAt': (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()}


class TestCloudSimBridge(unittest.TestCase):
    def test_result_matches_server_contract(self):
        payload = command()
        outcome = {'status': 'rejected', 'message': 'dry run', 'routeNodes': [], 'ledCommandAck': False}
        with patch('hardware.cloud_sim_bridge.request') as send:
            report_result('https://example.com', 'token', payload, outcome)
        send.assert_called_once_with('https://example.com/api/hardware/sim-result', token='token',
                                     data={'id': payload['id'], 'claimToken': payload['claimToken'], 'result': outcome})

    def test_dry_run_only_reads_local_state_and_never_reports_ack(self):
        fake = types.ModuleType('hardware.led_routes')
        fake.load_files = lambda: ({}, {'nodes': [{'id': 'N1'}],
                                        'sensors': [{'id': 'FLM-07', 'node': 'N7', 'type': 'flame'}]})
        fake.demo_snapshot = lambda floor, sensor, start: {'route': {'nodes': [start, 'N2', 'EXIT_NW']}}
        with patch('hardware.cloud_sim_bridge.request', return_value={
                'operationMode': 'simulation', 'realFireDetected': False}) as request, \
                patch.dict(sys.modules, {'hardware.led_routes': fake}):
            result = run_command(command(), local='http://127.0.0.1:5000')
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['routeNodes'], ['N1', 'N2', 'EXIT_NW'])
        self.assertFalse(result['ledCommandAck'])
        request.assert_called_once_with('http://127.0.0.1:5000/api/state', timeout=0.5)

    def test_expired_or_unsafe_mode_rejected(self):
        expired = command()
        expired['expiresAt'] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        with self.assertRaises(ValueError):
            validate_command(expired)
        for snapshot in ({'operationMode': 'real', 'realFireDetected': False},
                         {'operationMode': 'simulation', 'realFireDetected': True},
                         {'operationMode': 'simulation'}):
            with patch('hardware.cloud_sim_bridge.request', return_value=snapshot):
                with self.assertRaises(RuntimeError):
                    run_command(command(), local='http://127.0.0.1:5000')

    def test_no_route_stays_empty_and_new_unmapped_nodes_rejected(self):
        fake = types.ModuleType('hardware.led_routes')
        fake.load_files = lambda: ({}, {'nodes': [{'id': 'N1'}],
                                        'sensors': [{'id': 'FLM-07', 'node': 'N7', 'type': 'flame'}]})
        fake.demo_snapshot = lambda *args: {'route': None}
        with patch('hardware.cloud_sim_bridge.safe_snapshot'), patch.dict(sys.modules, {'hardware.led_routes': fake}):
            self.assertEqual(run_command(command(), local='http://127.0.0.1:5000')['routeNodes'], [])
            newer = command()
            newer['startNode'] = 'N40'
            with self.assertRaises(ValueError):
                run_command(newer, local='http://127.0.0.1:5000')


if __name__ == '__main__':
    unittest.main()
