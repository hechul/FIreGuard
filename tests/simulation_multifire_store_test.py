import unittest
from unittest.mock import Mock
from uuid import uuid4
from cloud_sim_multi_store import MultiFireSimulationCommandStore
from cloud_store import SupabaseStore

class MultiFireStoreTest(unittest.TestCase):
    def setUp(self):
        self.db = SupabaseStore('https://example.com', 'server-only')
        self.db._request = Mock(return_value={'id':'cmd'})
        self.store = MultiFireSimulationCommandStore(self.db)
    def test_v2_create_and_claim_use_versioned_rpcs(self):
        cid = str(uuid4())
        self.store.create_v2('pi-01',cid,'N4',['N7','N10'])
        self.db._request.assert_called_with('rpc/sim_command_create_v2', {'p_device_id':'pi-01','p_id':cid,'p_start_node':'N4','p_fire_nodes':['N7','N10']})
        self.store.claim_v2('pi-01')
        self.db._request.assert_called_with('rpc/sim_command_claim_v2', {'p_device_id':'pi-01'})
    def test_duplicate_empty_and_nonstring_rejected(self):
        for value in ([], ['N7','N7'], ['N7',None], [None]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.store.create_v2('pi-01',str(uuid4()),'N4',value)
        self.db._request.assert_not_called()

if __name__ == '__main__': unittest.main()
