"""
In-memory weighted graph over MRT + YouBike stations.
All edge weights are travel time in seconds.
"""
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
