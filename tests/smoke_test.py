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
assert s.snapshot()["routeMode"] == "exit"

# MQ-2 warning does not block node
s.reset()
s.set_mq2("MQ2-02", 450)
snap = s.snapshot()
assert snap["overallStatus"] == "warning"
assert "N5" not in snap["blockedNodes"]

# MQ-2 danger blocks node
s.reset()
s.set_mq2("MQ2-05", 760)
snap = s.snapshot()
assert snap["overallStatus"] == "fire"
assert "N3" in snap["blockedNodes"]

# congestion: dynamic weight reroutes away from default east exit
s.reset()
default_exit = s.snapshot()["selectedDestinationName"]
s.set_edge_weight("E02", 14.0)
s.set_edge_weight("E03", 8.0)
snap = s.snapshot()
assert snap["congestionActive"] is True
assert snap["edgeWeightOverrides"]["E02"] == 14.0
assert snap["selectedDestinationName"] != default_exit

# sensor fault
s.reset()
s.set_sensor_connection("FLM-15", False)
s.set_sensor_connection("MQ2-05", False)
snap = s.snapshot()
assert snap["sensorCounts"]["offline"] == 2
assert snap["flameSensors"]["FLM-15"]["connected"] is False

# server fail-safe vs PI offline distinction
s.reset()
s.set_connection("server", False)
assert s.snapshot()["failSafeActive"] is True
s.reset()
s.set_connection("pi", False)
assert s.snapshot()["connections"]["pi"] is False
assert s.snapshot()["failSafeActive"] is False

# fallback toilet
s.reset()
for edge_id in ("E03", "E09", "E12", "E16"):
    s.set_manual_edge(edge_id, True)
snap = s.snapshot()
assert snap["fallbackActive"] is True
assert snap["selectedDestinationType"] == "toilet"

# fallback descender
for edge_id in ("E21", "E22"):
    s.set_manual_edge(edge_id, True)
snap = s.snapshot()
assert snap["selectedDestinationType"] == "descender"
assert snap["route"]["destinationId"] == "N18"

# no route
s.set_manual_edge("E23", True)
snap = s.snapshot()
assert snap["route"] is None
assert snap["overallStatus"] == "no_route"

print("FireGuard v5.4 Scenario Lab smoke test: PASS")
