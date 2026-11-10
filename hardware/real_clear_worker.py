#!/usr/bin/env python3
"""Poll authenticated REAL-clear requests and forward once to the local service.

This worker does not read GPIO, calculate paths or command LEDs. A durable
write-ahead ledger prevents automatic replay after an ambiguous interruption.
Use only with the matching localhost REAL service; never use on its own as an
alarm or as evidence of a physical sensor/LED state.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

SENSOR = re.compile(r'FLM-(?:0[1-9]|1[01])\Z')


def validate_origin(url, *, local=False):
    if not isinstance(url, str): raise ValueError('Invalid service URL')
    parsed = urlsplit(url)
    expected = ('http', {'127.0.0.1', 'localhost', '::1'}) if local else ('https', None)
    if (parsed.scheme != expected[0] or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment
            or (local and parsed.hostname not in expected[1])):
        raise ValueError('Invalid service URL')
    return url.rstrip('/')


def uuid_text(value):
    try: return str(UUID(value))
    except (ValueError, TypeError, AttributeError): raise ValueError('Invalid command identifier') from None


def parse_command(value, *, now=None):
    if not isinstance(value, dict) or set(value) != {'id', 'claimToken', 'sensorIds', 'expiresAt'}:
        raise ValueError('Invalid command')
    command_id, claim = uuid_text(value['id']), uuid_text(value['claimToken'])
    sensors = value['sensorIds']
    if (not isinstance(sensors, list) or not 1 <= len(sensors) <= 11
            or any(not isinstance(s, str) or not SENSOR.fullmatch(s) for s in sensors)
            or len(set(sensors)) != len(sensors)):
        raise ValueError('Invalid sensor list')
    try:
        expires = datetime.fromisoformat(value['expiresAt'].replace('Z', '+00:00'))
    except (TypeError, ValueError, AttributeError): raise ValueError('Invalid expiry') from None
    if expires.tzinfo is None: raise ValueError('Invalid expiry')
    now = now or datetime.now(timezone.utc)
    return {'id':command_id, 'claimToken':claim, 'sensorIds':sorted(sensors),
            'expiresAt':expires.isoformat(), 'expired':expires <= now}


def http_json(url, *, headers, payload=None, timeout=3):
    data = None if payload is None else json.dumps(payload, allow_nan=False).encode('utf-8')
    all_headers = {'Accept':'application/json', **headers}
    if data is not None: all_headers['Content-Type'] = 'application/json'
    # Never forward either token to a redirect target.
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl): return None
    with build_opener(NoRedirect()).open(Request(url, data=data, headers=all_headers), timeout=timeout) as response:
        return json.load(response)


class Ledger:
    """Bounded fail-closed durable journal with atomic replace and fsync."""
    def __init__(self, path):
        self.path = Path(path)
        self.entries = {}
        if self.path.exists():
            with self.path.open(encoding='utf-8') as file: data = json.load(file)
            if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('entries'), dict):
                raise RuntimeError('Invalid clear journal')
            self.entries = data['entries']
            for key, item in self.entries.items():
                if (uuid_text(key) != key or not isinstance(item, dict)
                        or set(item) != {'claimToken','sensorIds','phase','result'}
                        or item['phase'] not in ('started','finished','reported')):
                    raise RuntimeError('Invalid clear journal entry')
                uuid_text(item['claimToken'])
                if (not isinstance(item['sensorIds'], list) or not item['sensorIds']
                        or any(not isinstance(s, str) or not SENSOR.fullmatch(s) for s in item['sensorIds'])
                        or len(set(item['sensorIds'])) != len(item['sensorIds'])):
                    raise RuntimeError('Invalid clear journal sensors')
                if item['phase'] == 'started' and item['result'] is not None:
                    raise RuntimeError('Invalid clear journal result')
                if item['phase'] in ('finished','reported') and not isinstance(item['result'], dict):
                    raise RuntimeError('Invalid clear journal result')

    def persist(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent,
                                             prefix='.real-clear-', suffix='.tmp', delete=False) as handle:
                tmp = handle.name
                os.fchmod(handle.fileno(), 0o600)
                json.dump({'version':1, 'entries':self.entries}, handle, sort_keys=True)
                handle.flush(); os.fsync(handle.fileno())
            os.replace(tmp, self.path); tmp = None
            # Ensure the replace survives an ordinary power loss when supported.
            fd = os.open(self.path.parent, os.O_RDONLY)
            try: os.fsync(fd)
            finally: os.close(fd)
        finally:
            if tmp is not None:
                try: os.unlink(tmp)
                except FileNotFoundError: pass

    def begin(self, command):
        if command['id'] in self.entries: return False
        if len(self.entries) >= 1000: raise RuntimeError('Clear journal is full')
        self.entries[command['id']] = {'claimToken':command['claimToken'],
                                      'sensorIds':command['sensorIds'], 'phase':'started', 'result':None}
        try: self.persist()
        except Exception:
            # If replace/fsync outcome is uncertain, do not touch the local service.
            self.entries.pop(command['id'], None)
            raise
        return True

    def finish(self, command_id, result):
        record = self.entries[command_id]
        previous = (record['phase'], record['result'])
        record['phase'], record['result'] = 'finished', result
        try: self.persist()
        except Exception:
            record['phase'], record['result'] = previous
            raise

    def mark_reported(self, command_id):
        self.entries[command_id]['phase'] = 'reported'
        try: self.persist()
        except Exception:
            self.entries[command_id]['phase'] = 'finished'
            raise


def outcome(status, message, cleared=None, rejected=None):
    return {'status':status, 'message':message, 'clearedSensorIds':cleared or [],
            'rejectedSensorIds':rejected or []}


class Worker:
    def __init__(self, cloud, local, device_token, local_token, ledger, *, http=http_json, clock=None):
        self.cloud, self.local = validate_origin(cloud), validate_origin(local, local=True)
        if not isinstance(device_token, str) or len(device_token) < 32 or not isinstance(local_token, str) or len(local_token) < 32:
            raise ValueError('Both device and local tokens must contain at least 32 characters')
        if device_token == local_token:
            raise ValueError('Device and local tokens must differ')
        self.device_headers = {'Authorization':'Bearer '+device_token}
        self.local_headers = {'X-Fireguard-Local-Token':local_token}
        self.ledger, self.http = ledger, http
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _report(self, cmd_id, record):
        data = {'id':cmd_id, 'claimToken':record['claimToken'], 'result':record['result']}
        response = self.http(self.cloud+'/api/hardware/real-clear-result', headers=self.device_headers, payload=data)
        if not isinstance(response, dict) or response.get('ok') is not True:
            raise RuntimeError('Clear acknowledgement failed')
        self.ledger.mark_reported(cmd_id)

    def recover(self):
        """No network claim or local mutation until all prior reports settle."""
        for cmd_id, record in list(self.ledger.entries.items()):
            if record['phase'] == 'started':
                # The local request may or may not have completed; never replay it.
                self.ledger.finish(cmd_id, outcome('failed','처리 결과를 확인할 수 없습니다. 실제 센서 상태를 확인하세요.'))
            if record['phase'] == 'finished': self._report(cmd_id, record)

    def poll_once(self):
        self.recover()
        response = self.http(self.cloud+'/api/hardware/real-clear-command', headers=self.device_headers)
        if not isinstance(response, dict) or response.get('ok') is not True or 'command' not in response:
            raise RuntimeError('Invalid clear queue response')
        if response['command'] is None: return None
        command = parse_command(response['command'], now=self.clock())
        if not self.ledger.begin(command):
            # A duplicate must never trigger another local clear.
            self.recover()
            return None
        if command['expired'] or datetime.fromisoformat(command['expiresAt']) <= self.clock():
            result = outcome('rejected','요청 시간이 만료되어 실행하지 않았습니다.', rejected=command['sensorIds'])
        else:
            try:
                data = self.http(self.local+'/api/real/clear', headers=self.local_headers,
                                 payload={'sensorIds':command['sensorIds']}, timeout=3)
                state = data.get('state') if isinstance(data, dict) else None
                remaining = state.get('realFireSensorIds') if isinstance(state, dict) else None
                if (not isinstance(data, dict) or data.get('ok') is not True or not isinstance(remaining, list)
                        or any(s in remaining for s in command['sensorIds'])):
                    result = outcome('failed','해제 응답을 확인할 수 없습니다. 실제 상태를 확인하세요.')
                else:
                    result = outcome('completed','Pi가 실제 센서 상태를 확인하고 해제했습니다.',cleared=command['sensorIds'])
            except HTTPError as error:
                # 409 is the local service's explicit atomic precondition rejection.
                result = (outcome('rejected','센서가 감지 중이거나 입력이 오래되어 해제하지 않았습니다.', rejected=command['sensorIds'])
                          if error.code == 409 else outcome('failed','Pi 처리 결과를 확인할 수 없습니다. 실제 상태를 확인하세요.'))
            except Exception:
                # Request may have completed before a timeout: never replay.
                result = outcome('failed','Pi 처리 결과를 확인할 수 없습니다. 실제 상태를 확인하세요.')
        self.ledger.finish(command['id'], result)
        self._report(command['id'], self.ledger.entries[command['id']])
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cloud-url',required=True)
    parser.add_argument('--local-url',default='http://127.0.0.1:5001')
    parser.add_argument('--ledger',default='runtime/real_clear_ledger.json')
    parser.add_argument('--enable-real-clear',action='store_true')
    args=parser.parse_args()
    if not args.enable_real_clear: parser.error('--enable-real-clear 명시가 필요합니다')
    ledger_path=Path(args.ledger)
    ledger_path.parent.mkdir(parents=True,exist_ok=True)
    with open(str(ledger_path)+'.lock','a') as lock:
        try: fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise SystemExit('실제 화재 해제 프로그램이 이미 실행 중입니다')
        ledger=Ledger(ledger_path)
        worker=Worker(args.cloud_url,args.local_url,os.environ.get('FIREGUARD_DEVICE_TOKEN',''),
                      os.environ.get('FIREGUARD_REAL_LOCAL_TOKEN',''),ledger)
        print('실제 화재 해제 요청 대기 중',flush=True)
        while True:
            try: worker.poll_once()
            except KeyboardInterrupt: return 0
            except Exception as exc: print('실제 화재 해제 연결 확인 필요:',type(exc).__name__,flush=True)
            time.sleep(2)


if __name__=='__main__': raise SystemExit(main())
