from fastapi import APIRouter
import database as db

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
