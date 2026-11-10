"""Independent REAL sensor latch core; not wired to the Pi application yet.

The caller supplies already-confirmed sensor samples. A normal sample never
clears an alarm; only an explicit selective clear can do so. Freshness is
measured using a monotonic clock and is deliberately reset on process restart.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Mapping


class RealFireLatch:
    def __init__(self, sensor_ids, path, *, stale_after=15.0, clock: Callable[[], float] = time.monotonic):
        ids = tuple(sensor_ids)
        if not ids or len(set(ids)) != len(ids) or any(not isinstance(s, str) or not s for s in ids):
            raise ValueError('sensor_ids must contain unique nonempty strings')
        if isinstance(stale_after, bool) or not isinstance(stale_after, (int, float)) or not math.isfinite(stale_after) or stale_after <= 0:
            raise ValueError('stale_after must be positive and finite')
        self.ids = ids
        self._known = frozenset(ids)
        self.path = Path(path)
        self.stale_after = float(stale_after)
        self.clock = clock
        self._lock = threading.RLock()
        self._raw = {sid: None for sid in ids}
        self._seen = {sid: None for sid in ids}
        self._latched = set()
        self._dirty = False
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding='utf-8'))
            except (OSError, ValueError, UnicodeError) as error:
                raise RuntimeError('Stored fire latches could not be read') from error
            if (not isinstance(data, dict) or set(data) != {'version', 'latched'}
                    or data['version'] != 1 or not isinstance(data['latched'], list)
                    or any(not isinstance(s, str) for s in data['latched'])
                    or len(set(data['latched'])) != len(data['latched'])
                    or not set(data['latched']) <= self._known):
                raise RuntimeError('Stored fire latches are invalid')
            self._latched = set(data['latched'])

    def _persist(self, value):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        filename = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent,
                                             prefix='.real-fire-', suffix='.tmp', delete=False) as handle:
                filename = handle.name
                json.dump({'version': 1, 'latched': sorted(value)}, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(filename, self.path)
            filename = None
        finally:
            if filename is not None:
                try:
                    os.unlink(filename)
                except FileNotFoundError:
                    pass

    def update(self, readings: Mapping[str, bool]):
        """Record one partial/full batch of debounced REAL samples, then latch.

        If persisting a new alarm fails, it remains active in memory and the
        error propagates; the next update retries persistence. Caller must not
        report a persistence failure as durable success.
        """
        if not isinstance(readings, Mapping) or not readings or any(
                sid not in self._known or type(value) is not bool for sid, value in readings.items()):
            raise ValueError('readings must be nonempty known sensor/boolean pairs')
        with self._lock:
            now = self.clock()
            for sid, value in readings.items():
                self._raw[sid] = value
                self._seen[sid] = now
            newly_active = {sid for sid, value in readings.items() if value} - self._latched
            if newly_active:
                self._latched.update(newly_active)
                self._dirty = True
            if self._dirty:
                self._persist(self._latched)
                self._dirty = False
            return self.snapshot()

    def clear(self, sensor_ids):
        """Atomically clear selected inactive, freshly observed alarm sensors.

        All selected sensors must be known, latched, fresh and physically read
        as inactive, otherwise none are cleared. This does not authenticate an
        operator; the caller is responsible for command authorization.
        """
        if not isinstance(sensor_ids, (list, tuple)) or not sensor_ids or any(
                not isinstance(sid, str) or sid not in self._known for sid in sensor_ids):
            raise ValueError('sensor_ids must contain known sensors')
        if len(set(sensor_ids)) != len(sensor_ids):
            raise ValueError('duplicate sensor IDs')
        with self._lock:
            now = self.clock()
            for sid in sensor_ids:
                age = None if self._seen[sid] is None else now - self._seen[sid]
                if (sid not in self._latched or age is None or age < 0 or age > self.stale_after
                        or self._raw[sid] is not False):
                    raise ValueError(f'{sid} is active, stale, unknown or not latched')
            remaining = self._latched.difference(sensor_ids)
            # Persist before dropping a latch; a failed write never clears it.
            self._persist(remaining)
            self._latched = remaining
            self._dirty = False
            return self.snapshot()

    def restore(self, sensor_ids):
        """Conservatively merge known cloud alarms without marking raw fresh."""
        if not isinstance(sensor_ids, list) or any(not isinstance(sid, str) or sid not in self._known for sid in sensor_ids):
            raise ValueError('sensor_ids must contain known sensors')
        if len(set(sensor_ids)) != len(sensor_ids):
            raise ValueError('duplicate sensor IDs')
        with self._lock:
            newly_active = set(sensor_ids) - self._latched
            if newly_active:
                self._latched.update(newly_active)
                self._dirty = True
            if self._dirty:
                self._persist(self._latched)
                self._dirty = False
            return self.snapshot()

    def snapshot(self):
        with self._lock:
            now = self.clock()
            sensors = {}
            for sid in self.ids:
                seen = self._seen[sid]
                age = None if seen is None else now - seen
                fresh = age is not None and 0 <= age <= self.stale_after
                sensors[sid] = {'active': sid in self._latched,
                                'rawActive': self._raw[sid] if fresh else None,
                                'connected': fresh}
            return {'sensors': sensors, 'realFireDetected': bool(self._latched),
                    'latchedSensorIds': sorted(self._latched), 'persistencePending': self._dirty}
