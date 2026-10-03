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


def _save_floorplan() -> None:
    """현재 floorplan을 JSON 파일에 안전하게 저장."""
    temp_path = FLOORPLAN_PATH.with_suffix(".json.tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(floorplan, file, ensure_ascii=False, indent=2)
    temp_path.replace(FLOORPLAN_PATH)


@app.post("/api/floorplan/layout")
def update_floorplan_layout():
    """대시보드 Map Editor에서 Node/Exit 표시 좌표를 저장한다.

    Edge는 from/to Node 연결 관계로 계산되므로 별도 좌표를 가지지 않는다.
    편집 화면의 '간선 이동'은 연결된 두 끝점을 동시에 이동한다.
    """
    try:
        data = payload()
        positions = data.get("positions")
        if not isinstance(positions, dict):
            raise ValueError("positions 객체가 필요합니다.")

        editable = {}
        for item in [*floorplan.get("nodes", []), *floorplan.get("exits", [])]:
            editable[item["id"]] = item

        changed = 0
        for item_id, point in positions.items():
            if item_id not in editable:
                continue
            if not isinstance(point, dict):
                raise ValueError(f"{item_id} 좌표 형식이 올바르지 않습니다.")

            x = float(point["x"])
            y = float(point["y"])
            # 현재 Digital Twin viewBox: 584 × 858
            x = max(8.0, min(576.0, x))
            y = max(8.0, min(850.0, y))

            editable[item_id]["x"] = round(x, 2)
            editable[item_id]["y"] = round(y, 2)
            changed += 1

        if not changed:
            raise ValueError("저장할 좌표가 없습니다.")

        _save_floorplan()
        socketio.emit("floorplan:update", floorplan)
        return jsonify({"ok": True, "floorplan": floorplan, "changed": changed})
    except (ValueError, TypeError, KeyError) as error:
        return jsonify({"ok": False, "error": str(error)}), 400


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



@app.post("/api/simulation/sensor-connection")
def set_sensor_connection():
    data = payload()
    return apply_action(lambda: state.set_sensor_connection(data["sensorId"], data["connected"], source="SIM"))


@app.post("/api/simulation/edge-weight")
def set_edge_weight():
    data = payload()
    value = data.get("weight")
    return apply_action(lambda: state.set_edge_weight(data["edgeId"], value, source="SIM"))


@app.post("/api/simulation/reset")
def reset():
    data = request.get_json(silent=True) or {}
    return apply_action(lambda: state.reset(clear_events=bool(data.get("clearEvents", False))))


@app.post("/api/simulation/scenario")
def run_scenario():
    data = payload()
    scenario_id = data["scenarioId"]

    def action():
        # -----------------------------------------------------------
        # BASIC
        # -----------------------------------------------------------
        if scenario_id == "normal":
            state.reset(clear_events=False)

        # -----------------------------------------------------------
        # SENSOR / FIRE
        # -----------------------------------------------------------
        elif scenario_id == "smoke_warning":
            state.reset(clear_events=False)
            state.set_mq2("MQ2-02", 450, source="SCENARIO")

        elif scenario_id == "smoke_danger":
            state.reset(clear_events=False)
            state.set_mq2("MQ2-05", 760, source="SCENARIO")

        elif scenario_id == "east_exit_fire":
            state.reset(clear_events=False)
            state.set_node_fire("N3", True, source="SCENARIO")

        elif scenario_id == "ticket_fire":
            state.reset(clear_events=False)
            state.set_node_fire("N14", True, source="SCENARIO")

        elif scenario_id == "cinema4_fire":
            state.reset(clear_events=False)
            state.set_node_fire("N9", True, source="SCENARIO")

        elif scenario_id == "large_fire":
            state.reset(clear_events=False)
            # 동측 출구와 서측 분기점을 동시에 위험 Node로 만들어 남측 출구 우회를 유도한다.
            state.set_node_fire("N3", True, source="SCENARIO")
            state.set_node_fire("N7", True, source="SCENARIO")

        # -----------------------------------------------------------
        # ROUTE / BLOCK / CROWD
        # -----------------------------------------------------------
        elif scenario_id == "east_shutter":
            state.reset(clear_events=False)
            state.set_shutter("SH-02", True, source="SCENARIO")

        elif scenario_id == "mid_route_block":
            state.reset(clear_events=False)
            # 정상 최단경로 N1-N2-N3-EXIT_E 중 E02가 갑자기 막힌 상황.
            state.set_manual_edge("E02", True)

        elif scenario_id == "crowd_congestion":
            state.reset(clear_events=False)
            # 차단은 아니지만 동측 통로 혼잡 비용을 크게 올려 Dijkstra가 다른 출구를 선택하게 한다.
            state.set_edge_weight("E02", 14.0, source="SCENARIO")
            state.set_edge_weight("E03", 8.0, source="SCENARIO")

        # -----------------------------------------------------------
        # FALLBACK / IMPOSSIBLE
        # -----------------------------------------------------------
        elif scenario_id == "fallback_toilet":
            state.reset(clear_events=False)
            for edge_id in ("E03", "E09", "E12", "E16"):
                state.set_manual_edge(edge_id, True)

        elif scenario_id == "fallback_descender":
            state.reset(clear_events=False)
            for edge_id in ("E03", "E09", "E12", "E16", "E21", "E22"):
                state.set_manual_edge(edge_id, True)

        elif scenario_id == "no_route":
            state.reset(clear_events=False)
            for edge_id in ("E03", "E09", "E12", "E16", "E21", "E22", "E23"):
                state.set_manual_edge(edge_id, True)

        # -----------------------------------------------------------
        # SYSTEM / COMMUNICATION
        # -----------------------------------------------------------
        elif scenario_id == "server_off":
            state.reset(clear_events=False)
            state.set_connection("server", False, source="SCENARIO")

        elif scenario_id == "fire_server_off":
            state.reset(clear_events=False)
            state.set_node_fire("N3", True, source="SCENARIO")
            state.set_connection("server", False, source="SCENARIO")

        elif scenario_id == "server_on":
            state.set_connection("server", True, source="SCENARIO")

        elif scenario_id == "pi_off":
            state.reset(clear_events=False)
            state.set_connection("pi", False, source="SCENARIO")

        elif scenario_id == "pi_on":
            state.set_connection("pi", True, source="SCENARIO")

        # -----------------------------------------------------------
        # SENSOR FAULT
        # -----------------------------------------------------------
        elif scenario_id == "sensor_fault":
            state.reset(clear_events=False)
            # 동측 비상구의 Flame + MQ-2가 동시에 통신 단절된 상황.
            state.set_sensor_connection("FLM-15", False, source="SCENARIO")
            state.set_sensor_connection("MQ2-05", False, source="SCENARIO")

        elif scenario_id == "sensor_recover":
            state.set_sensor_connection("FLM-15", True, source="SCENARIO")
            state.set_sensor_connection("MQ2-05", True, source="SCENARIO")

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
