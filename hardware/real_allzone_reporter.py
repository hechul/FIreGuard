"""REAL-only all-zone telemetry using the existing sender's sequence owner."""
import json
import time
from urllib.request import Request, urlopen


def _check_ingest_result(response):
    """HTTP 200 alone does not mean the database accepted this snapshot."""
    try:
        result = json.loads(response.read(16385).decode('utf-8'))
    except (UnicodeError, ValueError, TypeError) as exc:
        raise RuntimeError('클라우드 저장 응답 형식 오류') from exc
    if not isinstance(result, dict) or result.get('ok') is not True or result.get('accepted') is not True:
        reason = result.get('reason') if isinstance(result, dict) else None
        if reason not in ('stale', 'duplicate'):
            reason = 'unknown'
        print('[CLOUD] DB에서 상태 보고를 거부했습니다:', reason, flush=True)
        raise RuntimeError('클라우드에서 상태 저장을 확인하지 못했습니다')


def make_payload(base, plan):
    """Keep the existing sensor/ACK snapshot while clearing single-route claims."""
    payload = dict(base)
    payload.update(startNode=None, routeNodes=[], routeEdges=[], exitNode=None,
                   destinationNode=None, destinationType=None, routeCost=None,
                   routeMode='none', routeStatus='no_route',
                   plannedLedLogicalIndices=[], plannedLedIndices=[],
                   plannedFireLogicalIndices=[], plannedFireLedIndices=[])
    if plan is not None:
        payload['allZone'] = {
            'routingMode': 'all_zones_to_exits',
            'routeStatus': plan['routeStatus'],
            'availableExits': list(plan['availableExits']),
            'guidedNodes': list(plan['guidedNodes']),
            'unreachableNodes': list(plan['unreachableNodes']),
            'directedEdges': [{k: edge[k] for k in ('edgeId', 'from', 'to', 'exitNode')}
                              for edge in plan['directedEdges']],
            'ledExcludedEdges': sorted(set(plan['ledExcludedEdges']) | set(plan['blockedEdges'])),
        }
        if 'fallbackDestinations' in plan:
            payload['allZone']['fallbackDestinations'] = list(plan['fallbackDestinations'])
        payload.update(plannedLedLogicalIndices=list(plan['ledLogicalIndices']),
                       plannedLedIndices=list(plan['ledWireIndices']),
                       plannedFireLogicalIndices=list(plan['fireLedLogicalIndices']),
                       plannedFireLedIndices=list(plan['fireLedWireIndices']),
                       ledMappingError=None)
    return payload


class AllZoneReporter:
    def __init__(self, reporter):
        self.reporter = reporter

    def maybe_report(self, snapshot, floor, layout, *, all_zone_plan=None,
                     led_status, command_ack=False, commanded_path=None,
                     commanded_fire=None, led_error=None, force=False):
        from hardware.cloud_telemetry import build_payload, version_hash
        if snapshot.get('operationMode') != 'real':
            raise ValueError('REAL telemetry required')
        if led_status == 'active' and (all_zone_plan is None or not command_ack):
            raise ValueError('Active LED requires an acknowledged all-zone plan')
        sender = self.reporter
        signature = {'flame': {k: (v.get('active'), v.get('connected'))
                               for k, v in snapshot['flameSensors'].items()},
                     'blockedNodes': snapshot.get('blockedNodes'),
                     'blockedEdges': snapshot.get('blockedEdges'), 'plan': all_zone_plan,
                     'ledStatus': led_status, 'ack': command_ack,
                     'path': commanded_path, 'red': commanded_fire, 'error': led_error}
        key = version_hash(signature)
        now = time.monotonic()
        if not force and key == sender.last_key and now - sender.last_success < sender.interval:
            return False
        if not force and sender.last_attempt > sender.last_success and now - sender.last_attempt < sender.interval:
            return False
        if not force and now - sender.last_attempt < 0.5:
            return False
        sender.last_attempt = now
        base = build_payload(snapshot, floor, layout, device_id=sender.device_id,
                             boot_id=sender.boot_id, sequence=sender._next_sequence(),
                             led_status=led_status, command_ack=command_ack,
                             commanded_path=commanded_path, commanded_fire=commanded_fire,
                             led_error=led_error)
        payload = make_payload(base, all_zone_plan)
        if sender.mode == 'preview':
            print('[CLOUD PREVIEW] ' + json.dumps(payload, ensure_ascii=False), flush=True)
        else:
            data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
            request = Request(sender.url, data=data, method='POST', headers={
                'Authorization': f'Bearer {sender.token}', 'Content-Type': 'application/json'})
            with urlopen(request, timeout=3.0) as response:
                if not 200 <= response.status < 300:
                    raise RuntimeError(f'Cloud HTTP {response.status}')
                _check_ingest_result(response)
            print(f'[CLOUD] 전송 성공 sequence={sender.sequence}', flush=True)
        sender.last_key = key
        sender.last_success = time.monotonic()
        return True
