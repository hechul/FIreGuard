#!/usr/bin/env python3
"""Start the legacy Pi Flask app with a local, fail-closed sensor feed guard.

Run in the legacy node1 project root using its virtualenv. This wrapper must be
started *instead of* app.py and bound to loopback. It observes successful local
GPIO reader batch deliveries; the guard does not control GPIO or LEDs and does
not authenticate a process on the same Pi. A received GPIO level alone cannot
prove a sensor or its wiring is physically healthy.
"""
from __future__ import annotations

import time
from flask import jsonify, request

EXPECTED = frozenset(f'FLM-{i:02}' for i in range(1, 12))
LOOPBACK = {'127.0.0.1', '::1'}


def install_guard(app, state, *, freshness_seconds=8.0, clock=time.monotonic):
    """Observe successful loopback /api/hardware/batch posts after startup.

    Each sensor must have a recent, boolean sample. The in-memory monotonic
    timestamps are intentionally lost on restart: no initial optimistic state.
    """
    if not 0 < freshness_seconds <= 30:
        raise ValueError('Invalid guard freshness')
    observed = {}

    @app.after_request
    def record_sensor_delivery(response):
        if (request.path != '/api/hardware/batch' or request.method != 'POST'
                or request.remote_addr not in LOOPBACK):
            return response
        # Fail closed if a real sensor input could not be reliably interpreted.
        payload = request.get_json(silent=True)
        flame = payload.get('flame') if isinstance(payload, dict) else None
        valid = (200 <= response.status_code < 300 and isinstance(flame, dict)
                 and bool(flame) and set(flame) <= EXPECTED
                 and all(type(value) is bool for value in flame.values()))
        with state._lock:
            if not valid:
                observed.clear()
            else:
                now = clock()
                for sensor in flame:
                    observed[sensor] = now
        return response

    @app.get('/api/hardware/guard')
    def hardware_guard():
        if request.remote_addr not in LOOPBACK:
            return jsonify(ok=False, ready=False, error='local access only'), 403
        with state._lock:
            now = clock()
            fresh = {sid for sid, timestamp in observed.items()
                     if 0 <= now - timestamp <= freshness_seconds}
            try:
                bank = (state.flame_sensors if state.operation_mode == 'real'
                        else state._mode_states['real']['flame_sensors'])
                complete = set(bank) == EXPECTED and all(
                    isinstance(bank[sid], dict)
                    and type(bank[sid].get('active')) is bool
                    and type(bank[sid].get('connected')) is bool
                    for sid in EXPECTED)
                fire = any(bank[sid]['active'] for sid in EXPECTED) if complete else True
                connected = complete and all(bank[sid]['connected'] for sid in EXPECTED)
            except (KeyError, TypeError, AttributeError):
                complete, fire, connected = False, True, False
            ready = (state.operation_mode == 'simulation' and fresh == EXPECTED
                     and complete and connected and not fire)
            if state.operation_mode != 'simulation':
                reason = 'Pi 로컬 서버가 SIMULATION 모드가 아닙니다'
            elif fresh != EXPECTED:
                reason = '실제 센서 11개 입력이 최근에 확인되지 않았습니다'
            elif not complete or not connected:
                reason = '실제 센서 상태가 불완전하거나 연결이 끊겼습니다'
            elif fire:
                reason = '실제 화재 센서가 감지 중입니다'
            else:
                reason = '실제 센서 입력 수신 중'
            return jsonify(ok=True, ready=ready, realFireDetected=fire,
                           reason=reason, freshSensors=len(fresh), requiredSensors=11)

    return hardware_guard


def main():
    # ``python -m hardware.pi_real_guard`` from node1 uses the legacy project.
    from app import app, state, socketio
    install_guard(app, state)
    socketio.run(app, host='127.0.0.1', port=5000, debug=False,
                 use_reloader=False, allow_unsafe_werkzeug=True)


if __name__ == '__main__':
    main()
