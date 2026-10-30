#!/usr/bin/env python3
"""Send MOCK full snapshots to the REAL cloud dashboard; never accesses GPIO."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

MAPPING = json.loads((ROOT / "config" / "cloud_sensors.json").read_text(encoding="utf-8"))
SENSOR_IDS = tuple(sensor["id"] for sensor in MAPPING["sensors"])
MAPPING_VERSION = MAPPING["mappingVersion"]


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", required=True, help="Deployment origin, e.g. https://your-app.vercel.app")
    parser.add_argument("--active", action="append", choices=SENSOR_IDS, default=[], help="Repeat for multiple active sensors")
    parser.add_argument("--device-id", default=os.environ.get("FIREGUARD_DEVICE_ID", "pi-01"))
    parser.add_argument("--led-status", choices=("unknown", "applied", "error"), default="unknown")
    parser.add_argument("--route-file", type=Path, help="Optional valid route object including id, nodes, edges, cost and destinationId")
    parser.add_argument("--led-segments-file", type=Path, help="Optional JSON array of reported LED segment states")
    parser.add_argument("--led-error", default="MOCK output error", help="Used only with --led-status error")
    parser.add_argument("--repeat", type=float, help="Repeat interval in seconds; default sends once")
    parser.add_argument("--count", type=int, help="Limit repeated sends; otherwise --repeat runs until Ctrl+C")
    parser.add_argument("--dry-run", action="store_true", help="Print payload only; no token or network needed")
    args = parser.parse_args()
    parsed = urlparse(args.api)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        parser.error("--api must be a server URL without credentials, query or fragment")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        parser.error("Use HTTPS for deployed servers; HTTP is allowed only for localhost")
    if parsed.path not in {"", "/"}:
        parser.error("--api must be the origin without an API path")
    if args.repeat is not None and (args.repeat < 0.1 or not args.repeat < float("inf")):
        parser.error("--repeat must be a finite number of at least 0.1 seconds")
    if args.count is not None and args.count < 1:
        parser.error("--count must be positive")
    if args.count and args.count > 1 and args.repeat is None:
        parser.error("Use --repeat with --count greater than one")
    if args.led_status == "applied" and args.route_file is None:
        parser.error("--led-status applied requires --route-file; the tool does not invent an applied route")
    return args


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8")) if path else None


def make_payload(args, boot_id, sequence, route=None, segments=None):
    payload = {
        "deviceId": args.device_id,
        "bootId": boot_id,
        "sequence": sequence,
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "mappingVersion": MAPPING_VERSION,
        "flame": {sid: sid in args.active for sid in SENSOR_IDS},
        "startNode": route["nodes"][0] if route else "N33",
        "led": {
            "status": args.led_status,
            "routeId": route["id"] if route and args.led_status == "applied" else None,
            "segments": segments or [],
            "error": args.led_error if args.led_status == "error" else None,
        },
    }
    if route:
        payload["route"] = route
    return payload


def send(api, token, payload):
    request = Request(
        api.rstrip("/") + "/api/hardware/telemetry",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            data = json.load(response)
    except HTTPError as exc:
        # Never print a response body or authorization header containing secrets.
        raise RuntimeError(f"HTTP {exc.code}: check authentication, API contract and server configuration") from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise RuntimeError("Telemetry request failed; check connectivity and server logs") from None
    if not isinstance(data, dict) or data.get("ok") is False:
        raise RuntimeError("Server rejected telemetry; check server logs")
    return data


def main():
    args = parse_args()
    token = os.environ.get("FIREGUARD_DEVICE_TOKEN", "")
    if not args.dry_run and len(token) < 32:
        raise SystemExit("Set FIREGUARD_DEVICE_TOKEN (at least 32 characters) in the environment or local .env")
    try:
        route = load_json(args.route_file)
        segments = load_json(args.led_segments_file)
        if route is not None and (not isinstance(route, dict) or not route.get("id") or not route.get("nodes")):
            raise ValueError("invalid route")
        if segments is not None and not isinstance(segments, list):
            raise ValueError("invalid segments")
    except (OSError, ValueError, KeyError):
        raise SystemExit("Cannot load route/LED JSON files; check file shape and contents") from None
    print("MOCK telemetry: updates the REAL cloud screen. Use a test project/device.", file=sys.stderr)
    boot_id = str(uuid4())
    sequence = 0
    count = args.count if args.count is not None else (None if args.repeat else 1)
    try:
        while count is None or sequence < count:
            payload = make_payload(args, boot_id, sequence, route, segments)
            if args.dry_run:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                result = send(args.api, token, payload)
                print(f"sequence={sequence} accepted={result.get('accepted', 'see response contract')}")
            sequence += 1
            if count is None or sequence < count:
                time.sleep(args.repeat)
    except KeyboardInterrupt:
        return 0
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
