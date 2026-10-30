"""Production-mode regressions without a live Supabase or Vercel account."""
import json
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app as server
from cloud_api import install_cloud


class EmptyStore:
    def latest(self, device_id):
        return None

    def events(self, device_id):
        return []


class VercelDeploymentTest(unittest.TestCase):
    def test_vercel_framework_preset_is_explicit(self):
        config = json.loads((ROOT / 'vercel.json').read_text())
        self.assertEqual(config['framework'], 'flask')
        self.assertIn('app.py', config['functions'])
        self.assertNotIn('builds', config)

    def test_vercel_environment_cannot_be_downgraded_by_local_flag(self):
        cases = ({'VERCEL': '1', 'FIREGUARD_CLOUD': '0'},
                 {'VERCEL_ENV': 'production', 'FIREGUARD_CLOUD': '0'},
                 {'VERCEL_ENV': 'preview', 'FIREGUARD_CLOUD': '0'})
        for values in cases:
            with self.subTest(values=values), patch.dict(os.environ, values, clear=True):
                app = Flask('production-mode-test')
                install_cloud(app, server.floorplan)
                self.assertTrue(app.config['CLOUD_ENABLED'])
                client = app.test_client()
                self.assertTrue(client.get('/api/cloud/config').json['enabled'])
                self.assertEqual(client.post('/api/mode', json={'mode': 'simulation'}).status_code, 409)

    def test_local_run_keeps_simulation_available(self):
        with patch.dict(os.environ, {'FIREGUARD_CLOUD': '0'}, clear=True):
            app = Flask('local-mode-test')
            install_cloud(app, server.floorplan)
            self.assertFalse(app.config['CLOUD_ENABLED'])
            self.assertEqual(app.test_client().get('/api/cloud/config').json['enabled'], False)

    def test_health_exposes_build_marker_and_revision_not_secrets(self):
        with patch.dict(os.environ, {'VERCEL_ENV': 'production',
                                     'VERCEL_GIT_COMMIT_SHA': 'a' * 40,
                                     'SUPABASE_SERVICE_ROLE_KEY': 'never-publish-this-key',
                                     'FIREGUARD_DEVICE_TOKEN': 'never-publish-device-token'}, clear=True):
            app = Flask('build-info-test')
            install_cloud(app, server.floorplan)
            response = app.test_client().get('/api/health')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['buildId'], 'fireguard-cloud-v2')
            self.assertEqual(response.json['revision'], 'a' * 40)
            self.assertTrue(response.json['cloud'])
            self.assertNotIn('never-publish', response.text)

    def test_real_routes_and_first_paint_waiting_state(self):
        previous = server.app.config['CLOUD_ENABLED']
        previous_store = server.app.extensions.get('cloud_store')
        try:
            server.app.config['CLOUD_ENABLED'] = True
            server.app.extensions['cloud_store'] = EmptyStore()
            with patch.dict(os.environ, {'FIREGUARD_DEVICE_ID': 'pi-01'}, clear=True):
                client = server.app.test_client()
                for path in ('/api/cloud/config', '/api/state', '/api/floorplan'):
                    response = client.get(path)
                    self.assertEqual(response.status_code, 200, path)
                    self.assertTrue(response.is_json, path)
                snapshot = client.get('/api/state').json
                self.assertEqual(snapshot['operationMode'], 'real')
                self.assertFalse(snapshot['connections']['pi'])
                self.assertEqual(snapshot['overallStatus'], 'unknown')
                html = client.get('/').text
                self.assertRegex(html, r'data-cloud=["\']true["\']')
                self.assertIn('fireguard-cloud-v2', html)
                sim = re.search(r'<button\b[^>]*\bid="simModeBtn"[^>]*>', html)
                self.assertIsNotNone(sim)
                self.assertIn('disabled', sim.group(0))
                self.assertNotRegex(sim.group(0), r'class="[^"]*\bactive\b')
                pi_chip = re.search(r'id="piChip"[^>]*>(.*?)</div>', html, re.S)
                self.assertIsNotNone(pi_chip)
                self.assertNotIn('ONLINE', pi_chip.group(1))
                static_response = client.get('/static/js/cloud_live.js')
                self.assertEqual(static_response.status_code, 200)
                static_response.close()
        finally:
            server.app.config['CLOUD_ENABLED'] = previous
            if previous_store is None:
                server.app.extensions.pop('cloud_store', None)
            else:
                server.app.extensions['cloud_store'] = previous_store


if __name__ == '__main__':
    unittest.main()
