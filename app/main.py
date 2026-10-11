"""HTTP layer: serves the page, the data, points on the flood model and the AI endpoints.

A point (a pin or a GPS fix) arrives only in a POST body and is never logged: the page snaps it to its 90 m square
before sending, and app/places.py snaps it again. Afterwards the page names it only by the square's id. The flood squares
around a covered point come back in the same answer, so the page asks for no block of squares by URL: a URL naming a
block would tell every server and proxy log the area, about 2 km, that a person is looking at.
"""
from __future__ import annotations

import base64
import binascii
import ipaddress
import logging
import os
import threading
import time
from collections import defaultdict, deque
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from fastapi import Depends, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.middleware.gzip import GZipMiddleware  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from google.genai import errors as genai_errors  # noqa: E402
from pydantic import AliasChoices, BaseModel, Field, StringConstraints, ValidationError  # noqa: E402
from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402

from . import (ai, areas, chatguard, dryspots, evacuation, floodtools, googlemaps, indexes, lowground, places,  # noqa: E402
               plan, raster, satellite, sections, stock, tide)

log = logging.getLogger("banjir")

MAX_QUESTION_CHARS = 500
MAX_TURN_CHARS = 2000
MAX_TURNS = 12
MAX_PHOTO_BYTES = 4 * 1024 * 1024
MAX_BODY_BYTES = 6 * 1024 * 1024   # a 4 MB photo as base64, plus headroom
TOO_LARGE_WORDS = "That upload is too large."
# what each photo type starts with, as (offset, bytes) pairs; the page re-encodes every photo as JPEG
PHOTO_SIGNATURES = {
    "image/jpeg": ((0, b"\xff\xd8\xff"),),
    "image/png": ((0, b"\x89PNG\r\n\x1a\n"),),
    "image/webp": ((0, b"RIFF"), (8, b"WEBP")),
}
MAX_AUDIO_BYTES = 1_000_000   # 30 s of 16 kHz mono 16-bit WAV, as voice.js records it
AUDIO_TYPES = {"audio/wav"}   # the page turns every recording into WAV, a format Gemini takes on every platform
NOT_HEARD = "Sorry, I could not hear a question in that recording. Try again, a little closer to the phone."
RATE_LIMIT = 20             # chat, photo and news: each one is a Gemini call
MAPS_RATE_LIMIT = 60        # rain and open-or-closed lookups: cheap, and fired as visitors click round the map
CALC_RATE_LIMIT = 120       # cost estimates from the form: arithmetic only, no Google call
GEO_RATE_LIMIT = 120        # point checks: one for each pin dropped or GPS fix
DRY_RATE_LIMIT = 600        # where to move the car: asked by the page for each place picked; a lookup in a file
MAP_RATE_LIMIT = 1200       # the flood model's coverage: asked for once per visit, and again after a failure
RATE_WINDOW_S = 300
MAX_AI_CALLS = 8            # Gemini calls in flight at once: each holds a pool thread for up to minutes, and the pool
AI_SLOT_WAIT_S = 2          # is shared with the data routes, so a visitor past the cap waits this long, then is told
AI_BUSY_WORDS = "The AI assistant is busy. Please try again in a minute."
AI_BUSY_CODES = (429, 503)   # Gemini's own "too many requests" and "overloaded"
AI_DAILY_LIMIT = int(os.environ.get("AI_DAILY_LIMIT", "1500"))   # AI answers a day, all visitors together (one answer
# can take up to ai.MAX_MODEL_REQUESTS Gemini requests; a spoken question is two answers)
AI_DAY_ZONE = timezone(timedelta(hours=8))   # the day turns at midnight Malaysia time
AI_RESTING_WORDS = "The AI assistant has reached today's limit and is resting. Please try again tomorrow."
GZIP_MIN_BYTES = 1024
GZIP_LEVEL = 6               # level 9 gains 2% on the area data for over twice the time, on the event loop
MAX_TRACKED_CLIENTS = 10_000
MAX_ID_CHARS = 40
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        # the 3D page's map (MapLibre) fetches its tiles, so the tile hosts are in connect-src as well as img-src;
        # its satellite photo is Esri's keyed World Imagery (app/satellite.py), never the keyless server
        "default-src 'self'; script-src 'self'; "
        "connect-src 'self' https://tile.openstreetmap.org https://ibasemaps-api.arcgis.com; "
        # inline styles only for Google's search suggestions, which must be shown as given; scripts stay 'self'
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
        "img-src 'self' data: blob: https://tile.openstreetmap.org https://ibasemaps-api.arcgis.com; "
        "frame-src 'none'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    # Referer holds the origin only, even on requests to this site, so no request repeats the page's address in a log;
    # OSM's tile servers still get the origin
    "Referrer-Policy": "strict-origin",
    "Permissions-Policy": "camera=(), microphone=(self), geolocation=(self)",   # GPS and voice for this page, no frame
}
# Google results may not be cached; a point is personal; a rotated imagery key must not linger in a cache
NO_STORE_PATHS = ("/api/rain", "/api/place/", "/api/point", "/api/dry-spot", "/api/satellite")
POST_ONLY = ("/api/ask", "/api/photo", "/api/estimate", "/api/dry-spot", "/api/news", "/api/point", "/api/stock", "/api/plan", "/api/voice")
# business_id: the name the page used before there were points. "place" wins whenever it is in the body, even as null:
# {"place": null, "business_id": "node-1"} selects nothing in /api/ask, and is a 422 in /api/photo and /api/estimate.
PLACE_NAMES = AliasChoices("place", "business_id")
POINT_WORDS = "Please check the location and try again."
NOT_COVERED_WORDS = "That point is not covered by the flood model in this build."
MODEL_DOWN_WORDS = "Could not read the flood model just now. Try again."
QUESTION_WORDS = f"Please check your input and try again. Questions can be up to {MAX_QUESTION_CHARS} characters."
VALIDATION_WORDS = (   # (path prefix, message) for a request body or path that does not fit; else QUESTION_WORDS
    ("/api/estimate", "Please check the figures. Use plain numbers, such as 50000."),
    ("/api/point", POINT_WORDS),
    ("/api/news", "Please reload the page and ask for the news again."),
    ("/api/photo", "The photo could not be sent. Please choose it again."),
    ("/api/plan", "Please choose Bahasa Melayu or English, and check the figures."),
    ("/api/voice", "The recording could not be sent. Please try again."),
    ("/api/stock", "The photo could not be sent. Please choose it again, and check the floor height (0 to 300 cm)."),
)
UNKNOWN_SECTION = "Unknown section."
PLACE_ERRORS = {"malformed": (422, POINT_WORDS), "unknown": (404, "Unknown business.")}   # else NOT_COVERED_WORDS
# FastAPI's 400 for a body json.loads cannot read without a JSONDecodeError: bad UTF-8, an integer of more than 4,300
# digits, nesting too deep. It is answered like any body that does not fit, in VALIDATION_WORDS.
BODY_UNREADABLE = "There was an error parsing the body"

