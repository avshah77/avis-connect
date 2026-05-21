"""
AVIS Connect — FastAPI application entry point.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from connect.routes import admin, api, ui

app = FastAPI(
    title       = "AVIS Connect",
    description = "Lightweight integration gateway — plugin-based connector execution engine.",
    version     = "1.0.0",
    docs_url    = "/docs",
    redoc_url   = "/redoc",
)

app.mount("/static", StaticFiles(directory="connect/static"), name="static")

app.include_router(ui.router)
app.include_router(api.router)
app.include_router(api.router_sf)
app.include_router(admin.router)


@app.get("/ping")
def ping():
    return {"status": "ok", "service": "avis-connect"}
