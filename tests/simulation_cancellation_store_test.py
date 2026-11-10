import unittest
from unittest.mock import Mock
from uuid import uuid4
from cloud_sim_cancellation_store import SimulationCancellationStore
from cloud_store import SupabaseStore, StoreUnavailable

class CancellationStoreTest(unittest.TestCase):
    def setUp(self):
        self.db=SupabaseStore('https://example.supabase.co','server-only')
        self.db._request=Mock()
        self.s=SimulationCancellationStore(self.db)
        self.id=str(uuid4())
        self.claim=str(uuid4())
    def test_cancel_is_scoped_to_device_and_command(self):
        self.db._request.return_value={'id':self.id,'status':'claimed','cancelRequested':True}
        self.assertTrue(self.s.cancel('pi-01',self.id)['cancelRequested'])
        self.db._request.assert_called_once_with('rpc/sim_command_cancel',{'p_device_id':'pi-01','p_id':self.id})
    def test_check_requires_claim_token(self):
        self.db._request.return_value={'active':False,'cancelRequested':True}
        self.assertFalse(self.s.check('pi-01',self.id,self.claim)['active'])
        self.db._request.assert_called_once_with('rpc/sim_command_check',{'p_device_id':'pi-01','p_id':self.id,'p_claim_token':self.claim})
    def test_invalid_or_ambiguous_responses_fail_closed(self):
        for value in [None,{}, {'active':'false','cancelRequested':False}, {'active':True}]:
            self.db._request.return_value=value
            with self.assertRaises(StoreUnavailable): self.s.check('pi-01',self.id,self.claim)
    def test_identifiers_are_validated(self):
        with self.assertRaises(ValueError): self.s.cancel('pi-01','bad')
        with self.assertRaises(ValueError): self.s.check('bad/id',self.id,self.claim)
        self.db._request.assert_not_called()

if __name__ == '__main__': unittest.main()