app = FastAPI(title="Banjir shop flood check", docs_url=None, redoc_url=None, openapi_url=None)
# JSON and scripts shrink to a seventh or so (a point's answer: 71 KB to under 10 KB); short answers are not worth it
app.add_middleware(GZipMiddleware, minimum_size=GZIP_MIN_BYTES, compresslevel=GZIP_LEVEL)
_hits: dict[str, deque[float]] = defaultdict(deque)
_hits_lock = threading.Lock()
_ai_slots = threading.BoundedSemaphore(MAX_AI_CALLS)
_ai_today = {"day": None, "calls": 0}   # guarded by _hits_lock
areas.preload()   # a malformed area file stops the server here, at start-up, not in the middle of a request
sections.preload()


class Turn(BaseModel):
    """An earlier turn. The assistant's own come back with the signature they went out with (chatguard.sign); one
    without a matching signature is dropped, with its question, before the model sees the history."""
    role: Literal["user", "model"]
    text: str = Field(min_length=1, max_length=MAX_TURN_CHARS)
    sig: str | None = Field(default=None, max_length=64)


class AskIn(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUESTION_CHARS)]
    place: str | None = Field(default=None, max_length=MAX_ID_CHARS, validation_alias=PLACE_NAMES)
    area_id: str | None = Field(default=None, max_length=MAX_ID_CHARS)
    section_id: str | None = Field(default=None, max_length=MAX_ID_CHARS)
    history: list[Turn] = Field(default_factory=list, max_length=MAX_TURNS)


class NewsIn(BaseModel):
    """The news question is fixed: only the area (and section) it is about can be chosen. Other fields are ignored."""
    area_id: str | None = Field(default=None, max_length=MAX_ID_CHARS)
    section_id: str | None = Field(default=None, max_length=MAX_ID_CHARS)


