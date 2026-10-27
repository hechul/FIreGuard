"""Pi 4 / WS2812B commissioning: S1 -> ... -> S15. No dashboard connection."""
import argparse
import json
import math
from pathlib import Path
import signal
import time

CAPACITY = 300  # One purchased 300-pixel roll; unused frame slots remain black.
BLACK = (0, 0, 0)
COLORS = {'red': (255, 0, 0), 'green': (0, 255, 0), 'blue': (0, 0, 255)}


def segment_ranges(counts):
    if set(counts) != {f'S{i}' for i in range(1, 16)}:
        raise ValueError('Configuration must contain exactly S1 through S15.')
    result = {}
    offset = 0
    for i in range(1, 16):
        name = f'S{i}'
        count = counts[name]
        if type(count) is not int or count < 1:
            raise ValueError(f'{name}: replace null with the actual positive LED count.')
        result[name] = list(range(offset, offset + count))
        offset += count
    if offset > CAPACITY:
        raise ValueError('Total exceeds the purchased 300 LEDs; review counts.')
    return result


def path_indices(spec, ranges):
    """S2 or -S2: full segment; S2:3:0: local inclusive range, reversed."""
    result = []
    for token in spec.split(','):
        token = token.strip()
        parts = token.split(':')
        name = parts[0].lstrip('-')
        if name not in ranges:
            raise ValueError(f'Unknown segment: {name}')
        indices = ranges[name]
        if len(parts) == 1:
            selected = indices[::-1] if token.startswith('-') else indices
        elif len(parts) == 3 and not token.startswith('-'):
            start, end = int(parts[1]), int(parts[2])
            if not 0 <= start < len(indices) or not 0 <= end < len(indices):
                raise ValueError(f'Local pixel range outside {name}: {token}')
            step = 1 if end >= start else -1
            selected = [indices[j] for j in range(start, end + step, step)]
        else:
            raise ValueError(f'Invalid path token: {token}')
        result.extend(selected)
    if len(set(result)) != len(result):
        raise ValueError('Path repeats an LED. Use a simple, non-overlapping test path.')
    return result


class MockPixels:
    def __init__(self):
        self.values = [BLACK] * CAPACITY
        self.frames = 0

    def fill(self, color):
        self.values[:] = [color] * CAPACITY

    def __setitem__(self, index, color):
        self.values[index] = color

    def show(self):
        self.frames += 1

    def deinit(self):
        pass


def paint(pixels, indices, color):
    pixels.fill(BLACK)
    for index in indices:
        pixels[index] = color
    pixels.show()


def execute(pixels, args, ranges=None, sleep=time.sleep):
    try:
        paint(pixels, [], BLACK)
        if args.mode == 'off':
            return
        if args.mode == 'first':
            for name, color in COLORS.items():
                print(f'First LED: {name}', flush=True)
                paint(pixels, [0], color)
                sleep(args.hold)
        elif args.mode == 'scan':
            for i in range(args.limit):
                print(f'LED index={i} (physical LED #{i + 1})', flush=True)
                paint(pixels, [i], COLORS[args.color])
                sleep(args.delay)
        elif args.mode == 'pixel':
            paint(pixels, [args.index], COLORS[args.color])
            print(f'LED index={args.index}', flush=True)
            sleep(args.hold)
        elif args.mode == 'segments':
            for name, indices in ranges.items():
                print(f'{name}: global indices {indices[0]}..{indices[-1]}', flush=True)
                paint(pixels, indices, COLORS[args.color])
                sleep(args.hold)
        elif args.mode == 'segment':
            paint(pixels, ranges[args.segment], COLORS[args.color])
            sleep(args.hold)
        elif args.mode == 'chase':
            indices = ranges[args.segment]
            if args.reverse:
                indices = indices[::-1]
            for _ in range(args.cycles):
                for i in indices:
                    paint(pixels, [i], COLORS[args.color])
                    sleep(args.delay)
        elif args.mode == 'path':
            indices = path_indices(args.path, ranges)
            for _ in range(args.cycles):
                for i in indices:
                    paint(pixels, [i], COLORS[args.color])
                    sleep(args.delay)
    finally:
        try:
            paint(pixels, [], BLACK)
        finally:
            pixels.deinit()


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=['first', 'scan', 'pixel', 'off', 'segments', 'segment', 'chase', 'path'])
    p.add_argument('--config', type=Path, default=Path(__file__).with_name('led_segments.json'))
    p.add_argument('--segment', choices=[f'S{i}' for i in range(1, 16)], default='S1')
    p.add_argument('--color', choices=COLORS, default='green')
    p.add_argument('--limit', type=int, default=155)
    p.add_argument('--index', type=int, default=0, help='Zero-based global pixel index')
    p.add_argument('--brightness', type=float, default=0.05, help='0.01..0.10; test cap, not a fuse')
    p.add_argument('--delay', type=float, default=0.15)
    p.add_argument('--hold', type=float, default=2.0)
    p.add_argument('--cycles', type=int, default=3)
    p.add_argument('--reverse', action='store_true')
    p.add_argument('--path', default='', help='Example: S3:0:4,-S2,-S1; not a verified escape route')
    p.add_argument('--order', choices=['GRB', 'RGB'], default='GRB')
    p.add_argument('--mock', action='store_true', help='No GPIO or delays; software checks only')
    args = p.parse_args(argv)
    if not math.isfinite(args.brightness) or not 0.01 <= args.brightness <= 0.10:
        p.error('Test brightness must be between 0.01 and 0.10.')
    if not 1 <= args.limit <= CAPACITY or not 0 <= args.index < CAPACITY:
        p.error('limit: 1..300; index: 0..299.')
    if any(not math.isfinite(v) or not 0.01 <= v <= 60 for v in (args.delay, args.hold)):
        p.error('delay and hold must be 0.01..60 seconds.')
    if not 1 <= args.cycles <= 100:
        p.error('cycles must be 1..100.')
    if args.mode == 'path' and not args.path:
        p.error('path mode requires --path.')
    return args


def main(argv=None):
    args = parse_args(argv)
    ranges = None
    try:
        if args.mode in {'segments', 'segment', 'chase', 'path'}:
            ranges = segment_ranges(json.loads(args.config.read_text(encoding='utf-8-sig')))
            if args.mode == 'path':
                path_indices(args.path, ranges)  # Validate before opening GPIO.
            for name, indices in ranges.items():
                print(f'{name}: {len(indices)} LEDs, index {indices[0]}..{indices[-1]}')
        if args.mock:
            pixels = MockPixels()
        else:
            import board
            import neopixel
            pixels = neopixel.NeoPixel(board.D18, CAPACITY, brightness=args.brightness,
                                      auto_write=False, pixel_order=getattr(neopixel, args.order))
        print(f'GPIO18 (physical pin 12), brightness={args.brightness:.0%}; mode={args.mode}', flush=True)
        execute(pixels, args, ranges, sleep=(lambda _: None) if args.mock else time.sleep)
        print('Commands completed; visually verify hardware. All-off sent.')
        return 0
    except KeyboardInterrupt:
        print('Stopped; cleanup attempted. Disconnect power if LEDs remain lit.')
        return 130
    except Exception as exc:
        print(f'ERROR: {exc}')
        return 1


if __name__ == '__main__':
    def stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    raise SystemExit(main())
