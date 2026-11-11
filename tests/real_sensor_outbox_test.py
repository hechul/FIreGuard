import unittest

from hardware.real_sensor_outbox import PendingFireSamples


class PendingFireSamplesTest(unittest.TestCase):
    def test_fire_is_retained_across_failed_send_and_normal_transition(self):
        pending = PendingFireSamples()
        pending.observe({'FLM-01': True, 'FLM-02': True})
        attempted = pending.next()
        pending.observe({'FLM-01': False})
        self.assertEqual(pending.next(), attempted)
        pending.accepted(attempted)
        self.assertEqual(pending.next(), {})

    def test_new_fire_is_not_lost_when_acknowledging_an_older_batch(self):
        pending = PendingFireSamples()
        pending.observe({'FLM-01': True})
        old = pending.next()
        pending.observe({'FLM-02': True})
        pending.accepted(old)
        self.assertEqual(pending.next(), {'FLM-02': True})


if __name__ == '__main__':
    unittest.main()