class PhotoIn(BaseModel):
    place: str = Field(max_length=MAX_ID_CHARS, validation_alias=PLACE_NAMES)
    image: str = Field(min_length=32, description="data: URL, base64. Size is capped by MAX_BODY_BYTES and decode_photo.")


class VoiceIn(BaseModel):
    """A spoken question: a WAV recording as a data: URL, with the same selection and history as a typed one."""
    audio: str = Field(min_length=32)
    place: str | None = Field(default=None, max_length=MAX_ID_CHARS, validation_alias=PLACE_NAMES)
    area_id: str | None = Field(default=None, max_length=MAX_ID_CHARS)
    section_id: str | None = Field(default=None, max_length=MAX_ID_CHARS)
    history: list[Turn] = Field(default_factory=list, max_length=MAX_TURNS)


class StockIn(PhotoIn):
    """A photo of the shop's inside, and the floor height above the street if known (from the shop-front photo or the
    owner)."""
    floor_height_cm: float = Field(default=0, ge=0, le=300, allow_inf_nan=False)
    language: Literal["ms", "en"] = "en"


class EstimateIn(BaseModel):
    """The owner's own figures. Ranges and the rules between fields are checked in one place: floodtools.estimate_for."""
    place: str = Field(max_length=MAX_ID_CHARS, validation_alias=PLACE_NAMES)
    value_at_risk_rm: float = 0
    shop_size: str = Field(default="", max_length=20)
    floor_height_cm: float = 0
    daily_takings_rm: float = 0
    closed_days: float = 0
    raise_cm: float = 0
    measure_cost_rm: float = 0
    built_in_rm: float = 0
    vehicles_rm: float = 0
    unpaid_workers: float = 0


class PointIn(BaseModel):
    """A pin or a GPS fix, already snapped by the page. Numbers only (no text, no NaN or infinity), in range."""
    lat: float = Field(ge=-90, le=90, strict=True, allow_inf_nan=False)
    lon: float = Field(ge=-180, le=180, strict=True, allow_inf_nan=False)
    source: Literal["pin", "gps"]


def ok(data: dict) -> dict:
    return {"success": True, "data": data, "error": None}


def client_ip(request: Request) -> str:
    # Cloud Run and nginx append the real client address as the last X-Forwarded-For entry.
    forwarded = request.headers.get("x-forwarded-for", "")
    return visitor(forwarded.split(",")[-1].strip() or (request.client.host if request.client else "unknown"))


def visitor(address: str) -> str:
    """Who the limits count: the address, but an IPv6 one by its /64, the block one home or phone line usually gets,
    so changing the last part of the address does not give a fresh allowance."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return address
    return str(ipaddress.ip_network(f"{ip}/64", strict=False)) if ip.version == 6 else address


def _limit(request: Request, bucket: str, limit: int) -> None:
    # ponytail: in-memory, per instance, resets on restart. Enough to stop one visitor burning
    # the quota in a demo. For real traffic move this to Cloud Armor or an API gateway.
    now = time.monotonic()
    key = f"{bucket}:{client_ip(request)}"
    with _hits_lock:   # sync routes run in a thread pool: the count and the append must be one step
        if len(_hits) > MAX_TRACKED_CLIENTS:   # forget idle visitors so the table cannot grow forever
            for seen_key, seen in list(_hits.items()):
                if not seen or now - seen[-1] > RATE_WINDOW_S:
                    _hits.pop(seen_key, None)
            if len(_hits) > MAX_TRACKED_CLIENTS:
                raise HTTPException(429, "The service is busy. Please try again shortly.")
        hits = _hits[key]
        while hits and now - hits[0] > RATE_WINDOW_S:
            hits.popleft()
        if len(hits) >= limit:
            raise HTTPException(429, "Too many requests. Please wait a few minutes.")
        hits.append(now)


def rate_limit(request: Request) -> None:
    _limit(request, "ai", RATE_LIMIT)


def maps_limit(request: Request) -> None:
    _limit(request, "maps", MAPS_RATE_LIMIT)


def calc_limit(request: Request) -> None:
    _limit(request, "calc", CALC_RATE_LIMIT)


def dry_limit(request: Request) -> None:
    _limit(request, "dry", DRY_RATE_LIMIT)


def geo_limit(request: Request) -> None:
    _limit(request, "geo", GEO_RATE_LIMIT)


def map_limit(request: Request) -> None:
    _limit(request, "map", MAP_RATE_LIMIT)


def known_area(area_id: str | None) -> areas.Area:
    """The area with this id (or alias); the default area when none is given."""
    return known_scope(area_id)[0]


def known_scope(area_id: str | None, section_id: str | None = None) -> tuple[areas.Area, Mapping | None]:
    """(area, section) asked for: the default area when none is given, and an alias (an id that now means one section
    of an area) stands for its area and section. A section_id must be one of the area's; 404 otherwise."""
    area = areas.get(area_id) if area_id else areas.default()
    found = (area, None) if area else sections.alias(area_id)
    if found is None:
        raise HTTPException(404, "Unknown area.")
    area, section = found
    if section_id:
        section = sections.get(area, section_id)
        if section is None:
            raise HTTPException(404, UNKNOWN_SECTION)
    return area, section


