from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
import database as db
import graph as graph_module

router = APIRouter()


@router.get("/health")
def health():
    return {
        "status": "ok",
        "mrt_stations": db.station_count(),
        "mrt_lines": db.line_count(),
        "youbike_stations": db.youbike_station_count(),
    }


@router.get("/stations")
def stations():
    return db.get_stations_for_map()


@router.get("/graph/edges")
def graph_edges(request: Request):
    graph      = request.app.state.graph
    pos        = request.app.state.positions
    colors     = request.app.state.node_colors

    seen  = set()
    edges = []
    for a, neighbours in graph.items():
        for b, w in neighbours:
            key = frozenset((a, b))
            if key in seen:
                continue
            seen.add(key)

            a_lat, a_lng = pos[a]
            b_lat, b_lng = pos[b]
            a_mrt = a.startswith("mrt:")
            b_mrt = b.startswith("mrt:")

            if a_mrt and b_mrt:
                etype = "mrt"
                color = colors.get(a, "#888888")
            elif not a_mrt and not b_mrt:
                etype = "bike"
                color = "#22cc66"
            else:
                etype = "walk"
                color = "#ff8800"

            edges.append({
                "a_id": a, "a_lat": a_lat, "a_lng": a_lng,
                "b_id": b, "b_lat": b_lat, "b_lng": b_lng,
                "type": etype,
                "color": color,
                "weight_secs": round(w, 1),
            })

    return edges


class RouteRequest(BaseModel):
    from_id: str
    to_id: str


@router.post("/route")
def route(req: RouteRequest, request: Request):
    graph = request.app.state.graph
    pos   = request.app.state.positions

    if req.from_id not in graph:
        raise HTTPException(status_code=404, detail=f"Node not found: {req.from_id}")
    if req.to_id not in graph:
        raise HTTPException(status_code=404, detail=f"Node not found: {req.to_id}")

    result = graph_module.astar(graph, pos, req.from_id, req.to_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No path found between these nodes")

    path, total_secs = result

    segments = []
    for i in range(len(path) - 1):
        a, b = path[i], path[i + 1]
        weight = next(w for nb, w in graph[a] if nb == b)
        a_mrt, b_mrt = a.startswith("mrt:"), b.startswith("mrt:")
        if a_mrt and b_mrt:
            seg_type = "mrt"
        elif not a_mrt and not b_mrt:
            seg_type = "bike"
        else:
            seg_type = "walk"
        segments.append({"from": a, "to": b, "type": seg_type, "seconds": round(weight, 1)})

    return {
        "path":          path,
        "total_seconds": round(total_secs, 1),
        "total_minutes": round(total_secs / 60, 1),
        "segments":      segments,
    }


@router.get("/graph/stats")
def graph_stats(request: Request):
    graph = request.app.state.graph

    mrt_nodes  = [n for n in graph if n.startswith("mrt:")]
    bike_nodes = [n for n in graph if n.startswith("bike:")]

    seen = set()
    mrt_edges = bike_edges = walk_edges = 0
    for a, neighbours in graph.items():
        for b, _ in neighbours:
            key = frozenset((a, b))
            if key in seen:
                continue
            seen.add(key)
            a_mrt, b_mrt = a.startswith("mrt:"), b.startswith("mrt:")
            if a_mrt and b_mrt:
                mrt_edges += 1
            elif not a_mrt and not b_mrt:
                bike_edges += 1
            else:
                walk_edges += 1

    mrt_deg  = [len(graph[n]) for n in mrt_nodes]
    bike_deg = [len(graph[n]) for n in bike_nodes]

    return {
        "nodes": {
            "total": len(graph),
            "mrt":   len(mrt_nodes),
            "bike":  len(bike_nodes),
        },
        "edges": {
            "total": mrt_edges + bike_edges + walk_edges,
            "mrt":   mrt_edges,
            "bike":  bike_edges,
            "walk":  walk_edges,
        },
        "avg_degree": {
            "mrt":  round(sum(mrt_deg)  / len(mrt_deg)  if mrt_deg  else 0, 1),
            "bike": round(sum(bike_deg) / len(bike_deg) if bike_deg else 0, 1),
        },
    }
