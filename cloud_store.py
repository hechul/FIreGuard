"""Small server-only Supabase REST adapter; never expose its key to a browser."""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


class StoreUnavailable(RuntimeError):
    """A database request failed. Messages deliberately omit response bodies/keys."""


class SupabaseStore:
    def __init__(self, url: str, key: str, timeout: float = 5):
        parsed = urlsplit(url)
        local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if (parsed.scheme != "https" and not local_http) or not parsed.hostname:
            raise ValueError("Supabase URL must use HTTPS (HTTP is allowed only for localhost).")
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise ValueError("Supabase URL must be a project origin without credentials or a path.")
        if not isinstance(key, str) or not key.strip():
            raise ValueError("A server-side Supabase key is required.")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("A positive request timeout is required.")
        self.url = url.rstrip("/")
        self._key = key.strip()
        self.timeout = timeout

    def _request(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        headers = {"apikey": self._key, "Accept": "application/json"}
        # Legacy service_role JWTs use Authorization. New sb_secret keys use apikey.
        if not self._key.startswith("sb_secret_"):
            headers["Authorization"] = f"Bearer {self._key}"
        data = None
        if payload is not None:
            data = json.dumps(payload, allow_nan=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = Request(self.url + "/rest/v1/" + path, data=data, headers=headers,
                      method="POST" if payload is not None else "GET")
        try:
            with urlopen(req, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise StoreUnavailable(f"Database request failed (HTTP {error.code}).") from None
        except (URLError, TimeoutError, OSError, ValueError, UnicodeError):
            raise StoreUnavailable("Database is temporarily unavailable.") from None

    @staticmethod
    def _device_id(device_id: str) -> str:
        if not isinstance(device_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", device_id):
            raise ValueError("Invalid device ID.")
        return device_id

    def ingest(self, telemetry: dict[str, Any]) -> dict[str, Any]:
        result = self._request("rpc/ingest_telemetry", {"p_telemetry": telemetry})
        if not isinstance(result, dict) or type(result.get("accepted")) is not bool:
            raise StoreUnavailable("Database returned an invalid ingestion result.")
        return result

    def latest(self, device_id: str) -> dict[str, Any] | None:
        query = urlencode({"device_id": "eq." + self._device_id(device_id), "select": "*", "limit": 1})
        rows = self._request("device_state?" + query)
        if not isinstance(rows, list) or len(rows) > 1 or (rows and not isinstance(rows[0], dict)):
            raise StoreUnavailable("Database returned an invalid state result.")
        return rows[0] if rows else None

    def events(self, device_id: str, limit: int = 50) -> list[dict[str, Any]]:
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("Event limit must be between 1 and 200.")
        query = urlencode({"device_id": "eq." + self._device_id(device_id), "select": "*",
                           "order": "id.desc", "limit": limit})
        rows = self._request("events?" + query)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise StoreUnavailable("Database returned an invalid event result.")
        return rows