def known_business(business_id: str) -> dict:
    """A business from any area."""
    found = areas.business(business_id)
    if found is None:
        raise HTTPException(404, "Unknown business.")
    return found[0]


def known_place(ref: str) -> dict:
    """A mapped business from any area, or a point the flood model covers (places.resolve). 404 for an unknown
    business or an uncovered point; 422 for a point id not in the exact form the server gives out."""
    try:
        return places.resolve(ref)
    except places.PlaceError as error:
        status, words = PLACE_ERRORS.get(error.reason, (404, NOT_COVERED_WORDS))
        raise HTTPException(status, words) from None


def question_scope(area_id: str | None, section_id: str | None,
                   place_ref: str | None) -> tuple[areas.Area | None, Mapping | None]:
    """(area, section) a chat question is about: the selected place's, else the ones asked for, else the default area.
    A selected business must be in the area asked for. A point brings its own area and section, None outside the
    listed areas, since the page's area need not hold it."""
    asked, section = known_scope(area_id, section_id) if area_id or section_id else (None, None)
    if not place_ref:
        return asked or areas.default(), section
    place = known_place(place_ref)
    area = places.area_of(place)
    if not place["is_point"] and asked is not None and area.id != asked.id:
        raise HTTPException(404, "Unknown business.")
    return area, sections.get(area, (place["section"] or {}).get("id")) if area else None


def decode_photo(data_url: str) -> tuple[bytes, str]:
    header, _, payload = data_url.partition(",")
    mime = header.removeprefix("data:").removesuffix(";base64")
    if not header.endswith(";base64") or mime not in PHOTO_SIGNATURES:
        raise HTTPException(415, "Please upload a JPEG, PNG or WebP photo.")
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(400, "The photo could not be read.") from exc
    if len(raw) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "The photo is too large. The limit is 4 MB.")
    if not all(raw[at:at + len(start)] == start for at, start in PHOTO_SIGNATURES[mime]):
        raise HTTPException(415, "Please upload a JPEG, PNG or WebP photo.")
    return raw, mime


def decode_audio(data_url: str) -> tuple[bytes, str]:
    """The recording's bytes and type from a data: URL; 415 for a type other than WAV, 413 over MAX_AUDIO_BYTES."""
    header, _, payload = data_url.partition(",")
    mime = header.removeprefix("data:").split(";")[0]
    if not header.endswith(";base64") or mime not in AUDIO_TYPES:
        raise HTTPException(415, "Please record again: the recording must be WAV audio.")
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(400, "The recording could not be read.") from exc
    if len(raw) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "That recording is too long. Keep a question under 30 seconds.")
    if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise HTTPException(415, "Please record again: the recording must be WAV audio.")
    return raw, mime


def count_ai_call() -> None:
    """One more AI answer today, or a 503 once AI_DAILY_LIMIT is reached: a cap on the bill whoever is asking.
    ponytail: in memory, per instance, so a restart starts the day's count again. Behind it sit the quotas and
    budget alert set in Google Cloud; with several instances, move the count to a shared store."""
    day = datetime.now(AI_DAY_ZONE).date()
    with _hits_lock:
        if _ai_today["day"] != day:
            _ai_today.update(day=day, calls=0)
        if _ai_today["calls"] >= AI_DAILY_LIMIT:
            raise HTTPException(503, AI_RESTING_WORDS)
        _ai_today["calls"] += 1


