"""QR endpoints do not mutate global routing or select a Pi start node."""
import os
import unittest
from unittest.mock import patch
import app as server
from qr_locations import QR_LOCATIONS, mobile_url


class QrMobileTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'FIREGUARD_CLOUD':'0', 'VERCEL':'', 'VERCEL_ENV':''})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = server.app.test_client()

    def test_four_locations_and_unknown_node(self):
        before = server.state.start_node
        self.assertEqual(len(QR_LOCATIONS),4)
        for location in QR_LOCATIONS:
            response = self.client.get('/mobile/'+location['id'])
            self.assertEqual(response.status_code,200)
            self.assertIn(location['label'],response.get_data(as_text=True))
            with self.client.get('/static/images/qr/'+location['id']+'.svg') as image:
                self.assertEqual(image.status_code,200)
            snapshot = self.client.get('/api/state?startNode='+location['id']).json
            self.assertEqual(snapshot['startNode'],location['id'])
        self.assertEqual(server.state.start_node,before)
        self.assertEqual(self.client.get('/mobile/BAD').status_code,404)

    def test_print_urls_are_public_and_location_specific(self):
        response = self.client.get('/qr')
        self.assertEqual(response.status_code,200)
        text = response.get_data(as_text=True)
        for location in QR_LOCATIONS:
            self.assertIn(mobile_url(location['id']),text)
        self.assertNotIn('localhost',text)
