"""HTTP layer: serves the page, the data, points on the flood model and the AI endpoints.

A point (a pin or a GPS fix) arrives only in a POST body and is never logged: the page snaps it to its 90 m square
before sending, and app/places.py snaps it again. Afterwards the page names it only by the square's id. The flood squares
around a covered point come back in the same answer, so the page asks for no block of squares by URL: a URL naming a
block would tell every server and proxy log the area, about 2 km, that a person is looking at.
"""
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
from fastapi.middleware.gzip import GZipMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import AliasChoices, BaseModel, Field, StringConstraints, ValidationError  # noqa: E402
from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402

from . import ai, areas, floodtools, googlemaps, places, plan, raster, stock  # noqa: E402

log = logging.getLogger("banjir")

MAX_QUESTION_CHARS = 500
MAX_TURN_CHARS = 2000
MAX_TURNS = 12
MAX_PHOTO_BYTES = 4 * 1024 * 1024
MAX_BODY_BYTES = 6 * 1024 * 1024   # a 4 MB photo as base64, plus headroom
PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_AUDIO_BYTES = 1_000_000   # 30 s of 16 kHz mono 16-bit WAV, as voice.js records it
AUDIO_TYPES = {"audio/wav"}   # the page turns every recording into WAV, a format Gemini takes on every platform
NOT_HEARD = "Sorry, I could not hear a question in that recording. Try again, a little closer to the phone."
RATE_LIMIT = 20             # chat, photo and news: each one is a Gemini call
MAPS_RATE_LIMIT = 60        # rain and open-or-closed lookups: cheap, and fired as visitors click round the map
CALC_RATE_LIMIT = 120       # cost estimates from the form: arithmetic only, no Google call
GEO_RATE_LIMIT = 120        # point checks: one for each pin dropped or GPS fix
MAP_RATE_LIMIT = 1200       # the flood model's coverage: asked for once per visit, and again after a failure
RATE_WINDOW_S = 300
GZIP_MIN_BYTES = 1024
GZIP_LEVEL = 6               # level 9 gains 2% on the area data for over twice the time, on the event loop
MAX_TRACKED_CLIENTS = 10_000
MAX_ID_CHARS = 40
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
    # Referer holds the origin only, even on requests to this site, so no request repeats the page's address in a log;
    # OSM's tile servers still get the origin
    "Referrer-Policy": "strict-origin",
    "Permissions-Policy": "camera=(), microphone=(self), geolocation=(self)",   # GPS and voice for this page, no frame
}
NO_STORE_PATHS = ("/api/rain", "/api/place/", "/api/point")   # Google results may not be cached; a point is personal
POST_ONLY = ("/api/ask", "/api/photo", "/api/estimate", "/api/news", "/api/point", "/api/stock", "/api/plan", "/api/voice")
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
PLACE_ERRORS = {"malformed": (422, POINT_WORDS), "unknown": (404, "Unknown business.")}   # else NOT_COVERED_WORDS
# FastAPI's 400 for a body json.loads cannot read without a JSONDecodeError: bad UTF-8, an integer of more than 4,300
# digits, nesting too deep. It is answered like any body that does not fit, in VALIDATION_WORDS.
BODY_UNREADABLE = "There was an error parsing the body"

app = FastAPI(title="Banjir shop flood check", docs_url=None, redoc_url=None, openapi_url=None)
# JSON and scripts shrink to a seventh or so (a point's answer: 71 KB to under 10 KB); short answers are not worth it
app.add_middleware(GZipMiddleware, minimum_size=GZIP_MIN_BYTES, compresslevel=GZIP_LEVEL)
_hits: dict[str, deque[float]] = defaultdict(deque)
areas.preload()   # a malformed area file stops the server here, at start-up, not in the middle of a request


class Turn(BaseModel):
    role: Literal["user", "model"]
    text: str = Field(min_length=1, max_length=MAX_TURN_CHARS)


class AskIn(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUESTION_CHARS)]
    place: str | None = Field(default=None, max_length=MAX_ID_CHARS, validation_alias=PLACE_NAMES)
    area_id: str | None = Field(default=None, max_length=MAX_ID_CHARS)
    history: list[Turn] = Field(default_factory=list, max_length=MAX_TURNS)


class NewsIn(BaseModel):
    """The news question is fixed: only the area it is about can be chosen. Other fields are ignored."""
    area_id: str | None = Field(default=None, max_length=MAX_ID_CHARS)


class PhotoIn(BaseModel):
    place: str = Field(max_length=MAX_ID_CHARS, validation_alias=PLACE_NAMES)
    image: str = Field(min_length=32, description="data: URL, base64. Size is capped by MAX_BODY_BYTES and decode_photo.")


class VoiceIn(BaseModel):
    """A spoken question: a WAV recording as a data: URL, with the same selection and history as a typed one."""
    audio: str = Field(min_length=32)
    place: str | None = Field(default=None, max_length=MAX_ID_CHARS, validation_alias=PLACE_NAMES)
    area_id: str | None = Field(default=None, max_length=MAX_ID_CHARS)
    history: list[Turn] = Field(default_factory=list, max_length=MAX_TURNS)


class StockIn(PhotoIn):
    """A photo of the shop's inside, and the floor height above the street if known (from the shop-front photo or the
    owner)."""
    floor_height_cm: float = Field(default=0, ge=0, le=300, allow_inf_nan=False)


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


class PointIn(BaseModel):
    """A pin or a GPS fix, already snapped by the page. Numbers only (no text, no NaN or infinity), in range."""
    lat: float = Field(ge=-90, le=90, strict=True, allow_inf_nan=False)
    lon: float = Field(ge=-180, le=180, strict=True, allow_inf_nan=False)
    source: Literal["pin", "gps"]


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


