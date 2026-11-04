"""Per-request simulation replay. No real state, DB, or process globals are mutated."""
from __future__ import annotations

from copy import deepcopy
import math
from state_manager import SimulationState

MAX_ACTIONS = 100


def _boolean(body, key):
    value = body.get(key)
    if type(value) is not bool:
        raise ValueError(f'{key} must be a boolean')
    return value


def _id(body, key):
    value = body.get(key)
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError(f'{key} must be an identifier')
    return value


def _scenario(state, name):
    if name in ('normal', 'east_exit_fire', 'ticket_fire', 'cinema4_fire', 'large_fire',
                'east_shutter', 'mid_route_block', 'crowd_congestion', 'fallback_toilet',
                'fallback_descender', 'no_route', 'server_off', 'fire_server_off',
                'pi_off', 'sensor_fault'):
        state.reset(clear_events=False)
    if name == 'normal':
        return
    if name in ('east_exit_fire', 'ticket_fire', 'cinema4_fire', 'fire_server_off'):
        state.set_node_fire({'east_exit_fire': 'N10', 'ticket_fire': 'N14',
                             'cinema4_fire': 'N9', 'fire_server_off': 'N10'}[name], True, source='SCENARIO')
        if name == 'fire_server_off':
            state.set_connection('server', False, source='SCENARIO')
    elif name == 'large_fire':
        state.set_node_fire('N10', True, source='SCENARIO')
        state.set_node_fire('N7', True, source='SCENARIO')
    elif name == 'east_shutter':
        state.set_shutter('SH-02', True, source='SCENARIO')
    elif name == 'mid_route_block':
        state.set_manual_edge('E02', True)
    elif name == 'crowd_congestion':
        state.set_edge_weight('E02', 14.0, source='SCENARIO')
        state.set_edge_weight('E03', 8.0, source='SCENARIO')
    elif name in ('fallback_toilet', 'fallback_descender', 'no_route'):
        edges = ['E03', 'E09', 'E12', 'E16']
        if name in ('fallback_descender', 'no_route'):
            edges.extend(['E21', 'E22'])
        if name == 'no_route':
            edges.append('E23')
        for edge in edges:
            state.set_manual_edge(edge, True)
    elif name in ('server_off', 'server_on', 'pi_off', 'pi_on'):
        state.set_connection('server' if name.startswith('server') else 'pi', name.endswith('_on'), source='SCENARIO')
    elif name in ('sensor_fault', 'sensor_recover'):
        state.set_sensor_connection('FLM-15', name == 'sensor_recover', source='SCENARIO')
    else:
        raise ValueError('알 수 없는 시나리오입니다.')


def _apply(state, item):
    if not isinstance(item, dict) or set(item) != {'path', 'body'} or not isinstance(item['body'], dict):
        raise ValueError('올바른 시뮬레이션 요청이 필요합니다.')
    path, body = item['path'], item['body']
    if not isinstance(path, str):
        raise ValueError('요청 경로가 잘못되었습니다.')
    if path == '/api/simulation/scenario':
        _scenario(state, _id(body, 'scenarioId'))
    elif path == '/api/simulation/start-node':
        state.set_start_node(_id(body, 'nodeId'), source='SIM')
    elif path == '/api/simulation/flame':
        state.set_flame(_id(body, 'sensorId'), _boolean(body, 'active'), source='SIM')
    elif path == '/api/simulation/node-fire':
        state.set_node_fire(_id(body, 'nodeId'), _boolean(body, 'active'), source='SIM')
    elif path == '/api/simulation/shutter':
        state.set_shutter(_id(body, 'shutterId'), _boolean(body, 'closed'), source='SIM')
    elif path == '/api/simulation/manual-edge':
        state.set_manual_edge(_id(body, 'edgeId'), _boolean(body, 'blocked'))
    elif path == '/api/simulation/connection':
        state.set_connection(_id(body, 'target'), _boolean(body, 'connected'), source='SIM')
    elif path == '/api/simulation/sensor-connection':
        state.set_sensor_connection(_id(body, 'sensorId'), _boolean(body, 'connected'), source='SIM')
    elif path == '/api/simulation/edge-weight':
        weight = body.get('weight')
        if weight is not None and (type(weight) not in (int, float) or not math.isfinite(weight)):
            raise ValueError('weight must be a number or null')
        state.set_edge_weight(_id(body, 'edgeId'), weight, source='SIM')
    elif path == '/api/simulation/reset':
        value = body.get('clearEvents', False)
        if type(value) is not bool:
            raise ValueError('clearEvents must be a boolean')
        state.reset(clear_events=value)
    else:
        raise ValueError('지원하지 않는 시뮬레이션 동작입니다.')


def simulate(floorplan, payload):
    if not isinstance(payload, dict) or set(payload) - {'history', 'action'}:
        raise ValueError('잘못된 시뮬레이션 요청입니다.')
    history = payload.get('history', [])
    action = payload.get('action')
    if not isinstance(history, list) or len(history) > MAX_ACTIONS:
        raise ValueError('시뮬레이션 기록이 너무 깁니다. 정상 시나리오로 초기화하세요.')
    if action is not None:
        if len(history) >= MAX_ACTIONS:
            # A normal/reset action begins a fresh simulation without requiring
            # global state or dropping an unfinished operation silently.
            if action == {'path': '/api/simulation/scenario', 'body': {'scenarioId': 'normal'}}:
                history = []
            else:
                raise ValueError('시뮬레이션 기록이 너무 깁니다. 정상 시나리오로 초기화하세요.')
        history = [*history, action]
    state = SimulationState(deepcopy(floorplan))
    for item in history:
        _apply(state, item)
    return {'ok': True, 'state': state.snapshot(), 'floorplan': deepcopy(floorplan), 'history': history}
