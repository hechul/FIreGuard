"""HTTP boundary checks for the server-only Supabase adapter (no live keys)."""
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cloud_store import StoreUnavailable, SupabaseStore


class SupabaseStoreTest(unittest.TestCase):
    def setUp(self):
        self.store = SupabaseStore("https://example.supabase.co/", "test-server-key")
        self.urlopen = patch("cloud_store.urlopen").start()
        self.addCleanup(patch.stopall)

    def respond(self, value):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(value).encode()
        self.urlopen.return_value = response

    def test_ingest_uses_atomic_rpc_and_server_auth(self):
        telemetry = {"deviceId": "pi-01", "sequence": 7, "flame": {"FLM-08": True}}
        self.respond({"accepted": True, "deviceId": "pi-01", "sequence": 7})
        self.assertTrue(self.store.ingest(telemetry)["accepted"])
        request = self.urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.supabase.co/rest/v1/rpc/ingest_telemetry")
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.get_header("Apikey"), "test-server-key")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-server-key")
        self.assertEqual(json.loads(request.data), {"p_telemetry": telemetry})
        self.assertEqual(self.urlopen.call_args.kwargs["timeout"], 5)

    def test_secret_key_uses_apikey_without_invalid_bearer(self):
        self.respond([])
        SupabaseStore("https://example.supabase.co", "sb_secret_example").latest("pi-01")
        request = self.urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Apikey"), "sb_secret_example")
        self.assertIsNone(request.get_header("Authorization"))

    def test_duplicate_is_a_valid_rpc_result(self):
        self.respond({"accepted": False, "reason": "duplicate", "sequence": 8})
        self.assertFalse(self.store.ingest({})["accepted"])

    def test_latest_returns_no_state_or_one_row(self):
        self.respond([])
        self.assertIsNone(self.store.latest("pi-01"))
        row = {"device_id": "pi-01", "telemetry": {"flame": {}}}
        self.respond([row])
        self.assertEqual(self.store.latest("pi-01"), row)
        query = parse_qs(urlsplit(self.urlopen.call_args.args[0].full_url).query)
        self.assertEqual(query["device_id"], ["eq.pi-01"])
        self.assertEqual(query["limit"], ["1"])

    def test_events_are_bounded_and_newest_first(self):
        self.respond([{"id": 3}, {"id": 2}])
        self.assertEqual(len(self.store.events("pi-01", 2)), 2)
        query = parse_qs(urlsplit(self.urlopen.call_args.args[0].full_url).query)
        self.assertEqual(query["order"], ["id.desc"])
        self.assertEqual(query["limit"], ["2"])
        for limit in (0, 201, True, "20"):
            with self.assertRaises(ValueError):
                self.store.events("pi-01", limit)

    def test_filter_injection_and_invalid_device_are_rejected(self):
        for device in ("pi-01,device_id.neq.other", "", "x" * 65, None):
            with self.assertRaises(ValueError):
                self.store.latest(device)
        self.urlopen.assert_not_called()

    def test_http_error_does_not_leak_key_or_remote_body(self):
        self.urlopen.side_effect = HTTPError("https://secret-url", 401, "secret-key", {}, io.BytesIO(b"database credentials"))
        with self.assertRaises(StoreUnavailable) as caught:
            self.store.latest("pi-01")
        self.assertEqual(str(caught.exception), "Database request failed (HTTP 401).")

    def test_network_timeout_and_invalid_json_are_safe(self):
        for error in (URLError("private-network-details"), TimeoutError("secret")):
            self.urlopen.side_effect = error
            with self.assertRaisesRegex(StoreUnavailable, "temporarily unavailable"):
                self.store.latest("pi-01")
        self.urlopen.side_effect = None
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"<invalid json>"
        self.urlopen.return_value = response
        with self.assertRaisesRegex(StoreUnavailable, "temporarily unavailable"):
            self.store.latest("pi-01")

    def test_malformed_database_shapes_are_rejected(self):
        for result, action in (({}, lambda: self.store.latest("pi-01")),
                               ([{}, {}], lambda: self.store.latest("pi-01")),
                               ({"accepted": "true"}, lambda: self.store.ingest({})),
                               (["bad"], lambda: self.store.events("pi-01"))):
            self.respond(result)
            with self.assertRaises(StoreUnavailable):
                action()

    def test_url_validation(self):
        for url in ("http://example.com", "https://u:p@example.com", "https://example.com/rest/v1", "https://example.com?secret=key", "ftp://example.com"):
            with self.assertRaises(ValueError):
                SupabaseStore(url, "key")
        SupabaseStore("http://127.0.0.1:54321", "local-key")
        with self.assertRaises(ValueError):
            SupabaseStore("https://example.com", "")


if __name__ == "__main__":
    unittest.main()