def calc_limit(request: Request) -> None:
    _limit(request, "calc", CALC_RATE_LIMIT)


def geo_limit(request: Request) -> None:
    _limit(request, "geo", GEO_RATE_LIMIT)


def map_limit(request: Request) -> None:
    _limit(request, "map", MAP_RATE_LIMIT)


def known_area(area_id: str | None) -> areas.Area:
    """The area with this id; the default area when none is given."""
    if not area_id:
        return areas.default()
    area = areas.get(area_id)
    if area is None:
        raise HTTPException(404, "Unknown area.")
    return area


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


def question_area(area_id: str | None, place_ref: str | None) -> areas.Area | None:
    """The area a chat question is about: the selected place's, else the one asked for, else the default. A selected
    business must be in the area asked for. A point brings its own area, None outside the listed areas, since the
    page's area need not hold it."""
    asked = known_area(area_id) if area_id else None
    if not place_ref:
        return asked or areas.default()
    place = known_place(place_ref)
    area = places.area_of(place)
    if not place["is_point"] and asked is not None and area.id != asked.id:
        raise HTTPException(404, "Unknown business.")
    return area


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


def call_ai(fn, *args):
    """Run an AI call; turn provider failures into clean HTTP errors without leaking details."""
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


def area_data(area: areas.Area) -> dict:
    return {"premises": areas.premises(area.id), "town": areas.town(area.id), "limits": floodtools.LIMITS}


@app.get("/api/areas")
def area_list() -> dict:
    return ok({"default": areas.default().id, "areas": [areas.summary(area) for area in areas.load_all()]})


@app.get("/api/areas/{area_id}/data")
def one_area(area_id: str) -> dict:
    area = known_area(area_id)
    return ok({"area": areas.details(area), **area_data(area)})


@app.get("/api/data")
def data() -> dict:
    """The default area, as /api/areas/{id}/data gives it: a page with no area in its link asks for this at once, beside
    /api/areas, instead of waiting for the list to learn the default's id."""
    return one_area(areas.default().id)


@app.get("/api/status")
def status() -> dict:
    return ok({"ai_ready": ai.is_configured(), "model": ai.MODEL, "maps_ready": googlemaps.is_configured(),
               "points_ready": places.points_ready()})


@app.post("/api/point", dependencies=[Depends(geo_limit)])
def check_point(body: PointIn) -> dict:
    """{coverage, region, place} for a pin or a GPS fix; a covered one also has the 2 x 2 blocks of squares around it
    (`blocks`, and their wet squares as `cells`, places.neighbourhood). A POST, so the point never sits in a URL or a
    log, and neither do the blocks, which name the area."""
    return ok(places.check(body.lat, body.lon))


@app.get("/api/coverage", dependencies=[Depends(map_limit)])
def coverage() -> dict:
    return ok(places.coverage())


@app.post("/api/ask", dependencies=[Depends(rate_limit)])
def ask(body: AskIn) -> dict:
    area = question_area(body.area_id, body.place)
    history = [turn.model_dump() for turn in body.history]
    return ok({"answer": call_ai(ai.ask, body.question, body.place, history, area)})


@app.post("/api/voice", dependencies=[Depends(rate_limit)])
def voice(body: VoiceIn, request: Request) -> dict:
    """A spoken question: Gemini writes down the words (ai.transcribe), which are then asked like typed ones. It is two
    Gemini calls, so a recording that can be used counts twice in the AI bucket. Neither the recording nor the words
    are logged."""
    area = question_area(body.area_id, body.place)
    raw, mime = decode_audio(body.audio)
    rate_limit(request)
    heard = call_ai(ai.transcribe, raw, mime)
    question = heard.text.strip()[:MAX_QUESTION_CHARS]
    if not heard.is_speech or not question:
        raise HTTPException(422, NOT_HEARD)
    history = [turn.model_dump() for turn in body.history]
    return ok({"question": question, "language": heard.language,
               "answer": call_ai(ai.ask, question, body.place, history, area)})


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
    estimate = call_ai(ai.read_stock_photo, raw, mime)
    found = stock.summarise([item.model_dump() for item in estimate.items], place["depth_m"], body.floor_height_cm)
    if not estimate.is_shop_inside:
        found = {"total": None, "suggested_value_rm": None, "per_flood": None}
    return ok({"estimate": estimate.model_dump(), "floor_height_cm": body.floor_height_cm, **found})


# floodtools words its errors for the AI model, which knows the argument names; the form shows them to people.
FORM_WORDS = (
    ("value_at_risk_rm", "the value of stock and equipment"), ("floor_height_cm", "the floor height in cm"),
    ("daily_takings_rm", "the takings per day"), ("closed_days", "the days closed"),
    ("raise_cm", "how far to raise the stock"), ("measure_cost_rm", "what that costs"), ("shop_size", "the shop size"),
    ("Ask the owner which one fits.", "Choose the one that fits."), ("the owner's own", "your own"),
    ("Ask for that value.", "Give that value."), ("Ask for the value", "Give the value"),
)


def for_people(message: str) -> str:
    for model_words, people_words in FORM_WORDS:
        message = message.replace(model_words, people_words)
    return message[:1].upper() + message[1:]


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


@app.get("/api/rain", dependencies=[Depends(maps_limit)])
def rain(area: str | None = None) -> dict:
    lat, lon = known_area(area).centre()
    if not googlemaps.is_configured():
        return ok({"configured": False, "rain": None})
    return ok({"configured": True, "rain": call_maps(googlemaps.rain_outlook, lat, lon, floodtools.RAIN_HOURS)})


@app.get("/api/place/{place_id}", dependencies=[Depends(maps_limit)])
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
    area = known_area(body.area_id if body else None)
    return ok(call_ai(ai.flood_news, area))


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