def call_ai(fn, *args):
    """Run an AI call; turn provider failures into clean HTTP errors without leaking details. At most MAX_AI_CALLS run
    at once, and at most AI_DAILY_LIMIT a day; a visitor past either, or one Gemini itself turns away as over its rate
    limit or overloaded, gets a 503."""
    count_ai_call()
    if not _ai_slots.acquire(timeout=AI_SLOT_WAIT_S):
        raise HTTPException(503, AI_BUSY_WORDS)
    try:
        return fn(*args)
    except ai.NotConfigured as exc:
        raise HTTPException(503, "The AI assistant is not set up yet. Add a Gemini key to .env.") from exc
    except raster.RasterError:
        raise   # damaged flood model files are model_unreadable's 503, not a failure of the AI provider
    except ValidationError as exc:   # the model's answer broke its schema; the error would repeat what it wrote
        log.error("AI call failed: %s: ValidationError", fn.__name__)
        raise HTTPException(502, "The AI assistant could not answer just now. Please try again.") from exc
    except Exception as exc:  # provider SDK raises many types; all mean "upstream failed"
        if isinstance(exc, genai_errors.APIError) and exc.code in AI_BUSY_CODES:
            log.warning("AI call turned away: %s: %s", fn.__name__, exc.code)
            raise HTTPException(503, AI_BUSY_WORDS) from exc
        log.exception("AI call failed: %s", fn.__name__)
        raise HTTPException(502, "The AI assistant could not answer just now. Please try again.") from exc
    finally:
        _ai_slots.release()


class BodyLimit:
    """Counts a request's body as it arrives and stops it at MAX_BODY_BYTES, whether or not it said how long it is:
    a chunked upload has no Content-Length for limits_and_headers to check. The 413 comes from the route's read."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        received = 0

        async def counted():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b"")) if message["type"] == "http.request" else 0
            if received > MAX_BODY_BYTES:
                raise HTTPException(413, TOO_LARGE_WORDS)
            return message

        await self.app(scope, counted, send)


app.add_middleware(BodyLimit)   # inside limits_and_headers, so its 413 carries the same headers


@app.middleware("http")
async def limits_and_headers(request: Request, call_next):
    # Reject oversized bodies before they are read into memory.
    length = request.headers.get("content-length", "0")
    if not length.isdigit() or int(length) > MAX_BODY_BYTES:
        response = JSONResponse({"success": False, "data": None, "error": TOO_LARGE_WORDS}, status_code=413)
    else:
        response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    if request.url.path.startswith(NO_STORE_PATHS):
        response.headers["Cache-Control"] = "no-store"
    elif not request.url.path.startswith("/api/"):
        # the page's files: checked again on every load (an unchanged one is a 304), so a deploy never mixes old and
        # new modules from the browser's cache
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.exception_handler(StarletteHTTPException)   # also covers 404s raised by the static mount
async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    if exc.status_code == 400 and exc.detail == BODY_UNREADABLE:
        return body_does_not_fit(request.url.path)
    return JSONResponse({"success": False, "data": None, "error": exc.detail}, status_code=exc.status_code,
                        headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, __: RequestValidationError) -> JSONResponse:
    return body_does_not_fit(request.url.path)


def body_does_not_fit(path: str) -> JSONResponse:
    """422 in the endpoint's plain words. The details are neither sent nor logged: they would repeat what was posted,
    such as a point."""
    message = next((words for prefix, words in VALIDATION_WORDS if path.startswith(prefix)), QUESTION_WORDS)
    return JSONResponse({"success": False, "data": None, "error": message}, status_code=422)


@app.exception_handler(raster.RasterError)
async def model_unreadable(_: Request, exc: raster.RasterError) -> JSONResponse:
    log.error("The flood model files could not be read: %s", exc)   # names a file and a tag, never a point
    return JSONResponse({"success": False, "data": None, "error": MODEL_DOWN_WORDS}, status_code=503)


def post_only() -> None:
    """A GET to an endpoint that takes a POST: 405, where the page's static mount would otherwise answer 404."""
    raise HTTPException(405, "Method Not Allowed", headers={"Allow": "POST"})


for _path in POST_ONLY:
    app.add_api_route(_path, post_only, methods=["GET"], include_in_schema=False)


GET_AND_HEAD = ["GET", "HEAD"]   # a monitor's HEAD gets the status line and headers of the same answer


def area_data(area: areas.Area, section: Mapping | None = None) -> dict:
    """An area's data for the page (app/sections.py says what a split area's city and section pages hold)."""
    if section is not None:
        found = sections.section_data(area, section)
    elif sections.has_sections(area):
        found = sections.city_data(area)
    else:
        found = {"area": sections.details(area), "premises": areas.premises(area.id), "town": areas.town(area.id)}
    return {**found, "limits": floodtools.LIMITS}


