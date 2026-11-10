"""Private REAL-latch clear-command RPC adapter.

This module never changes device_state or events. A command only asks the Pi to
verify live inputs and, if permitted, clear its own persistent latch. The caller
must authenticate operator/device requests and bind tokens to a device first.
"""
from __future__ import annotations

import re
from uuid import UUID
from cloud_store import StoreUnavailable, SupabaseStore

_SENSOR = re.compile(r'FLM-(?:0[1-9]|1[01])\Z')


class RealClearCommandStore:
    def __init__(self, store: SupabaseStore):
        self.store = store

    @staticmethod
    def _uuid(value: str) -> str:
        try:
            return str(UUID(value))
        except (TypeError, ValueError, AttributeError):
            raise ValueError('Invalid REAL clear command identifier.') from None

    @staticmethod
    def _sensors(value: object) -> list[str]:
        if (not isinstance(value, list) or not 1 <= len(value) <= 11
                or not all(isinstance(s, str) and _SENSOR.fullmatch(s) for s in value)
                or len(set(value)) != len(value)):
            raise ValueError('Select one or more distinct registered flame sensors.')
        return sorted(value)

    def create(self, device_id: str, command_id: str, sensor_ids: list[str]) -> dict:
        result = self.store._request('rpc/real_clear_create', {
            'p_device_id': self.store._device_id(device_id), 'p_id': self._uuid(command_id),
            'p_sensor_ids': self._sensors(sensor_ids),
        })
        if not isinstance(result, dict):
            raise StoreUnavailable('Invalid REAL clear creation result.')
        return result

    def claim(self, device_id: str) -> dict | None:
        result = self.store._request('rpc/real_clear_claim', {'p_device_id': self.store._device_id(device_id)})
        if result is not None and not isinstance(result, dict):
            raise StoreUnavailable('Invalid REAL clear claim result.')
        return result

    def complete(self, device_id: str, command_id: str, claim_token: str, result: dict) -> dict:
        if (not isinstance(result, dict) or set(result) != {'status', 'message', 'clearedSensorIds', 'rejectedSensorIds'}
                or result['status'] not in ('completed', 'rejected', 'failed')
                or not isinstance(result['message'], str) or len(result['message']) > 500):
            raise ValueError('Invalid REAL clear result.')
        cleared, rejected = result['clearedSensorIds'], result['rejectedSensorIds']
        if (not isinstance(cleared, list) or not isinstance(rejected, list)
                or len(cleared) + len(rejected) > 11
                or any(not isinstance(s, str) or not _SENSOR.fullmatch(s) for s in cleared + rejected)
                or len(set(cleared + rejected)) != len(cleared) + len(rejected)
                or (result['status'] == 'completed' and (not cleared or rejected))
                or (result['status'] == 'rejected' and (cleared or not rejected))):
            raise ValueError('Invalid REAL clear result sensors.')
        response = self.store._request('rpc/real_clear_complete', {
            'p_device_id': self.store._device_id(device_id), 'p_id': self._uuid(command_id),
            'p_claim_token': self._uuid(claim_token), 'p_result': result,
        })
        if not isinstance(response, dict):
            raise StoreUnavailable('Invalid REAL clear completion result.')
        return response

    def latest(self, device_id: str) -> dict | None:
        result = self.store._request('rpc/real_clear_latest', {'p_device_id': self.store._device_id(device_id)})
        if result is not None and not isinstance(result, dict):
            raise StoreUnavailable('Invalid REAL clear status result.')
        return result
