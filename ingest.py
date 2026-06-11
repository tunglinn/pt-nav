"""
MRT data ingest — downloads station/line data from TDX and stores in SQLite.

Run once to populate the DB (re-run with --force to overwrite):
    python ingest.py
    python ingest.py --force
"""
import os
import sys

import database as db
import tdx


def _load_env() -> None:
    try:
        with open(".env", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    except FileNotFoundError:
        pass


# ── Lines ─────────────────────────────────────────────────────────────────────

def ingest_lines() -> int:
    data = tdx.get("/Rail/Metro/Line/TRTC")
    if not data:
        raise RuntimeError("TDX returned empty list for /Rail/Metro/Line/TRTC")

    print(f"  [debug] line keys: {list(data[0].keys())}")

    rows = []
    for l in data:
        rows.append((
            l["LineID"],
            l["LineName"]["Zh_tw"],
            l.get("LineName", {}).get("En", ""),
            l.get("LineColor") or l.get("LineColorCode", ""),
        ))

    with db._conn() as con:
        con.executemany(
            "INSERT OR REPLACE INTO mrt_lines (line_id, name_zh, name_en, color_hex) VALUES (?, ?, ?, ?)",
            rows,
        )
    print(f"  stored {len(rows)} lines")
    return len(rows)


# ── Stations ──────────────────────────────────────────────────────────────────

def ingest_stations() -> tuple[int, int]:
    """
    Fetch StationOfLine (has sequence + usually coordinates) and
    cross-check against Station (guaranteed coordinates).
    Returns (station_count, line_station_count).
    """
    raw = tdx.get("/Rail/Metro/StationOfLine/TRTC")
    if not raw:
        raise RuntimeError("TDX returned empty list for /Rail/Metro/StationOfLine/TRTC")

    print(f"  [debug] StationOfLine keys: {list(raw[0].keys())}")

    # Detect nested vs flat layout
    first = raw[0]
    nested_key = next((k for k in ("LineStations", "Stations") if k in first), None)
    if nested_key:
        print(f"  [debug] nested under key '{nested_key}'")
        sample_station = first[nested_key][0] if first[nested_key] else {}
        print(f"  [debug] station-in-line keys: {list(sample_station.keys())}")
    else:
        print("  [debug] flat layout (no nested key found)")

    stations: dict[str, dict] = {}   # station_id -> metadata
    seq_rows: list[tuple]     = []   # (line_id, station_id, sequence)

    if nested_key:
        for item in raw:
            line_id = item["LineID"]
            for idx, s in enumerate(item[nested_key]):
                sid = s["StationID"]
                if sid not in stations:
                    pos = s.get("StationPosition") or {}
                    stations[sid] = {
                        "name_zh": s["StationName"]["Zh_tw"],
                        "name_en": s.get("StationName", {}).get("En", ""),
                        "lat": pos.get("PositionLat", 0.0),
                        "lng": pos.get("PositionLon", 0.0),
                    }
                seq = (
                    s.get("Sequence")
                    or s.get("StationSequence")
                    or (idx + 1)
                )
                seq_rows.append((line_id, sid, int(seq)))
    else:
        for item in raw:
            sid = item["StationID"]
            if sid not in stations:
                pos = item.get("StationPosition") or {}
                stations[sid] = {
                    "name_zh": item["StationName"]["Zh_tw"],
                    "name_en": item.get("StationName", {}).get("En", ""),
                    "lat": pos.get("PositionLat", 0.0),
                    "lng": pos.get("PositionLon", 0.0),
                }
            seq = item.get("Sequence") or item.get("StationSequence", 0)
            seq_rows.append((item["LineID"], sid, int(seq)))

    # If StationOfLine lacked coordinates, fill from /Rail/Metro/Station/TRTC
    missing = [sid for sid, info in stations.items() if info["lat"] == 0.0]
    if missing:
        print(f"  {len(missing)} stations missing coordinates — fetching from /Station/TRTC...")
        details = tdx.get("/Rail/Metro/Station/TRTC")
        coord_map = {
            s["StationID"]: (
                s["StationPosition"]["PositionLat"],
                s["StationPosition"]["PositionLon"],
            )
            for s in details
        }
        for sid in missing:
            if sid in coord_map:
                stations[sid]["lat"], stations[sid]["lng"] = coord_map[sid]
            else:
                print(f"  [warn] no coordinates found for {sid}")

    with db._conn() as con:
        con.executemany(
            "INSERT OR REPLACE INTO mrt_stations "
            "(station_id, name_zh, name_en, lat, lng) VALUES (?, ?, ?, ?, ?)",
            [
                (sid, info["name_zh"], info["name_en"], info["lat"], info["lng"])
                for sid, info in stations.items()
            ],
        )
        con.executemany(
            "INSERT OR REPLACE INTO mrt_line_stations "
            "(line_id, station_id, sequence) VALUES (?, ?, ?)",
            seq_rows,
        )

    print(f"  stored {len(stations)} unique stations")
    print(f"  stored {len(seq_rows)} line-station links")
    return len(stations), len(seq_rows)


# ── YouBike ───────────────────────────────────────────────────────────────────

_YOUBIKE_CITIES = ("Taipei", "NewTaipei")


def ingest_youbike() -> int:
    rows = []
    for city in _YOUBIKE_CITIES:
        data = tdx.get(f"/Bike/Station/City/{city}")
        if not data:
            print(f"  [warn] TDX returned empty list for /Bike/Station/City/{city}")
            continue
        print(f"  [debug] {city} sample keys: {list(data[0].keys())}")
        for s in data:
            pos = s.get("StationPosition") or {}
            rows.append((
                s["StationUID"],
                s["StationName"]["Zh_tw"],
                s.get("StationName", {}).get("En", ""),
                pos.get("PositionLat", 0.0),
                pos.get("PositionLon", 0.0),
                city,
            ))

    with db._conn() as con:
        con.executemany(
            "INSERT OR REPLACE INTO youbike_stations "
            "(station_id, name_zh, name_en, lat, lng, city) VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
    print(f"  stored {len(rows)} YouBike stations")
    return len(rows)


# ── Branch line corrections ───────────────────────────────────────────────────
# TDX appends branch terminals at the end of the parent line's sequence, which
# creates a false long segment (e.g. Songshan → Xiaobitan on the green line).
# We move each branch terminal into its own mini-line with branch_from_station_id
# pointing at the true junction station.

_BRANCHES = [
    # (branch_line_id, name_zh, name_en, color_hex, parent_line_id, junction_id, terminal_ids...)
    ("G_BR", "小碧潭支線", "Xiaobitan Branch", "#80C342", "G", "G03",  ["G03A"]),
    ("R_BR", "新北投支線", "Xinbeitou Branch", "#F0A0B4", "R", "R28",  ["R28A"]),
    ("O_LZ", "蘆洲支線",   "Luzhou Branch",    "#F8A227", "O", "O12",  ["O50", "O51", "O52", "O53", "O54"]),
]


def fix_branches() -> None:
    with db._conn() as con:
        for line_id, name_zh, name_en, color, parent, junction, terminals in _BRANCHES:
            con.execute(
                "INSERT INTO mrt_lines (line_id, name_zh, name_en, color_hex, branch_from_station_id) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(line_id) DO UPDATE SET color_hex=excluded.color_hex, "
                "branch_from_station_id=excluded.branch_from_station_id",
                (line_id, name_zh, name_en, color, junction),
            )
            for terminal in terminals:
                con.execute(
                    "DELETE FROM mrt_line_stations WHERE line_id=? AND station_id=?",
                    (parent, terminal),
                )
            con.execute(
                "INSERT OR IGNORE INTO mrt_line_stations (line_id, station_id, sequence) VALUES (?,?,1)",
                (line_id, junction),
            )
            for seq, terminal in enumerate(terminals, start=2):
                con.execute(
                    "INSERT OR IGNORE INTO mrt_line_stations (line_id, station_id, sequence) VALUES (?,?,?)",
                    (line_id, terminal, seq),
                )
    print(f"  fixed {len(_BRANCHES)} branch lines")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    _load_env()
    db.init_db()

    force = "--force" in sys.argv

    if not force:
        mrt = db.station_count()
        yb = db.youbike_station_count()
        if mrt > 0 and yb > 0:
            print(f"DB already has {mrt} MRT stations and {yb} YouBike stations. Use --force to re-ingest.")
            return

    print("Ingesting MRT lines...")
    n_lines = ingest_lines()

    print("Ingesting MRT stations...")
    n_stations, n_links = ingest_stations()

    print("Ingesting YouBike stations...")
    n_youbike = ingest_youbike()

    print("Fixing branch lines...")
    fix_branches()

    print()
    print(f"Done: {n_lines} MRT lines, {n_stations} MRT stations, {n_links} line-station links, {n_youbike} YouBike stations")


if __name__ == "__main__":
    main()
