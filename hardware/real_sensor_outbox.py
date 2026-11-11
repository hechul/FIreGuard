"""Keep observed fire transitions until the local REAL service accepts them."""

class PendingFireSamples:
    def __init__(self):
        self.pending = set()

    def observe(self, changed):
        self.pending.update(sid for sid, active in changed.items() if active)

    def next(self):
        return {sid: True for sid in sorted(self.pending)}

    def accepted(self, payload):
        self.pending.difference_update(sid for sid, active in payload.items() if active)
