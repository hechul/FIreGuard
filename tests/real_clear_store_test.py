import unittest
from unittest.mock import Mock
from uuid import uuid4

from cloud_real_clear_store import RealClearCommandStore
from cloud_store import StoreUnavailable, SupabaseStore


class RealClearStoreTest(unittest.TestCase):
    def setUp(self):
        self.client = SupabaseStore('https://example.supabase.co', 'server-only')
        self.client._request = Mock()
        self.store = RealClearCommandStore(self.client)
        self.id, self.token = str(uuid4()), str(uuid4())

    def test_create_normalizes_sensor_order_and_uses_isolated_rpc(self):
        self.client._request.return_value = {'id': self.id, 'status': 'pending'}
        self.store.create('pi-01', self.id, ['FLM-10', 'FLM-01'])
        self.client._request.assert_called_once_with('rpc/real_clear_create', {'p_device_id':'pi-01', 'p_id':self.id, 'p_sensor_ids':['FLM-01','FLM-10']})

    def test_invalid_sensor_or_device_fails_before_request(self):
        for sensors in ([], ['FLM-01','FLM-01'], ['FLM-12'], ['N10'], [None], 'FLM-01'):
            with self.subTest(sensors=sensors), self.assertRaises(ValueError):
                self.store.create('pi-01', self.id, sensors)
        with self.assertRaises(ValueError): self.store.claim('bad/device')
        self.client._request.assert_not_called()

    def test_claim_and_latest_null(self):
        self.client._request.return_value = None
        self.assertIsNone(self.store.claim('pi-01'))
        self.assertIsNone(self.store.latest('pi-01'))

    def test_complete_passes_claim_and_result(self):
        result={'status':'completed','message':'ok','clearedSensorIds':['FLM-01'],'rejectedSensorIds':[]}
        self.client._request.return_value = {'id':self.id,'status':'completed'}
        self.store.complete('pi-01',self.id,self.token,result)
        self.client._request.assert_called_once_with('rpc/real_clear_complete', {'p_device_id':'pi-01','p_id':self.id,'p_claim_token':self.token,'p_result':result})

    def test_complete_rejects_conflicting_sensor_results_and_extra_fields(self):
        for result in [
            {'status':'completed','message':'ok','clearedSensorIds':['FLM-01'],'rejectedSensorIds':['FLM-01']},
            {'status':'completed','message':'ok','clearedSensorIds':[],'rejectedSensorIds':[]},
            {'status':'rejected','message':'no','clearedSensorIds':[],'rejectedSensorIds':[]},
            {'status':'completed','message':'ok','clearedSensorIds':[],'rejectedSensorIds':[],'extra':'x'},
        ]:
            with self.assertRaises(ValueError): self.store.complete('pi-01',self.id,self.token,result)
        self.client._request.assert_not_called()

    def test_bad_rpc_result_fails_closed(self):
        self.client._request.return_value = []
        with self.assertRaises(StoreUnavailable): self.store.claim('pi-01')

if __name__ == '__main__': unittest.main()
