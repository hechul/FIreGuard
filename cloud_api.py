"""Stateless, authenticated hardware ingestion for Vercel + Supabase."""
from __future__ import annotations

import hmac
import os
import re
import base64
import json

from flask import jsonify, request

from cloud_model import MAPPING_VERSION, cloud_floorplan, project_state, validate_telemetry
from cloud_store import StoreUnavailable, SupabaseStore


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
            if request.method == 'GET' and request.path == '/api/state':
                return jsonify(snapshot())
            if request.method == 'GET' and request.path == '/api/floorplan':
                return jsonify(plan)
            if request.method == 'POST' and request.path in ('/api/hardware/telemetry', '/api/hardware/batch'):
                token = os.environ.get('FIREGUARD_DEVICE_TOKEN', '')
                if len(token) < 32:
                    raise StoreUnavailable('장치 인증키를 32자 이상으로 설정하세요.')
                supplied = request.headers.get('Authorization', '')
                if not hmac.compare_digest(supplied.encode(), ('Bearer ' + token).encode()):
                    return jsonify(ok=False, error='장치 인증이 필요합니다.'), 401
                data = validate_telemetry(request.get_json(silent=True), plan, device_id())
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