@app.api_route("/api/areas", methods=GET_AND_HEAD)
def area_list() -> dict:
    return ok({"default": areas.default().id, "areas": [sections.summary(area) for area in areas.load_all()]})


@app.api_route("/api/areas/{area_id}/data", methods=GET_AND_HEAD)
def one_area(area_id: str) -> dict:
    """An area's data; an alias's is its section's."""
    return ok(area_data(*known_scope(area_id)))


@app.api_route("/api/areas/{area_id}/sections/{section_id}/data", methods=GET_AND_HEAD)
def one_section(area_id: str, section_id: str) -> dict:
    """One section of a split area: its businesses in full and the squares of its box (app/sections.py)."""
    area, section = known_scope(area_id, section_id)
    return ok(area_data(area, section))


@app.api_route("/api/areas/{area_id}/layers/flash-flood.png", dependencies=[Depends(map_limit)],
               methods=GET_AND_HEAD)
def flash_flood_layer(area_id: str, request: Request) -> Response:
    """The flash flood potential map layer of an area (app/indexes.py)."""
    return png_answer(indexes.png_path(area_id), request)


@app.api_route("/api/areas/{area_id}/layers/low-ground-{level}.png", dependencies=[Depends(map_limit)],
               methods=GET_AND_HEAD)
def low_ground_layer(area_id: str, level: str, request: Request) -> Response:
    """The low ground map layer of an area at one level, 1, 2, 3 or 5 m (app/lowground.py); any other is a 404."""
    return png_answer(lowground.png_path(area_id, level), request)


def png_answer(path: Path | None, request: Request) -> Response:
    """A map layer's PNG, checked again on every load: an unchanged file (its ETag, from its size and time) is a 304;
    no file is a 404."""
    if path is None:
        raise HTTPException(404, "No layer.")
    found = FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache"}, stat_result=path.stat())
    wanted = (tag.strip().removeprefix("W/") for tag in request.headers.get("if-none-match", "").split(","))
    if found.headers["etag"] in wanted:
        return Response(status_code=304, headers={key: found.headers[key] for key in ("etag", "cache-control")})
    return found


@app.api_route("/api/data", methods=GET_AND_HEAD)
def data() -> dict:
    """The default area, as /api/areas/{id}/data gives it: a page with no area in its link asks for this at once, beside
    /api/areas, instead of waiting for the list to learn the default's id."""
    return one_area(areas.default().id)


@app.api_route("/api/status", methods=GET_AND_HEAD)
def status() -> dict:
    return ok({"ai_ready": ai.is_configured(), "model": ai.MODEL, "maps_ready": googlemaps.is_configured(),
               "points_ready": places.points_ready()})


@app.api_route("/api/satellite", dependencies=[Depends(map_limit)], methods=GET_AND_HEAD)
def satellite_photo() -> dict:
    """The 3D page's satellite tiles: `{tiles, attribution}`, the tile URL holding the public ArcGIS key, or null
    without ARCGIS_API_KEY (the page then shows the street map)."""
    return ok({"satellite": satellite.imagery()})


@app.post("/api/point", dependencies=[Depends(geo_limit)])
def check_point(body: PointIn) -> dict:
    """{coverage, region, place} for a pin or a GPS fix; a covered one also has the 2 x 2 blocks of squares around it
    (`blocks`, and their wet squares as `cells`, places.neighbourhood). A POST, so the point never sits in a URL or a
    log, and neither do the blocks, which name the area."""
    return ok(places.check(body.lat, body.lon))


@app.api_route("/api/coverage", dependencies=[Depends(map_limit)], methods=GET_AND_HEAD)
def coverage() -> dict:
    return ok(places.coverage())


@app.api_route("/api/evacuation", dependencies=[Depends(map_limit)], methods=GET_AND_HEAD)
def evacuation_centres(area: str | None = None, section: str | None = None) -> dict:
    """Evacuation centres open now near the area or section, from JKM's public feed (fetched at most every 5 minutes
    for everyone); `centres` is null while the feed is failing, and the page then leaves the card out."""
    found, part = known_scope(area, section)
    return ok({"centres": evacuation.for_box(part["bbox"] if part else found.view)})


