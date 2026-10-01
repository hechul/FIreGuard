import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from state_manager import SimulationState

with (ROOT / "static" / "data" / "floorplan.json").open(encoding="utf-8") as f:
    floor = json.load(f)

s = SimulationState(floor)
assert len(s.mq2_sensors) == 5
assert s.snapshot()["route"] is not None

s.set_node_fire("N3", True)
snap = s.snapshot()
assert "N3" in snap["blockedNodes"]
assert snap["overallStatus"] == "fire"
assert snap["route"] is not None

s.set_connection("server", False)
assert s.snapshot()["failSafeActive"] is True

s.reset()
s.set_manual_edge("E02", True)
assert "E02" in s.snapshot()["blockedEdges"]

print("FireGuard smoke test: PASS")
