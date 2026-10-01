from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO, emit

from state_manager import SimulationState

BASE_DIR = Path(__file__).resolve().parent
FLOORPLAN_PATH = BASE_DIR / "static" / "data" / "floorplan.json"

app = Flask(__name__)
app.config["SECRET_KEY"] = "fireguard-capstone-2026"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

with FLOORPLAN_PATH.open("r", encoding="utf-8") as file:
    floorplan = json.load(file)

state = SimulationState(floorplan)


def broadcast_state() -> dict[str, Any]:
    snapshot = state.snapshot()
    socketio.emit("state:update", snapshot)
    return snapshot


def apply_action(action: Callable[[], None]):
    try:
        action()
    except (ValueError, TypeError, KeyError) as error:
        return jsonify({"ok": False, "error": str(error)}), 400
    return jsonify({"ok": True, "state": broadcast_state()})


def payload() -> dict[str, Any]:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("JSON 요청 본문이 필요합니다.")
    return data


@app.get("/")
def dashboard():
    return render_template("dashboard.html")


@app.get("/mobile/<node_id>")
def mobile(node_id: str):
    return render_template("mobile.html", node_id=node_id)


@app.get("/api/floorplan")
def get_floorplan():
    return jsonify(floorplan)


@app.get("/api/state")
def get_state():
    return jsonify(state.snapshot())


@app.post("/api/mode")
def set_mode():
    data = payload()
    return apply_action(lambda: state.set_operation_mode(data["mode"]))


@app.post("/api/simulation/start-node")
def set_start_node():
    data = payload()
    return apply_action(lambda: state.set_start_node(data["nodeId"], source="SIM"))


@app.post("/api/simulation/flame")
def set_flame():
    data = payload()
    return apply_action(lambda: state.set_flame(data["sensorId"], data["active"], source="SIM"))


@app.post("/api/simulation/mq2")
def set_mq2():
    data = payload()
    return apply_action(lambda: state.set_mq2(data["sensorId"], data["value"], source="SIM"))


@app.post("/api/simulation/node-fire")
def set_node_fire():
    data = payload()
    return apply_action(lambda: state.set_node_fire(data["nodeId"], data["active"], source="SIM"))


@app.post("/api/simulation/shutter")
def set_shutter():
    data = payload()
    return apply_action(lambda: state.set_shutter(data["shutterId"], data["closed"], source="SIM"))


@app.post("/api/simulation/manual-edge")
def set_manual_edge():
    data = payload()
    return apply_action(lambda: state.set_manual_edge(data["edgeId"], data["blocked"]))


@app.post("/api/simulation/connection")
def set_connection():
    data = payload()
    return apply_action(lambda: state.set_connection(data["target"], data["connected"], source="SIM"))


@app.post("/api/simulation/reset")
def reset():
    data = request.get_json(silent=True) or {}
    return apply_action(lambda: state.reset(clear_events=bool(data.get("clearEvents", False))))


@app.post("/api/simulation/scenario")
def run_scenario():
    data = payload()
    scenario_id = data["scenarioId"]

    def action():
        if scenario_id == "normal":
            state.reset(clear_events=False)
        elif scenario_id == "east_exit_fire":
            state.reset(clear_events=False)
            state.set_node_fire("N3", True, source="SCENARIO")
        elif scenario_id == "cinema4_fire":
            state.reset(clear_events=False)
            state.set_node_fire("N9", True, source="SCENARIO")
        elif scenario_id == "east_shutter":
            state.reset(clear_events=False)
            state.set_shutter("SH-02", True, source="SCENARIO")
        elif scenario_id == "server_off":
            state.set_connection("server", False, source="SCENARIO")
        elif scenario_id == "server_on":
            state.set_connection("server", True, source="SCENARIO")
        elif scenario_id == "no_route":
            state.reset(clear_events=False)
            for shutter in floorplan.get("shutters", []):
                state.set_shutter(shutter["id"], True, source="SCENARIO")
            # 서측 우회 경로까지 차단하여 '경로 없음'을 시연한다.
            state.set_manual_edge("E08", True)
            state.set_manual_edge("E16", True)
            state.set_manual_edge("E12", True)
        else:
            raise ValueError(f"알 수 없는 시나리오입니다: {scenario_id}")

    return apply_action(action)


# ---------------------------------------------------------------------------
# 실제 Raspberry Pi 연동용 API
# ---------------------------------------------------------------------------
@app.post("/api/hardware/heartbeat")
def hardware_heartbeat():
    def action():
        state.set_operation_mode("real")
        state.hardware_heartbeat()

    return apply_action(action)


@app.post("/api/hardware/flame")
def hardware_flame():
    data = payload()

    def action():
        state.set_operation_mode("real")
        state.hardware_heartbeat()
        state.set_flame(data["sensorId"], data["active"], source="REAL")

    return apply_action(action)


@app.post("/api/hardware/mq2")
def hardware_mq2():
    data = payload()

    def action():
        state.set_operation_mode("real")
        state.hardware_heartbeat()
        state.set_mq2(data["sensorId"], data["value"], source="REAL")

    return apply_action(action)


@app.post("/api/hardware/batch")
def hardware_batch():
    """라즈베리파이가 한 번에 여러 센서 값을 전송할 때 사용한다.

    예시:
    {
      "flame": {"FLM-01": false, "FLM-07": true},
      "mq2": {"MQ2-01": 120, "MQ2-04": 731},
      "shutters": {"SH-01": false}
    }
    """
    data = payload()

    def action():
        state.set_operation_mode("real")
        state.hardware_heartbeat()
        for sensor_id, active in (data.get("flame") or {}).items():
            state.set_flame(sensor_id, bool(active), source="REAL")
        for sensor_id, value in (data.get("mq2") or {}).items():
            state.set_mq2(sensor_id, int(value), source="REAL")
        for shutter_id, closed in (data.get("shutters") or {}).items():
            state.set_shutter(shutter_id, bool(closed), source="REAL")

    return apply_action(action)


@socketio.on("connect")
def socket_connected():
    emit("state:update", state.snapshot())


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, use_reloader=False)
