import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "pt_nav.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mrt_lines (
    line_id   TEXT PRIMARY KEY,
    name_zh   TEXT NOT NULL,
    name_en   TEXT,
    color_hex TEXT
);

CREATE TABLE IF NOT EXISTS mrt_stations (
    station_id TEXT PRIMARY KEY,
    name_zh    TEXT NOT NULL,
    name_en    TEXT,
    lat        REAL NOT NULL,
    lng        REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS mrt_line_stations (
    line_id    TEXT    NOT NULL REFERENCES mrt_lines(line_id),
    station_id TEXT    NOT NULL REFERENCES mrt_stations(station_id),
    sequence   INTEGER NOT NULL,
    PRIMARY KEY (line_id, station_id)
);

CREATE INDEX IF NOT EXISTS idx_mrt_line_seq
    ON mrt_line_stations(line_id, sequence);

CREATE INDEX IF NOT EXISTS idx_mrt_station_coords
    ON mrt_stations(lat, lng);

CREATE TABLE IF NOT EXISTS youbike_stations (
    station_id  TEXT PRIMARY KEY,
    name_zh     TEXT NOT NULL,
    name_en     TEXT,
    lat         REAL NOT NULL,
    lng         REAL NOT NULL,
    city        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_youbike_coords
    ON youbike_stations(lat, lng);
"""


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    return con


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _conn() as con:
        con.executescript(_SCHEMA)


def station_count() -> int:
    with _conn() as con:
        return con.execute("SELECT COUNT(*) FROM mrt_stations").fetchone()[0]


def youbike_station_count() -> int:
    with _conn() as con:
        return con.execute("SELECT COUNT(*) FROM youbike_stations").fetchone()[0]


def line_count() -> int:
    with _conn() as con:
        return con.execute("SELECT COUNT(*) FROM mrt_lines").fetchone()[0]


def get_all_stations() -> list[dict]:
    with _conn() as con:
        rows = con.execute("""
            SELECT s.station_id, s.name_zh, s.name_en, s.lat, s.lng,
                   GROUP_CONCAT(ls.line_id) AS lines
            FROM mrt_stations s
            LEFT JOIN mrt_line_stations ls USING (station_id)
            GROUP BY s.station_id
            ORDER BY s.name_en
        """).fetchall()
        return [dict(r) for r in rows]


def get_lines_with_stations() -> list[dict]:
    """Return every line-station row in line+sequence order."""
    with _conn() as con:
        rows = con.execute("""
            SELECT ls.line_id, ls.station_id, ls.sequence,
                   s.name_zh, s.name_en, s.lat, s.lng,
                   l.color_hex
            FROM mrt_line_stations ls
            JOIN mrt_stations s USING (station_id)
            JOIN mrt_lines l ON l.line_id = ls.line_id
            ORDER BY ls.line_id, ls.sequence
        """).fetchall()
        return [dict(r) for r in rows]


def get_all_youbike_stations() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT station_id, lat, lng FROM youbike_stations"
        ).fetchall()
        return [dict(r) for r in rows]


def get_stations_for_map() -> dict:
    with _conn() as con:
        mrt = con.execute("""
            SELECT s.station_id, s.name_zh, s.name_en, s.lat, s.lng,
                   GROUP_CONCAT(ls.line_id)    AS line_ids,
                   GROUP_CONCAT(l.color_hex)   AS line_colors
            FROM mrt_stations s
            LEFT JOIN mrt_line_stations ls USING (station_id)
            LEFT JOIN mrt_lines l ON l.line_id = ls.line_id
            GROUP BY s.station_id
            ORDER BY s.name_en
        """).fetchall()
        youbike = con.execute("""
            SELECT station_id, name_zh, name_en, lat, lng, city
            FROM youbike_stations
            ORDER BY name_zh
        """).fetchall()
    return {
        "mrt":    [dict(r) for r in mrt],
        "youbike": [dict(r) for r in youbike],
    }
