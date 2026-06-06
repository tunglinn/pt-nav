import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import api
import database as db


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_env()
    db.init_db()
    yield


app = FastAPI(title="pt-nav", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api.router)
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
