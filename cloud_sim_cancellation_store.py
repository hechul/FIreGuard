"""Private RPC adapter for invalidating and checking a SIM command lease."""
from cloud_sim_commands_store import SimulationCommandStore
from cloud_store import StoreUnavailable


class SimulationCancellationStore(SimulationCommandStore):
    def cancel(self, device_id: str, command_id: str) -> dict:
        result = self.store._request('rpc/sim_command_cancel', {
            'p_device_id': self.store._device_id(device_id), 'p_id': self._uuid(command_id),
        })
        if (not isinstance(result, dict) or not isinstance(result.get('status'), str)
                or type(result.get('cancelRequested')) is not bool):
            raise StoreUnavailable('Invalid simulation cancellation result.')
        return result

    def check(self, device_id: str, command_id: str, claim_token: str) -> dict:
        result = self.store._request('rpc/sim_command_check', {
            'p_device_id': self.store._device_id(device_id), 'p_id': self._uuid(command_id),
            'p_claim_token': self._uuid(claim_token),
        })
        if (not isinstance(result, dict) or type(result.get('active')) is not bool
                or type(result.get('cancelRequested')) is not bool):
            raise StoreUnavailable('Invalid simulation claim check result.')
        return result
