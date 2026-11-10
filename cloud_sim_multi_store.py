"""Versioned multi-fire command adapter; legacy Pi claims remain singleton-only."""
from cloud_sim_commands_store import SimulationCommandStore
from cloud_store import StoreUnavailable


class MultiFireSimulationCommandStore(SimulationCommandStore):
    def create_v2(self, device_id, command_id, start_node, fire_nodes):
        if not isinstance(fire_nodes, list) or not fire_nodes or len(fire_nodes) > 11 or any(not isinstance(n, str) for n in fire_nodes) or len(set(fire_nodes)) != len(fire_nodes):
            raise ValueError('Invalid simulated fire nodes.')
        result = self.store._request('rpc/sim_command_create_v2', {
            'p_device_id': self.store._device_id(device_id), 'p_id': self._uuid(command_id),
            'p_start_node': start_node, 'p_fire_nodes': fire_nodes,
        })
        if not isinstance(result, dict):
            raise StoreUnavailable('Invalid multi-fire command result.')
        return result

    def claim_v2(self, device_id):
        result = self.store._request('rpc/sim_command_claim_v2', {'p_device_id': self.store._device_id(device_id)})
        if result is not None and not isinstance(result, dict):
            raise StoreUnavailable('Invalid multi-fire command claim.')
        return result