@app.api_route("/api/tide", dependencies=[Depends(map_limit)], methods=GET_AND_HEAD)
def tide_today(area: str | None = None, section: str | None = None) -> dict:
    """Today's predicted high and low tides at the area's tide gauge; `tide` is null for an area without one."""
    found, _ = known_scope(area, section)
    return ok({"tide": tide.today(found.id)})


@app.post("/api/ask", dependencies=[Depends(rate_limit)])
def ask(body: AskIn) -> dict:
    area, section = question_scope(body.area_id, body.section_id, body.place)
    return ok(answer_question(body.question, body.place, body.history, area, section))


def answer_question(question: str, place: str | None, turns: list[Turn], area, section) -> dict:
    """The answer and its signature. A question after the assistant's set-up or secrets gets the refusal with no AI
    call; otherwise the model sees only the earlier turns it really answered (chatguard.trusted_history)."""
    refused = chatguard.screen_question(question)
    if refused:
        log.warning("Chat question refused: %s", refused)   # the reason only, never the words
        answer = chatguard.REFUSAL
    else:
        history = chatguard.trusted_history([turn.model_dump() for turn in turns])
        answer = call_ai(ai.ask, question, place, history, area, section)
    return {"answer": answer, "sig": chatguard.sign(question, answer[:MAX_TURN_CHARS])}


@app.post("/api/voice", dependencies=[Depends(rate_limit)])
def voice(body: VoiceIn, request: Request) -> dict:
    """A spoken question: Gemini writes down the words (ai.transcribe), which are then asked like typed ones. It is two
    Gemini calls, so a recording that can be used counts twice in the AI bucket. Neither the recording nor the words
    are logged."""
    area, section = question_scope(body.area_id, body.section_id, body.place)
    raw, mime = decode_audio(body.audio)
    rate_limit(request)
    heard = call_ai(ai.transcribe, raw, mime)
    question = heard.text.strip()[:MAX_QUESTION_CHARS]
    if not heard.is_speech or not question:
        raise HTTPException(422, NOT_HEARD)
    return ok({"question": question, "language": heard.language,
               **answer_question(question, body.place, body.history, area, section)})


@app.post("/api/photo", dependencies=[Depends(rate_limit)])
def photo(body: PhotoIn) -> dict:
    place = known_place(body.place)
    raw, mime = decode_photo(body.image)
    estimate = call_ai(ai.read_shop_photo, raw, mime)
    floor_m = estimate.floor_height_cm / 100
    above_floor = {rp: (None if depth is None else round(max(0.0, depth - floor_m), 2))
                   for rp, depth in place["depth_m"].items()}
    return ok({"estimate": estimate.model_dump(), "water_above_floor_m": above_floor})


@app.post("/api/stock", dependencies=[Depends(rate_limit)])
def stock_photo(body: StockIn) -> dict:
    """Gemini lists the stock and equipment in the photo with rough value ranges; stock.summarise says which of it is
    under the modelled water in each flood size. A photo that is not a shop's inside gets no figures."""
    place = known_place(body.place)
    raw, mime = decode_photo(body.image)
    estimate = call_ai(ai.read_stock_photo, raw, mime, body.language)
    found = stock.summarise([item.model_dump() for item in estimate.items], place["depth_m"], body.floor_height_cm)
    if not estimate.is_shop_inside:
        found = {"total": None, "suggested_value_rm": None, "per_flood": None}
    return ok({"estimate": estimate.model_dump(), "floor_height_cm": body.floor_height_cm, **found})


# floodtools words its errors for the AI model, which knows the argument names; the form shows them to people.
FORM_WORDS = (
    ("value_at_risk_rm", "the value of stock and equipment"), ("floor_height_cm", "the floor height in cm"),
    ("daily_takings_rm", "the takings per day"), ("closed_days", "the days closed"),
    ("raise_cm", "how far to raise the stock"), ("measure_cost_rm", "what that costs"), ("shop_size", "the shop size"),
    ("built_in_rm", "the value of renovation and built-ins"), ("vehicles_rm", "the value of vehicles"),
    ("unpaid_workers", "the number of workers"),
    ("Ask the owner which one fits.", "Choose the one that fits."), ("the owner's own", "your own"),
    ("Ask for that value.", "Give that value."), ("Ask for the value", "Give the value"),
)


def for_people(message: str) -> str:
    for model_words, people_words in FORM_WORDS:
        message = message.replace(model_words, people_words)
    return message[:1].upper() + message[1:]


