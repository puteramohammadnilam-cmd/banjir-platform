"""HTTP layer: serves the page, the data and two AI endpoints."""
from __future__ import annotations

import base64
import binascii
import logging
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Annotated, Literal

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from fastapi import Depends, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field, StringConstraints  # noqa: E402
from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402

from . import ai, floodtools, googlemaps  # noqa: E402

log = logging.getLogger("banjir")

MAX_QUESTION_CHARS = 500
MAX_TURN_CHARS = 2000
MAX_TURNS = 12
MAX_PHOTO_BYTES = 4 * 1024 * 1024
MAX_BODY_BYTES = 6 * 1024 * 1024   # a 4 MB photo as base64, plus headroom
PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp"}
RATE_LIMIT = 20             # chat, photo and news: each one is a Gemini call
MAPS_RATE_LIMIT = 60        # rain and open-or-closed lookups: cheap, and fired as visitors click round the map
RATE_WINDOW_S = 300
MAX_TRACKED_CLIENTS = 10_000
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; connect-src 'self'; "
        # inline styles only for Google's search suggestions, which must be shown as given; scripts stay 'self'
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
        "img-src 'self' data: https://tile.openstreetmap.org; "
        "frame-src 'none'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

app = FastAPI(title="Banjir shop flood check", docs_url=None, redoc_url=None, openapi_url=None)
_hits: dict[str, deque[float]] = defaultdict(deque)


class Turn(BaseModel):
    role: Literal["user", "model"]
    text: str = Field(min_length=1, max_length=MAX_TURN_CHARS)


class AskIn(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUESTION_CHARS)]
    business_id: str | None = Field(default=None, max_length=40)
    history: list[Turn] = Field(default_factory=list, max_length=MAX_TURNS)


class PhotoIn(BaseModel):
    business_id: str = Field(max_length=40)
    image: str = Field(min_length=32, description="data: URL, base64. Size is capped by MAX_BODY_BYTES and decode_photo.")


def ok(data: dict) -> dict:
    return {"success": True, "data": data, "error": None}


def client_ip(request: Request) -> str:
    # Cloud Run appends the real client address as the last X-Forwarded-For entry.
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[-1].strip() or (request.client.host if request.client else "unknown")


def _limit(request: Request, bucket: str, limit: int) -> None:
    # ponytail: in-memory, per instance, resets on restart. Enough to stop one visitor burning
    # the quota in a demo. For real traffic move this to Cloud Armor or an API gateway.
    now = time.monotonic()
    if len(_hits) > MAX_TRACKED_CLIENTS:   # forget idle visitors so the table cannot grow forever
        for key, seen in list(_hits.items()):
            if not seen or now - seen[-1] > RATE_WINDOW_S:
                _hits.pop(key, None)
        if len(_hits) > MAX_TRACKED_CLIENTS:
            raise HTTPException(429, "The service is busy. Please try again shortly.")
    hits = _hits[f"{bucket}:{client_ip(request)}"]
    while hits and now - hits[0] > RATE_WINDOW_S:
        hits.popleft()
    if len(hits) >= limit:
        raise HTTPException(429, "Too many requests. Please wait a few minutes.")
    hits.append(now)


def rate_limit(request: Request) -> None:
    _limit(request, "ai", RATE_LIMIT)


def maps_limit(request: Request) -> None:
    _limit(request, "maps", MAPS_RATE_LIMIT)


def known_business(business_id: str) -> dict:
    premise = floodtools.get(business_id)
    if premise is None:
        raise HTTPException(404, "Unknown business.")
    return premise


def decode_photo(data_url: str) -> tuple[bytes, str]:
    header, _, payload = data_url.partition(",")
    mime = header.removeprefix("data:").removesuffix(";base64")
    if not header.endswith(";base64") or mime not in PHOTO_TYPES:
        raise HTTPException(415, "Please upload a JPEG, PNG or WebP photo.")
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(400, "The photo could not be read.") from exc
    if len(raw) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "The photo is too large. The limit is 4 MB.")
    return raw, mime


