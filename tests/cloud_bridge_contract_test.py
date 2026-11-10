"""Regression tests for the supplied USB bridge fixtures; no physical device/DB."""
import json
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from cloud_api_test import CloudApiTest, FLOOR, MemoryStore, TOKEN
from cloud_model import validate_hardware_telemetry

FIXTURES = Path(__file__).parent / 'fixtures' / 'bridge_20261109'


def sample(name):
    payload = json.loads((FIXTURES / name).read_text())
    payload['observedAt'] = datetime.now(timezone.utc).isoformat()
    for sensor in payload['flame'].values():
        sensor['updatedAt'] = payload['observedAt']
    return payload


class BridgeContractTest(CloudApiTest):
    def test_nov10_measured_led_version_is_accepted(self):
        data = sample('01_REAL_NORMAL.json')
        data['ledMappingVersion'] = 'led162-usb163-shift20-da2de217fd'
        response = self.post(data)
        self.assertEqual(response.status_code, 200, response.json)

    def test_sender_examples_and_real_screen(self):
        for index, name in enumerate(('01_REAL_NORMAL.json', '02_REAL_FIRE_ROUTE_ACK.json',
                                      '03_REAL_NO_ROUTE.json', '04_REAL_ARDUINO_DISCONNECTED.json',
                                      '05_REAL_ARDUINO_ACK_FAILURE.json')):
            data = sample(name)
            data['sequence'] = index + 1
            with self.subTest(name=name):
                response = self.post(data)
                self.assertEqual(response.status_code, 200, response.json)
                state = self.client.get('/api/state').json
                self.assertEqual(state['cloud']['hardware']['ledStatus'], data['ledStatus'])
                self.assertEqual(state['cloud']['routeSource'], 'pi')
                self.assertEqual(state['route'] is None, data['routeStatus'] == 'no_route')
                self.assertEqual(state['blockedEdges'], data['blockedEdges'])
                if data['routeStatus'] == 'ok':
                    self.assertEqual(state['route']['nodes'], data['routeNodes'])
                else:
                    self.assertIsNone(state['selectedDestinationName'])
                    self.assertEqual(state['overallStatus'], 'no_route')

    def test_simulation_does_not_write_real_state(self):
        real = sample('02_REAL_FIRE_ROUTE_ACK.json')
        self.post(real)
        previous = deepcopy(self.store.row)
        sim = sample('06_SIMULATION_PREVIEW.json')
        self.assertEqual(self.post(sim).status_code, 400)
        self.assertEqual(self.store.row, previous)

    def test_bad_versions_and_forged_led_ack_are_rejected(self):
        for key, value in [('mappingVersion', 'flame11-unknown'),
                           ('graphMappingVersion', 'graph-unknown'),
                           ('ledMappingVersion', 'led162-unknown'),
                           ('ledCommandAck', False)]:
            data = sample('02_REAL_FIRE_ROUTE_ACK.json')
            data[key] = value
            with self.subTest(key=key):
                self.assertEqual(self.post(data).status_code, 400)
                self.assertIsNone(self.store.row)

    def test_bad_sensor_and_led_translation_are_rejected(self):
        for mutator in (lambda d: d['flame']['FLM-07'].update(node='N8'),
                        lambda d: d['plannedLedIndices'].__setitem__(0, 20),
                        lambda d: d.update(secret='must not persist')):
            data = sample('02_REAL_FIRE_ROUTE_ACK.json')
            mutator(data)
            self.assertEqual(self.post(data).status_code, 400)
            self.assertIsNone(self.store.row)

    def test_disconnected_sensor_not_reported_normal(self):
        data = sample('01_REAL_NORMAL.json')
        data['flame']['FLM-07']['connected'] = False
        self.assertEqual(self.post(data).status_code, 200)
        state = self.client.get('/api/state').json
        self.assertTrue(state['connections']['pi'])
        self.assertFalse(state['flameSensors']['FLM-07']['connected'])
        self.assertEqual(state['sensorCounts']['offline'], 1)
        equipment = next(x for x in state['equipment'] if x['id'] == 'FLM-07')
        self.assertEqual(equipment['status'], 'offline')

    def test_last_known_fire_does_not_clear_on_disconnected_sensor(self):
        data = sample('01_REAL_NORMAL.json')
        data['flame']['FLM-10']['connected'] = False
        self.assertEqual(self.post(data).status_code, 200)
        # SQL v2 retains the last known active value when a sensor disconnects.
        self.store.row['telemetry']['flame']['FLM-10'] = True
        state = self.client.get('/api/state').json
        self.assertTrue(state['flameSensors']['FLM-10']['active'])
        self.assertFalse(state['flameSensors']['FLM-10']['connected'])
        self.assertIn('N10', state['blockedNodes'])
        self.assertNotIn('N10', state['cloud']['hardware']['blockedNodes'])
        self.assertIsNone(state['route'])
        self.assertEqual(state['cloud']['routeSource'], 'pi_unverified')
