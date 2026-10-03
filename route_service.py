from __future__ import annotations

import heapq
from dataclasses import dataclass
from math import inf
from typing import Any


@dataclass(frozen=True)
class RouteResult:
    destination_id: str
    nodes: list[str]
    edges: list[str]
    cost: float
    destination_type: str = "exit"
    route_mode: str = "exit"

    def as_dict(self) -> dict[str, Any]:
        # exitId는 기존 프론트/코드와의 호환을 위해 유지한다.
        return {
            "exitId": self.destination_id,
            "destinationId": self.destination_id,
            "destinationType": self.destination_type,
            "routeMode": self.route_mode,
            "nodes": self.nodes,
            "edges": self.edges,
            "cost": self.cost,
        }


class FloorGraph:
    def __init__(self, floorplan: dict[str, Any]):
        self.nodes = {node["id"]: node for node in floorplan["nodes"]}
        self.exits = {exit_["id"]: exit_ for exit_ in floorplan["exits"]}
        self.edges = {edge["id"]: edge for edge in floorplan["edges"]}
        self.fallbacks = {
            item["id"]: item for item in floorplan.get("fallbackDestinations", [])
        }

        self.adjacency: dict[str, list[tuple[str, float, str]]] = {
            node_id: [] for node_id in [*self.nodes, *self.exits]
        }

        for edge in self.edges.values():
            start = edge["from"]
            end = edge["to"]
            weight = float(edge["weight"])
            if start not in self.adjacency or end not in self.adjacency:
                raise ValueError(f"Edge {edge['id']}가 알 수 없는 Node를 참조합니다: {start} -> {end}")
            self.adjacency[start].append((end, weight, edge["id"]))
            self.adjacency[end].append((start, weight, edge["id"]))

    def _shortest_to_targets(
        self,
        start_node: str,
        targets: set[str],
        blocked_nodes: set[str],
        blocked_edges: set[str],
        destination_type_by_id: dict[str, str],
        route_mode: str,
        edge_weight_overrides: dict[str, float] | None = None,
    ) -> RouteResult | None:
        if start_node not in self.nodes or start_node in blocked_nodes:
            return None

        targets = {
            target for target in targets
            if target in self.adjacency and target not in blocked_nodes
        }
        if not targets:
            return None

        distances = {node_id: inf for node_id in self.adjacency}
        previous: dict[str, tuple[str, str]] = {}
        distances[start_node] = 0.0
        queue: list[tuple[float, str]] = [(0.0, start_node)]
        destination: str | None = None

        while queue:
            current_cost, current = heapq.heappop(queue)
            if current_cost != distances[current]:
                continue

            if current in targets:
                destination = current
                break

            for neighbor, weight, edge_id in self.adjacency[current]:
                if edge_id in blocked_edges or neighbor in blocked_nodes:
                    continue
                effective_weight = (
                    float(edge_weight_overrides[edge_id])
                    if edge_weight_overrides and edge_id in edge_weight_overrides
                    else weight
                )
                candidate = current_cost + effective_weight
                if candidate < distances[neighbor]:
                    distances[neighbor] = candidate
                    previous[neighbor] = (current, edge_id)
                    heapq.heappush(queue, (candidate, neighbor))

        if destination is None:
            return None

        nodes = [destination]
        edges: list[str] = []
        cursor = destination
        while cursor != start_node:
            parent, edge_id = previous[cursor]
            nodes.append(parent)
            edges.append(edge_id)
            cursor = parent

        nodes.reverse()
        edges.reverse()

        return RouteResult(
            destination_id=destination,
            nodes=nodes,
            edges=edges,
            cost=distances[destination],
            destination_type=destination_type_by_id.get(destination, "exit"),
            route_mode=route_mode,
        )

    def shortest_route(
        self,
        start_node: str,
        blocked_nodes: set[str] | None = None,
        blocked_edges: set[str] | None = None,
        edge_weight_overrides: dict[str, float] | None = None,
    ) -> RouteResult | None:
        """1순위: 정규 비상구(EXIT) 중 최단 안전 경로."""
        blocked_nodes = blocked_nodes or set()
        blocked_edges = blocked_edges or set()

        available_exits = {
            exit_id
            for exit_id, exit_ in self.exits.items()
            if exit_.get("available", True)
        }

        return self._shortest_to_targets(
            start_node=start_node,
            targets=available_exits,
            blocked_nodes=blocked_nodes,
            blocked_edges=blocked_edges,
            destination_type_by_id={exit_id: "exit" for exit_id in available_exits},
            route_mode="exit",
            edge_weight_overrides=edge_weight_overrides,
        )

    def shortest_fallback_route(
        self,
        start_node: str,
        blocked_nodes: set[str] | None = None,
        blocked_edges: set[str] | None = None,
        edge_weight_overrides: dict[str, float] | None = None,
    ) -> RouteResult | None:
        """2순위: 정규 비상구가 모두 불가능할 때 지정된 보조 대피 지점으로 이동."""
        blocked_nodes = blocked_nodes or set()
        blocked_edges = blocked_edges or set()

        available = {
            destination_id
            for destination_id, config in self.fallbacks.items()
            if config.get("available", True)
        }
        types = {
            destination_id: self.fallbacks[destination_id].get("type", "fallback")
            for destination_id in available
        }

        return self._shortest_to_targets(
            start_node=start_node,
            targets=available,
            blocked_nodes=blocked_nodes,
            blocked_edges=blocked_edges,
            destination_type_by_id=types,
            route_mode="fallback",
            edge_weight_overrides=edge_weight_overrides,
        )

    def destination_name(self, destination_id: str) -> str:
        if destination_id in self.exits:
            return self.exits[destination_id].get("name", destination_id)
        if destination_id in self.fallbacks:
            return self.fallbacks[destination_id].get("name", destination_id)
        if destination_id in self.nodes:
            return self.nodes[destination_id].get("name", destination_id)
        return destination_id
