from __future__ import annotations

import heapq
from dataclasses import dataclass
from math import inf
from typing import Any


@dataclass(frozen=True)
class RouteResult:
    exit_id: str
    nodes: list[str]
    edges: list[str]
    cost: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "exitId": self.exit_id,
            "nodes": self.nodes,
            "edges": self.edges,
            "cost": self.cost,
        }


class FloorGraph:
    def __init__(self, floorplan: dict[str, Any]):
        self.nodes = {node["id"]: node for node in floorplan["nodes"]}
        self.exits = {exit_["id"]: exit_ for exit_ in floorplan["exits"]}
        self.edges = {edge["id"]: edge for edge in floorplan["edges"]}
        self.adjacency: dict[str, list[tuple[str, float, str]]] = {
            node_id: [] for node_id in [*self.nodes, *self.exits]
        }

        for edge in self.edges.values():
            start = edge["from"]
            end = edge["to"]
            weight = float(edge["weight"])
            self.adjacency[start].append((end, weight, edge["id"]))
            self.adjacency[end].append((start, weight, edge["id"]))

    def shortest_route(
        self,
        start_node: str,
        blocked_nodes: set[str] | None = None,
        blocked_edges: set[str] | None = None,
    ) -> RouteResult | None:
        blocked_nodes = blocked_nodes or set()
        blocked_edges = blocked_edges or set()

        if start_node not in self.nodes or start_node in blocked_nodes:
            return None

        available_exits = {
            exit_id
            for exit_id, exit_ in self.exits.items()
            if exit_.get("available", True)
        }
        if not available_exits:
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
            if current in available_exits:
                destination = current
                break

            for neighbor, weight, edge_id in self.adjacency[current]:
                if edge_id in blocked_edges or neighbor in blocked_nodes:
                    continue
                candidate = current_cost + weight
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
        return RouteResult(destination, nodes, edges, distances[destination])

