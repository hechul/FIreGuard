import json
from pathlib import Path
import unittest
from led_demo_test import (BLACK, MockPixels, execute, parse_args, path_indices,
                           segment_ranges)


class LedTest(unittest.TestCase):
    def setUp(self):
        self.counts = json.loads(Path(__file__).with_name('led_segments.json').read_text())
        self.ranges = segment_ranges(self.counts)

    def test_physical_boundaries(self):
        flat = [i for indices in self.ranges.values() for i in indices]
        self.assertEqual(flat, list(range(155)))
        self.assertEqual(self.ranges['S10'], [112, 113, 114, 115])
        self.assertEqual(self.ranges['S15'], [151, 152, 153, 154])

    def test_reverse_and_partial_path(self):
        self.assertEqual(path_indices('S3:4:2,-S1', self.ranges), [33, 32, 31, 3, 2, 1, 0])
        with self.assertRaises(ValueError):
            path_indices('S1,S1', self.ranges)
        with self.assertRaises(ValueError):
            path_indices('S3:0:30', self.ranges)

    def test_bad_config_is_rejected(self):
        for value in (None, True, 0, -1, 500):
            counts = dict(self.counts, S1=value)
            with self.assertRaises(ValueError):
                segment_ranges(counts)

    def test_interruption_blanks_every_pixel(self):
        pixels = MockPixels()
        def interrupt(_):
            raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            execute(pixels, parse_args(['segment', '--segment', 'S10']), self.ranges, interrupt)
        self.assertTrue(all(value == BLACK for value in pixels.values))

    def test_scan_never_lights_multiple_pixels(self):
        pixels = MockPixels()
        original = pixels.show
        def record():
            self.assertLessEqual(sum(v != BLACK for v in pixels.values), 1)
            original()
        pixels.show = record
        execute(pixels, parse_args(['scan']), sleep=lambda _: None)
        self.assertTrue(all(v == BLACK for v in pixels.values))


if __name__ == '__main__':
    unittest.main()
