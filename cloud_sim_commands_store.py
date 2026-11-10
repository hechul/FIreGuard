"""Private RPC adapter for short-lived, isolated hardware simulation commands."""
from __future__ import annotations
from uuid import UUID
from cloud_store import StoreUnavailable, SupabaseStore


class SimulationCommandStore:
    def __init__(self, store: SupabaseStore):
        self.store = store

    @staticmethod
    def _uuid(value: str) -> str:
        try:
            return str(UUID(value))
        except (TypeError, ValueError, AttributeError):
            raise ValueError('Invalid command identifier.') from None

    def create(self, device_id: str, command_id: str, start_node: str, fire_node: str) -> dict:
        result = self.store._request('rpc/sim_command_create', {
            'p_device_id': self.store._device_id(device_id), 'p_id': self._uuid(command_id),
            'p_start_node': start_node, 'p_fire_node': fire_node,
        })
        if not isinstance(result, dict):
            raise StoreUnavailable('Invalid simulation command result.')
        return result

    def claim(self, device_id: str) -> dict | None:
        result = self.store._request('rpc/sim_command_claim', {'p_device_id': self.store._device_id(device_id)})
        if result is not None and not isinstance(result, dict):
            raise StoreUnavailable('Invalid simulation claim result.')
        return result

    def complete(self, device_id: str, command_id: str, claim_token: str, result: dict) -> dict:
        response = self.store._request('rpc/sim_command_complete', {
            'p_device_id': self.store._device_id(device_id), 'p_id': self._uuid(command_id),
            'p_claim_token': self._uuid(claim_token), 'p_result': result,
        })
        if not isinstance(response, dict):
            raise StoreUnavailable('Invalid simulation completion result.')
        return response

    def latest(self, device_id: str) -> dict | None:
        result = self.store._request('rpc/sim_command_latest', {'p_device_id': self.store._device_id(device_id)})
        if result is not None and not isinstance(result, dict):
            raise StoreUnavailable('Invalid simulation status result.')
        return result
