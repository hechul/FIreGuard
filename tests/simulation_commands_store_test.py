import unittest
from uuid import uuid4
from unittest.mock import Mock

from cloud_sim_commands_store import SimulationCommandStore
from cloud_store import SupabaseStore, StoreUnavailable


class SimulationCommandStoreTest(unittest.TestCase):
    def setUp(self):
        self.db = SupabaseStore('https://example.supabase.co', 'server-only')
        self.db._request = Mock()
        self.store = SimulationCommandStore(self.db)
        self.id = str(uuid4())
        self.token = str(uuid4())

    def test_create_uses_separate_sim_rpc(self):
        self.db._request.return_value = {'id': self.id, 'status': 'pending'}
        self.store.create('pi-01', self.id, 'N4', 'N10')
        self.db._request.assert_called_once_with('rpc/sim_command_create', {
            'p_device_id': 'pi-01', 'p_id': self.id, 'p_start_node': 'N4', 'p_fire_node': 'N10'})

    def test_claim_and_latest_can_be_empty(self):
        self.db._request.return_value = None
        self.assertIsNone(self.store.claim('pi-01'))
        self.assertIsNone(self.store.latest('pi-01'))

    def test_complete_passes_claim_token_and_isolated_result(self):
        payload = {'status': 'completed', 'message': 'OK', 'routeNodes': ['N4'], 'ledCommandAck': False}
        self.db._request.return_value = {'id': self.id, 'status': 'completed'}
        self.store.complete('pi-01', self.id, self.token, payload)
        self.db._request.assert_called_once_with('rpc/sim_command_complete', {
            'p_device_id': 'pi-01', 'p_id': self.id, 'p_claim_token': self.token, 'p_result': payload})

    def test_rejects_invalid_ids_before_database(self):
        with self.assertRaises(ValueError):
            self.store.create('pi-01', 'bad', 'N4', 'N10')
        with self.assertRaises(ValueError):
            self.store.claim('pi/01')
        self.db._request.assert_not_called()

    def test_unexpected_database_response_fails_closed(self):
        self.db._request.return_value = []
        with self.assertRaises(StoreUnavailable):
            self.store.claim('pi-01')


if __name__ == '__main__':
    unittest.main()