class DrySpotIn(BaseModel):
    place: str = Field(max_length=MAX_ID_CHARS, validation_alias=PLACE_NAMES)


@app.post("/api/dry-spot", dependencies=[Depends(dry_limit)])
def dry_spot(body: DrySpotIn) -> dict:
    """Where to move the car: for each flood size, the nearest street point the model keeps dry (dryspots.nearest), or
    null spots for a place in an area without them. A POST, so a point's coordinates never sit in a URL or a log."""
    place = known_place(body.place)
    return ok({"spots": dryspots.nearest(place.get("area_id"), place["lat"], place["lon"])})


@app.post("/api/estimate", dependencies=[Depends(calc_limit)])
def estimate(body: EstimateIn) -> dict:
    place = known_place(body.place)
    result = floodtools.estimate_for(place, **body.model_dump(exclude={"place"}))
    if "error" in result:
        raise HTTPException(422, for_people(result["error"]))
    return ok(result)


class PlanIn(EstimateIn):
    """The place, the language, and the owner's figures if they have given any (the same as the cost form's)."""
    language: Literal["ms", "en"]
    floor_height_cm: float = Field(default=0, ge=0, le=300, allow_inf_nan=False)   # used even with no other figure


def plan_estimate(place: dict, body: PlanIn) -> dict | None:
    """The cost estimate for the plan's facts when the owner has given a value or a shop size, else None."""
    figures = body.model_dump(exclude={"place", "language"})
    if not (body.value_at_risk_rm or body.shop_size or body.raise_cm or body.measure_cost_rm):
        return None
    found = floodtools.estimate_for(place, **figures)
    if "error" in found:
        raise HTTPException(422, for_people(found["error"]))
    return found


@app.post("/api/plan", dependencies=[Depends(rate_limit)])
def flood_plan(body: PlanIn) -> dict:
    """A one-page flood plan: our facts and contacts, and the steps Gemini writes from the facts (plan.clean drops
    any link or phone number it adds)."""
    place = known_place(body.place)
    area = places.area_of(place)
    facts = plan.facts(place, area, body.floor_height_cm, plan_estimate(place, body))
    written = call_ai(ai.write_plan, facts, body.language)
    return ok({"language": body.language, "plan": plan.clean(written, facts, body.language), "facts": facts,
               "contacts": plan.contacts(area, body.language)})


def call_maps(fn, *args):
    """Run a Google Maps Platform call; upstream failures become a clean 502 without details."""
    try:
        return fn(*args)
    except googlemaps.UpstreamError as exc:
        log.warning("Google Maps call failed: %s", exc)
        raise HTTPException(502, "Google Maps did not answer just now. Please try again.") from exc


@app.get("/api/rain", dependencies=[Depends(maps_limit)])   # GET only: each answer is a billed Maps call
def rain(area: str | None = None, section: str | None = None) -> dict:
    """Rain over the middle of the area, or of one of its sections."""
    found, part = known_scope(area, section)
    lat, lon = sections.centre(part) if part else found.centre()
    if not googlemaps.is_configured():
        return ok({"configured": False, "rain": None})
    return ok({"configured": True, "rain": call_maps(googlemaps.rain_outlook, lat, lon, floodtools.RAIN_HOURS)})


@app.get("/api/place/{place_id}", dependencies=[Depends(maps_limit)])   # GET only, as /api/rain
def listing(place_id: str) -> dict:
    """How Google Maps lists a mapped business. Never for a point: it is not a business, and it does not go to Google."""
    if places.is_point_id(place_id):
        raise HTTPException(404, "Only mapped businesses have a Google Maps listing.")
    premise = known_business(place_id)
    if not googlemaps.is_configured():
        return ok({"configured": False, "place": None})
    return ok({"configured": True,
               "place": call_maps(googlemaps.place_status, premise["name"], premise["lat"], premise["lon"])})


@app.post("/api/news", dependencies=[Depends(rate_limit)])
def news(body: NewsIn | None = None) -> dict:
    # ponytail: only the area comes from the request; the question is fixed in ai.NEWS_QUESTION.
    # Grounded results may not be cached or framed (Gemini API terms), so each press is one Gemini call,
    # bounded by the per-visitor limit and the quotas set in Google Cloud.
    area, section = known_scope(body.area_id, body.section_id) if body else (areas.default(), None)
    return ok(call_ai(ai.flood_news, area, section))


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