def call_ai(fn, *args):
    """Run an AI call; turn provider failures into clean HTTP errors without leaking details."""
    try:
        return fn(*args)
    except ai.NotConfigured as exc:
        raise HTTPException(503, "The AI assistant is not set up yet. Add a Gemini key to .env.") from exc
    except Exception as exc:  # provider SDK raises many types; all mean "upstream failed"
        log.exception("AI call failed: %s", fn.__name__)
        raise HTTPException(502, "The AI assistant could not answer just now. Please try again.") from exc


@app.middleware("http")
async def limits_and_headers(request: Request, call_next):
    # Reject oversized bodies before they are read into memory.
    length = request.headers.get("content-length", "0")
    if not length.isdigit() or int(length) > MAX_BODY_BYTES:
        response = JSONResponse({"success": False, "data": None, "error": "That upload is too large."}, status_code=413)
    else:
        response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    return response


@app.exception_handler(StarletteHTTPException)   # also covers 404s raised by the static mount
async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse({"success": False, "data": None, "error": exc.detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, __: RequestValidationError) -> JSONResponse:
    message = f"Please check your input and try again. Questions can be up to {MAX_QUESTION_CHARS} characters."
    return JSONResponse({"success": False, "data": None, "error": message}, status_code=422)


@app.get("/api/data")
def data() -> dict:
    return ok({"premises": floodtools.premises(), "town": floodtools.town(), "limits": floodtools.LIMITS})


@app.get("/api/status")
def status() -> dict:
    return ok({"ai_ready": ai.is_configured(), "model": ai.MODEL, "maps_ready": googlemaps.is_configured()})


@app.post("/api/ask", dependencies=[Depends(rate_limit)])
def ask(body: AskIn) -> dict:
    if body.business_id:
        known_business(body.business_id)
    history = [turn.model_dump() for turn in body.history]
    return ok({"answer": call_ai(ai.ask, body.question, body.business_id, history)})


@app.post("/api/photo", dependencies=[Depends(rate_limit)])
def photo(body: PhotoIn) -> dict:
    premise = known_business(body.business_id)
    raw, mime = decode_photo(body.image)
    estimate = call_ai(ai.read_shop_photo, raw, mime)
    floor_m = estimate.floor_height_cm / 100
    above_floor = {rp: (None if depth is None else round(max(0.0, depth - floor_m), 2))
                   for rp, depth in premise["depth_m"].items()}
    return ok({"estimate": estimate.model_dump(), "water_above_floor_m": above_floor})


def call_maps(fn, *args):
    """Run a Google Maps Platform call; upstream failures become a clean 502 without details."""
    try:
        return fn(*args)
    except googlemaps.UpstreamError as exc:
        log.warning("Google Maps call failed: %s", exc)
        raise HTTPException(502, "Google Maps did not answer just now. Please try again.") from exc


@app.get("/api/rain", dependencies=[Depends(maps_limit)])
def rain() -> dict:
    if not googlemaps.is_configured():
        return ok({"configured": False, "rain": None})
    return ok({"configured": True, "rain": call_maps(googlemaps.rain_outlook, *floodtools.area_centre(),
                                                     floodtools.RAIN_HOURS)})


@app.get("/api/place/{business_id}", dependencies=[Depends(maps_limit)])
def place(business_id: str) -> dict:
    premise = known_business(business_id)
    if not googlemaps.is_configured():
        return ok({"configured": False, "place": None})
    return ok({"configured": True,
               "place": call_maps(googlemaps.place_status, premise["name"], premise["lat"], premise["lon"])})


@app.post("/api/news", dependencies=[Depends(rate_limit)])
def news() -> dict:
    # ponytail: a request body, if any, is ignored on purpose: the question is fixed in ai.NEWS_QUESTION.
    # Grounded results may not be cached or framed (Gemini API terms), so each press is one Gemini call,
    # bounded by the per-visitor limit and the quotas set in Google Cloud.
    return ok(call_ai(ai.flood_news))


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
