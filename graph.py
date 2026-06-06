"""
In-memory weighted graph over MRT + YouBike stations.
All edge weights are travel time in seconds.
"""
import heapq
import itertools
import math

import database as db

Graph     = dict[str, list[tuple[str, float]]]
Positions = dict[str, tuple[float, float]]

_MRT_SPEED  = 35_000 / 3600   # m/s  (~35 km/h)
_BIKE_SPEED = 15_000 / 3600   # m/s  (~15 km/h)
_WALK_SPEED =  5_000 / 3600   # m/s  (~5 km/h)

_BIKE_RADIUS = 2_000   # max distance for a bike edge (m)
_BIKE_MAX_K  = 5       # max neighbours per YouBike station
_WALK_RADIUS = 500     # max distance for a walk-transfer edge (m)


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    R = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _add(g: Graph, a: str, b: str, w: float) -> None:
    g.setdefault(a, []).append((b, w))
    g.setdefault(b, []).append((a, w))


def build_graph() -> tuple[Graph, Positions, dict[str, str]]:
    graph: Graph = {}
    pos:   Positions = {}
    node_colors: dict[str, str] = {}   # mrt node_id -> line color hex

    # ── MRT nodes ─────────────────────────────────────────────────────────────
    mrt = db.get_all_stations()
    for s in mrt:
        nid = f"mrt:{s['station_id']}"
        pos[nid] = (s['lat'], s['lng'])
        graph.setdefault(nid, [])

    # ── MRT edges (consecutive stations per line) ─────────────────────────────
    line_rows = db.get_lines_with_stations()   # already sorted by line_id, sequence
    for _, grp in itertools.groupby(line_rows, key=lambda r: r['line_id']):
        stops = list(grp)
        for stop in stops:
            nid = f"mrt:{stop['station_id']}"
            if nid not in node_colors:
                node_colors[nid] = stop['color_hex'] or '#888888'
        for i in range(len(stops) - 1):
            a = f"mrt:{stops[i]['station_id']}"
            b = f"mrt:{stops[i + 1]['station_id']}"
            d = haversine(
                stops[i]['lat'],     stops[i]['lng'],
                stops[i + 1]['lat'], stops[i + 1]['lng'],
            )
            _add(graph, a, b, d / _MRT_SPEED)

    # ── MRT interchange edges (same-location nodes on different lines) ────────
    # Groups nodes by (lat, lng); any two nodes at the same spot get a
    # 2-minute transfer penalty edge so A* can change lines there.
    _TRANSFER_SECS = 120.0
    coord_to_nodes: dict[tuple, list[str]] = {}
    for nid, (lat, lng) in pos.items():
        if nid.startswith("mrt:"):
            coord_to_nodes.setdefault((lat, lng), []).append(nid)
    for nodes in coord_to_nodes.values():
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                _add(graph, nodes[i], nodes[j], _TRANSFER_SECS)

    # ── YouBike nodes ─────────────────────────────────────────────────────────
    bike = db.get_all_youbike_stations()
    for s in bike:
        nid = f"bike:{s['station_id']}"
        pos[nid] = (s['lat'], s['lng'])
        graph.setdefault(nid, [])

    # ── YouBike edges (k-nearest neighbours within radius) ────────────────────
    for i, s in enumerate(bike):
        a    = f"bike:{s['station_id']}"
        near = []
        for j, t in enumerate(bike):
            if i == j:
                continue
            d = haversine(s['lat'], s['lng'], t['lat'], t['lng'])
            if d <= _BIKE_RADIUS:
                near.append((d, f"bike:{t['station_id']}"))
        near.sort()
        for d, b in near[:_BIKE_MAX_K]:
            # One-directional: b will add the reverse when it processes its own neighbours
            graph[a].append((b, d / _BIKE_SPEED))

    # ── Walk-transfer edges (MRT ↔ YouBike within radius) ────────────────────
    for m in mrt:
        for b in bike:
            d = haversine(m['lat'], m['lng'], b['lat'], b['lng'])
            if d <= _WALK_RADIUS:
                _add(graph, f"mrt:{m['station_id']}", f"bike:{b['station_id']}", d / _WALK_SPEED)

    n_nodes = len(pos)
    n_edges = sum(len(v) for v in graph.values())
    print(f"  graph built: {n_nodes} nodes, {n_edges} directed edges")
    return graph, pos, node_colors


def astar(
    graph: Graph,
    positions: Positions,
    start: str,
    goal: str,
) -> tuple[list[str], float] | None:
    """
    A* shortest path. Returns (path, total_seconds) or None if unreachable.
    Heuristic: straight-line distance to goal at MRT speed (admissible).
    """
    if start not in graph or goal not in graph:
        return None
    if start == goal:
        return [start], 0.0

    def h(node: str) -> float:
        lat1, lng1 = positions[node]
        lat2, lng2 = positions[goal]
        return haversine(lat1, lng1, lat2, lng2) / _MRT_SPEED

    g_score: dict[str, float] = {start: 0.0}
    came_from: dict[str, str] = {}
    counter = itertools.count()          # tie-breaker so we never compare strings
    open_set = [(h(start), next(counter), start)]
    closed: set[str] = set()

    while open_set:
        _, _, current = heapq.heappop(open_set)

        if current in closed:
            continue
        if current == goal:
            path, node = [], goal
            while node in came_from:
                path.append(node)
                node = came_from[node]
            path.append(start)
            path.reverse()
            return path, g_score[goal]

        closed.add(current)

        for neighbour, weight in graph[current]:
            if neighbour in closed:
                continue
            tentative_g = g_score[current] + weight
            if tentative_g < g_score.get(neighbour, float('inf')):
                came_from[neighbour] = current
                g_score[neighbour] = tentative_g
                heapq.heappush(open_set, (tentative_g + h(neighbour), next(counter), neighbour))

    return None
