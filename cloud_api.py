"""Stateless, authenticated hardware ingestion for Vercel + Supabase."""
from __future__ import annotations

import hmac
import os
import re
import base64
import json
from uuid import uuid4

from flask import jsonify, request

from cloud_model import MAPPING_VERSION, cloud_floorplan, project_state, validate_telemetry, validate_hardware_telemetry
from cloud_store import StoreUnavailable, SupabaseStore
from cloud_simulation import simulate
from cloud_sim_commands_store import SimulationCommandStore
from cloud_sim_multi_store import MultiFireSimulationCommandStore
from cloud_sim_cancellation_store import SimulationCancellationStore


def enabled(app):
    return app.config.get('CLOUD_ENABLED', False)


def deployment_info():
    return {'buildId': 'fireguard-cloud-v2',
            'revision': os.environ.get('VERCEL_GIT_COMMIT_SHA') or None}


def install_cloud(app, original_floorplan):
    # Hosting markers take precedence over FIREGUARD_CLOUD=0 from local defaults.
    app.config['CLOUD_ENABLED'] = (
        os.environ.get('FIREGUARD_CLOUD', '').strip().lower() in ('1', 'true')
        or os.environ.get('VERCEL', '').strip().lower() in ('1', 'true')
        or os.environ.get('VERCEL_ENV', '').strip().lower() in ('production', 'preview')
    )
    app.config['MAX_CONTENT_LENGTH'] = 64 * 1024
    app.config['SIM_CONTROL_ENABLED'] = os.environ.get('FIREGUARD_SIM_CONTROL_ENABLED') == '1'
    plan = cloud_floorplan(original_floorplan)

    def device_id():
        value = os.environ.get('FIREGUARD_DEVICE_ID', 'pi-01')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value):
            raise StoreUnavailable('FIREGUARD_DEVICE_ID 설정을 확인하세요.')
        return value

    def store():
        if 'cloud_store' in app.extensions:
            return app.extensions['cloud_store']
        url = os.environ.get('SUPABASE_URL', '')
        key = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
        if not url or not key:
            raise StoreUnavailable('Supabase 서버 환경변수가 아직 설정되지 않았습니다.')
        return SupabaseStore(url, key)

    def stale_seconds():
        try:
            return max(5, min(300, int(os.environ.get('FIREGUARD_STALE_SECONDS', '15'))))
        except ValueError:
            return 15

    def snapshot():
        backend = store()
        did = device_id()
        preview = request.args.get('startNode')
        if preview is not None and preview not in {n['id'] for n in plan['nodes']}:
            raise ValueError('알 수 없는 startNode입니다.')
        return project_state(plan, backend.latest(did), backend.events(did), did, stale_seconds(), preview_start=preview)

    def sim_control_auth(kind):
        if os.environ.get('FIREGUARD_SIM_CONTROL_ENABLED') != '1':
            raise StoreUnavailable('실물 시험 연결 점검이 비활성화되어 있습니다.')
        key = 'FIREGUARD_SIM_OPERATOR_TOKEN' if kind == 'operator' else 'FIREGUARD_DEVICE_TOKEN'
        token = os.environ.get(key, '')
        if len(token) < 32:
            raise StoreUnavailable('시험 연결 인증 설정을 확인하세요.')
        if kind == 'operator' and hmac.compare_digest(token.encode(), os.environ.get('FIREGUARD_DEVICE_TOKEN', '').encode()):
            raise StoreUnavailable('운영자 키는 장치 키와 다르게 설정하세요.')
        return hmac.compare_digest(request.headers.get('Authorization', '').encode(), ('Bearer ' + token).encode())

    def sim_command_store():
        return app.extensions.get('sim_command_store') or SimulationCommandStore(store())

    def sim_multi_store():
        return app.extensions.get('sim_command_store') or MultiFireSimulationCommandStore(store())

    def sim_cancellation_store():
        return app.extensions.get('sim_cancellation_store') or SimulationCancellationStore(store())

    @app.get('/api/cloud/config')
    def public_config():
        if not enabled(app):
            return jsonify(enabled=False, **deployment_info())
        public_key = os.environ.get('SUPABASE_ANON_KEY', '')
        secret = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
        private_key = public_key.startswith('sb_secret_') or (bool(secret) and public_key == secret)
        if public_key.count('.') == 2:
            try:
                part = public_key.split('.')[1]
                claims = json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))
                private_key = private_key or claims.get('role') == 'service_role'
            except (ValueError, TypeError, AttributeError):
                pass
        if private_key:
            return jsonify(ok=False, error='SUPABASE_ANON_KEY에는 공개 키를 설정하세요. 서버 비밀 키는 사용할 수 없습니다.'), 503
        return jsonify(enabled=True, deviceId=device_id(), mappingVersion=MAPPING_VERSION,
                       supabaseUrl=os.environ.get('SUPABASE_URL', ''),
                       supabaseAnonKey=public_key,
                       staleAfterSeconds=stale_seconds(), **deployment_info())

    @app.get('/api/health')
    def health():
        return jsonify(ok=True, cloud=enabled(app), mappingVersion=MAPPING_VERSION, **deployment_info())

    @app.before_request
    def cloud_dispatch():
        if not enabled(app):
            return None
        if request.path.startswith('/socket.io'):
            return jsonify(ok=False, error='클라우드는 Supabase Realtime을 사용합니다.'), 404
        if not request.path.startswith('/api/'):
            return None
        try:
            if request.path in ('/api/sim-control/commands', '/api/sim-control/latest', '/api/sim-control/cancel',
                                '/api/hardware/sim-command', '/api/hardware/sim-command/check', '/api/hardware/sim-result'):
                operator = request.path.startswith('/api/sim-control/')
                if not sim_control_auth('operator' if operator else 'device'):
                    return jsonify(ok=False, error='시험 연결 인증이 필요합니다.'), 401
                commands = sim_command_store()
                if request.path == '/api/sim-control/commands' and request.method == 'POST':
                    body = request.get_json(silent=True)
                    allowed = {'N33','N10','N9','N34','N8','N35','N7','N36','N37','N38','N12','N13','N14','N15','N5','N6','N3','N19','N1','N20','N11','N23','N2','N25','N4','N27','N28','N29','N30','N31'}
                    fires = {'N20','N2','N3','N4','N5','N6','N7','N8','N9','N10','N11'}
                    if not isinstance(body, dict) or set(body) not in ({'startNode', 'fireNode'}, {'startNode', 'fireNodes'}):
                        raise ValueError('Pi에 등록된 출발점과 화재 센서 위치를 선택하세요.')
                    selected = body.get('fireNodes', [body.get('fireNode')])
                    if (not isinstance(body['startNode'], str) or body['startNode'] not in allowed
                            or not isinstance(selected, list) or not 1 <= len(selected) <= len(fires)
                            or any(not isinstance(node, str) or node not in fires for node in selected)
                            or len(set(selected)) != len(selected)):
                        raise ValueError('Pi에 등록된 출발점과 중복 없는 화재 센서 위치를 선택하세요.')
                    # Preview requests never control the device or write real
                    # state. Pi may be running SIM without a REAL cloud heartbeat;
                    # the Pi bridge validates its local mode before calculating.
                    command_id = str(uuid4())
                    result = (commands.create(device_id(), command_id, body['startNode'], selected[0])
                              if len(selected) == 1 else sim_multi_store().create_v2(device_id(), command_id, body['startNode'], selected))
                    return jsonify(ok=True, command=result)
                if request.path == '/api/sim-control/latest' and request.method == 'GET':
                    return jsonify(ok=True, command=commands.latest(device_id()))
                if request.path == '/api/sim-control/cancel' and request.method == 'POST':
                    body = request.get_json(silent=True)
                    if not isinstance(body, dict) or set(body) != {'id'}:
                        raise ValueError('시험 취소 요청이 올바르지 않습니다.')
                    return jsonify(ok=True, command=sim_cancellation_store().cancel(device_id(), body['id']))
                if request.path == '/api/hardware/sim-command/check' and request.method == 'POST':
                    body = request.get_json(silent=True)
                    if not isinstance(body, dict) or set(body) != {'id', 'claimToken'}:
                        raise ValueError('시험 명령 확인 요청이 올바르지 않습니다.')
                    return jsonify(ok=True, **sim_cancellation_store().check(device_id(), body['id'], body['claimToken']))
                if request.path == '/api/hardware/sim-command' and request.method == 'GET':
                    if request.args.get('version') not in (None, '2'):
                        raise ValueError('지원하지 않는 시험 프로토콜 버전입니다.')
                    return jsonify(ok=True, command=(sim_multi_store().claim_v2(device_id()) if request.args.get('version') == '2' else commands.claim(device_id())))
                if request.path == '/api/hardware/sim-result' and request.method == 'POST':
                    body = request.get_json(silent=True)
                    if not isinstance(body, dict) or set(body) != {'id', 'claimToken', 'result'} or not isinstance(body['result'], dict):
                        raise ValueError('시험 결과 형식이 잘못되었습니다.')
                    return jsonify(ok=True, command=commands.complete(device_id(), body['id'], body['claimToken'], body['result']))
                return jsonify(ok=False, error='지원하지 않는 요청입니다.'), 405
            if request.method == 'GET' and request.path == '/api/state':
                return jsonify(snapshot())
            if request.method == 'GET' and request.path == '/api/floorplan':
                return jsonify(plan)
            if request.method == 'POST' and request.path == '/api/cloud/simulation':
                # Never trust a client-provided real status: read the shared DB.
                # A disconnected Pi's old alarm remains visible in realState, but
                # does not block the user-requested isolated presentation mode.
                real = snapshot()
                if real['connections']['pi'] and real['realFireDetected']:
                    return jsonify(ok=False, error='실제 화재가 감지되어 REAL 모드로 전환합니다.', realState=real), 409
                result = simulate(original_floorplan, request.get_json(silent=True))
                # Recheck just before returning so a concurrent Pi report takes
                # priority over a calculation initiated before it arrived.
                real = snapshot()
                if real['connections']['pi'] and real['realFireDetected']:
                    return jsonify(ok=False, error='실제 화재가 감지되어 REAL 모드로 전환합니다.', realState=real), 409
                result['realState'] = real
                return jsonify(result)
            if request.method == 'POST' and request.path in ('/api/hardware/telemetry', '/api/hardware/batch'):
                token = os.environ.get('FIREGUARD_DEVICE_TOKEN', '')
                if len(token) < 32:
                    raise StoreUnavailable('장치 인증키를 32자 이상으로 설정하세요.')
                supplied = request.headers.get('Authorization', '')
                if not hmac.compare_digest(supplied.encode(), ('Bearer ' + token).encode()):
                    return jsonify(ok=False, error='장치 인증이 필요합니다.'), 401
                payload = request.get_json(silent=True)
                data = (validate_hardware_telemetry(payload, plan, device_id())
                        if isinstance(payload, dict) and 'operationMode' in payload
                        else validate_telemetry(payload, plan, device_id()))
                outcome = store().ingest(data)
                return jsonify(ok=True, **outcome)
            if request.method not in ('GET', 'HEAD', 'OPTIONS'):
                return jsonify(ok=False, error='클라우드는 실제 장비 관제 전용입니다. 시뮬레이션·지도 수정은 로컬에서 실행하세요.'), 409
            if request.path not in ('/api/cloud/config', '/api/health'):
                return jsonify(ok=False, error='지원하지 않는 클라우드 API입니다.'), 404
        except ValueError as error:
            return jsonify(ok=False, error=str(error)), 400
        except StoreUnavailable:
            return jsonify(ok=False, error='Supabase 연결/서버 설정을 확인하세요. 장비 상태를 불러오지 못했습니다.'), 503
        return None

    @app.after_request
    def no_state_cache(response):
        if request.path.startswith('/api/') or request.path == '/':
            response.headers['Cache-Control'] = 'no-store'
        response.headers['X-FireGuard-Build'] = deployment_info()['buildId']
        return response

    return plan
