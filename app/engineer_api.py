"""Engineer mode's routes (app/engineer.py does the work): the rain pools layer, inspect, profile, basin, what-if,
upload and the downloads. router() is given main.py's helpers, so this module does not import main."""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from . import engineer

ENG_RATE_LIMIT = 120        # engineer mode lookups (inspect, profile, basin, exports): our own files, no Google call
ENG_RUN_LIMIT = 12          # engineer mode model runs (what-if, upload): each takes a second or two of CPU
MAX_ID_CHARS = 40           # as main.py
Lat = Annotated[float, Field(ge=-90, le=90)]
Lon = Annotated[float, Field(ge=-180, le=180)]
_main: dict = {}            # main.py's helpers, given to router()


class WhatIfIn(BaseModel):
    """A bund raised along a line, or a pond dug inside a shape, for engineer mode's what-if (app/engineer.py)."""
    area_id: str | None = Field(default=None, max_length=MAX_ID_CHARS)
    storm_mm: int = Field(ge=1, le=500)
    kind: Literal["bund", "pond"]
    points: list[tuple[Lat, Lon]] = Field(min_length=2, max_length=50)


class UploadIn(BaseModel):
    """An ESRI ASCII grid (.asc) of the visitor's own, run through the rain pools model and never stored."""
    asc: str = Field(min_length=10, max_length=engineer.MAX_ASC_BYTES)
    storm_mm: int = Field(ge=1, le=500)


def tool(fn, *args) -> dict:
    """An engineer mode tool's answer; what it cannot do is a 400 with its reason."""
    try:
        return _main["ok"](fn(*args))
    except engineer.ToolError as error:
        raise HTTPException(400, str(error)) from None


def area_id(area: str | None) -> str:
    return _main["known_area"](area).id


def eng_limit(request: Request) -> None:
    _main["limit"](request, "eng", ENG_RATE_LIMIT)


def eng_run_limit(request: Request) -> None:
    _main["limit"](request, "engrun", ENG_RUN_LIMIT)


def rain_pools_layer(area_id: str, mm: str, request: Request) -> Response:
    """The rain pools layer of an area for one storm, 40, 70 or 100 mm in an hour; any other is a 404."""
    return _main["png_answer"](engineer.png_path(area_id, mm), request)


def inspect(lat: Lat, lon: Lon, area: str | None = None) -> dict:
    """Every value the app holds at a spot."""
    return tool(engineer.inspect, area_id(area), lat, lon)


def profile(a_lat: Lat, a_lon: Lon, b_lat: Lat, b_lon: Lon, area: str | None = None) -> dict:
    """Heights, river depths and standing water along a line of up to 5 km."""
    return tool(engineer.profile, area_id(area), (a_lat, a_lon), (b_lat, b_lon))


def basin(lat: Lat, lon: Lon, area: str | None = None) -> dict:
    """The land that drains through a spot."""
    return tool(engineer.basin, area_id(area), lat, lon)


def whatif(body: WhatIfIn) -> dict:
    """Standing water with and without a bund or a pond."""
    return tool(engineer.whatif, area_id(body.area_id), body.storm_mm, body.kind, body.points)


def upload(body: UploadIn) -> dict:
    """Standing water on the visitor's own .asc grid; never stored."""
    return tool(engineer.upload, body.asc, body.storm_mm)


def export(area: str | None = None, section: str | None = None) -> Response:
    """The area's (or section's) businesses with every value at each, as a CSV download."""
    found, part = _main["known_scope"](area, section)
    name = f"myflood-{found.id}{'-' + part['id'] if part else ''}.csv"
    return Response(engineer.export_csv(found.id, part["id"] if part else None), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


def pool_tif(mm: str, area: str | None = None) -> Response:
    """The rain pools GeoTIFF for one storm (CC BY-NC-SA 4.0)."""
    found = _main["known_area"](area)
    path = engineer.tif_path(found.id, mm)
    if path is None:
        raise HTTPException(404, "No layer.")
    return FileResponse(path, media_type="image/tiff", filename=f"myflood-{found.id}-rain-pools-{mm}mm.tif")


def router(*, limit, known_area, known_scope, ok, png_answer, map_limit, methods) -> APIRouter:
    """The routes, with main.py's rate limiter, scope lookups, answer envelope and PNG answer."""
    _main.update(limit=limit, known_area=known_area, known_scope=known_scope, ok=ok, png_answer=png_answer)
    api = APIRouter()
    light, heavy = [Depends(eng_limit)], [Depends(eng_run_limit)]
    api.add_api_route("/api/areas/{area_id}/layers/rain-pools-{mm}.png", rain_pools_layer, methods=list(methods),
                      dependencies=[Depends(map_limit)])
    api.add_api_route("/api/eng/inspect", inspect, methods=["GET"], dependencies=light)
    api.add_api_route("/api/eng/profile", profile, methods=["GET"], dependencies=light)
    api.add_api_route("/api/eng/basin", basin, methods=["GET"], dependencies=light)
    api.add_api_route("/api/eng/whatif", whatif, methods=["POST"], dependencies=heavy)
    api.add_api_route("/api/eng/upload", upload, methods=["POST"], dependencies=heavy)
    api.add_api_route("/api/eng/export.csv", export, methods=["GET"], dependencies=light)
    api.add_api_route("/api/eng/rain-pools-{mm}.tif", pool_tif, methods=["GET"], dependencies=light)
    return api
