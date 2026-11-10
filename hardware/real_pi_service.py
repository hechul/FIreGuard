#!/usr/bin/env python3
"""Independent REAL sensor state for the legacy Pi project.

Run separately on loopback; point the Pi GPIO reader at this service rather than
at the legacy SIM server. Does not start the Arduino, send telemetry, or expose
an internet API. Callers must use the same authoritative state for route/LED.
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request
from route_service import FloorGraph
from hardware.real_fire_latch import RealFireLatch


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class RealPiState:
    def __init__(self, floorplan, latch_path, *, start_node='N33', stale_after=15.0, clock=None):
        self.floorplan = deepcopy(floorplan)
        sensors = [s for s in self.floorplan.get('sensors', []) if s.get('type') == 'flame']
        self.sensor_nodes = {s['id']: s['node'] for s in sensors}
        if len(sensors) != 11 or len(self.sensor_nodes) != 11:
            raise ValueError('REAL floorplan must define 11 unique flame sensors')
        self.graph = FloorGraph(self.floorplan)
        if start_node not in self.graph.nodes:
            raise ValueError('Unknown start node')
        if any(node not in self.graph.nodes for node in self.sensor_nodes.values()):
            raise ValueError('Flame sensor references an unknown node')
        self.start_node = start_node
        opts = {'stale_after': stale_after}
        if clock is not None:
            opts['clock'] = clock
        self.latch = RealFireLatch(self.sensor_nodes, latch_path, **opts)
        self._lock = threading.RLock()
        self._observed_at = {sid: None for sid in self.sensor_nodes}

    def update(self, readings):
        if not isinstance(readings, dict) or not readings or any(
                sid not in self.sensor_nodes or type(value) is not bool for sid, value in readings.items()):
            raise ValueError('REAL samples must be known sensor IDs with boolean values')
        with self._lock:
            stamp = now_utc()
            # Even if saving an alarm fails, RealFireLatch retains its in-memory
            # alarm; remember the sample time and let the caller report failure.
            for sid in readings:
                self._observed_at[sid] = stamp
            self.latch.update(readings)
            return self.snapshot()

    def clear(self, sensor_ids):
        with self._lock:
            self.latch.clear(sensor_ids)
            return self.snapshot()

    def restore(self, sensor_ids):
        with self._lock:
            self.latch.restore(sensor_ids)
            return self.snapshot()

    def snapshot(self):
        with self._lock:
            data = self.latch.snapshot()
            blocked = {self.sensor_nodes[sid] for sid in data['latchedSensorIds']}
            route = self.graph.shortest_route(self.start_node, blocked_nodes=blocked, blocked_edges=set())
            if route is None:
                route = self.graph.shortest_fallback_route(self.start_node, blocked_nodes=blocked, blocked_edges=set())
            sensors = {sid: {'active': item['active'], 'connected': item['connected'],
                             'updatedAt': self._observed_at[sid]}
                       for sid, item in data['sensors'].items()}
            return {'operationMode': 'real', 'updatedAt': now_utc(), 'startNode': self.start_node,
                    'route': route.as_dict() if route else None, 'blockedNodes': sorted(blocked),
                    'blockedEdges': [], 'flameSensors': sensors,
                    'realFireDetected': data['realFireDetected'],
                    'realFireSensorIds': data['latchedSensorIds'],
                    'rawFlame': {sid: item['rawActive'] for sid, item in data['sensors'].items()},
                    'persistencePending': data['persistencePending'],
                    # Do not use a computed route to assert physical LED output.
                    'ledSafetyReady': all(item['connected'] for item in data['sensors'].values()) and not data['persistencePending']}


def create_app(real_state, local_token):
    if not isinstance(local_token, str) or len(local_token) < 32:
        raise ValueError('FIREGUARD_REAL_LOCAL_TOKEN must be at least 32 characters')
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024

    @app.before_request
    def loopback_only():
        if request.remote_addr not in ('127.0.0.1', '::1'):
            return jsonify(ok=False, error='local access only'), 403

    @app.after_request
    def no_cache(response):
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/api/real/state')
    def real_snapshot():
        return jsonify(real_state.snapshot())

    @app.post('/api/hardware/batch')
    def batch():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {'flame'}:
            return jsonify(ok=False, error='Expected flame samples'), 400
        try:
            snapshot = real_state.update(body['flame'])
        except (ValueError, TypeError):
            return jsonify(ok=False, error='Invalid sensor samples'), 400
        except OSError:
            return jsonify(ok=False, error='Fire latch persistence failed'), 503
        return jsonify(ok=True, state=snapshot)

    @app.post('/api/real/clear')
    def clear_real():
        supplied = request.headers.get('X-Fireguard-Local-Token', '')
        if not hmac.compare_digest(supplied.encode(), local_token.encode()):
            return jsonify(ok=False, error='Local authorization required'), 401
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {'sensorIds'}:
            return jsonify(ok=False, error='Expected sensor IDs'), 400
        try:
            state = real_state.clear(body['sensorIds'])
        except (ValueError, TypeError):
            return jsonify(ok=False, error='Sensor is active, stale, unknown, or not latched'), 409
        except OSError:
            return jsonify(ok=False, error='Fire latch persistence failed'), 503
        return jsonify(ok=True, state=state)

    @app.post('/api/real/restore')
    def restore_real():
        supplied = request.headers.get('X-Fireguard-Local-Token', '')
        if not hmac.compare_digest(supplied.encode(), local_token.encode()):
            return jsonify(ok=False, error='Local authorization required'), 401
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {'sensorIds'}:
            return jsonify(ok=False, error='Expected sensor IDs'), 400
        try:
            state = real_state.restore(body['sensorIds'])
        except (ValueError, TypeError):
            return jsonify(ok=False, error='Invalid sensor IDs'), 400
        except OSError:
            return jsonify(ok=False, error='Fire latch persistence failed'), 503
        return jsonify(ok=True, state=state)

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--floorplan', default='static/data/floorplan.json')
    parser.add_argument('--latch-file', default='runtime/real_fire_latches_v2.json')
    parser.add_argument('--start-node', default='N33')
    parser.add_argument('--port', type=int, default=5001)
    args = parser.parse_args()
    floorplan = json.loads(Path(args.floorplan).read_text(encoding='utf-8'))
    state = RealPiState(floorplan, args.latch_file, start_node=args.start_node)
    app = create_app(state, os.environ.get('FIREGUARD_REAL_LOCAL_TOKEN', ''))
    app.run(host='127.0.0.1', port=args.port, debug=False, use_reloader=False)


if __name__ == '__main__':
    main()
