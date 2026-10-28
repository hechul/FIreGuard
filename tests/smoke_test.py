import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from state_manager import SimulationState

with (ROOT / "static" / "data" / "floorplan.json").open(encoding="utf-8") as f:
    floor = json.load(f)

s = SimulationState(floor)

assert all(sensor["type"] == "flame" for sensor in floor["sensors"])
assert s.snapshot()["route"] is not None
assert s.snapshot()["routeMode"] == "exit"

# Flame detection blocks its configured node
s.reset()
s.set_flame("FLM-15", True)
snap = s.snapshot()
assert snap["overallStatus"] == "fire"
assert "N10" in snap["blockedNodes"]

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
snap = s.snapshot()
assert snap["sensorCounts"]["offline"] == 1
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
assert snap["route"]["destinationId"] == "N3"

# no route
for edge in floor["edges"]:
    if s.start_node in (edge["from"], edge["to"]):
        s.set_manual_edge(edge["id"], True)
snap = s.snapshot()
assert snap["route"] is None
assert snap["overallStatus"] == "no_route"

print("FireGuard v5.4 Scenario Lab smoke test: PASS")
