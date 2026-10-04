"""Server hardening: streamed body size, the AI concurrency cap, Gemini overload, the rate limiter's lock, HEAD, photo types.

Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_server_fixes.py
"""
import base64
import threading
import time
from collections import defaultdict, deque
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from google.genai import errors

from app import ai, floodtools, main

KNOWN_ID = floodtools.premises()[0]["id"]
JPEG = b"\xff\xd8\xff" + b"0" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"0" * 64
BUSY = "busy"
TOO_LARGE = {"success": False, "data": None, "error": "That upload is too large."}


def data_url(mime: str, raw: bytes) -> str:
    return f"data:{mime};base64," + base64.b64encode(raw).decode()


@pytest.fixture
def client(monkeypatch):
    main._hits.clear()
    monkeypatch.setattr(ai, "ask", lambda question, place, history, area, section=None: "answer")
    monkeypatch.setattr(ai, "read_shop_photo", lambda image, mime: ai.PhotoEstimate(
        is_shop_front=True, floor_height_cm=30, steps_counted=2, stock_at_floor_level="yes",
        confidence="low", reasoning="Two steps."))
    return TestClient(main.app)


# --- body size, counted as it arrives ---

def chunks(count: int, size: int):
    for _ in range(count):
        yield b" " * size


def test_a_chunked_body_with_no_content_length_is_cut_off_at_the_limit(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_BODY_BYTES", 1000)
    res = client.post("/api/point", content=chunks(100, 100), headers={"content-type": "application/json"})
    assert "content-length" not in res.request.headers
    assert res.status_code == 413 and res.json() == TOO_LARGE
    assert res.headers["content-security-policy"]


def test_a_chunked_body_within_the_limit_is_read_as_before(client):
    def body():
        yield b'{"lat": 3.0, '
        yield b'"lon": 101.5, "source": "pin"}'
    res = client.post("/api/point", content=body(), headers={"content-type": "application/json"})
    assert res.status_code != 413 and res.status_code != 422


# --- AI concurrency ---

def test_a_full_ai_pool_answers_busy_without_calling_gemini(client, monkeypatch):
    calls = []
    monkeypatch.setattr(ai, "ask", lambda *args: calls.append(args))
    monkeypatch.setattr(main, "_ai_slots", threading.BoundedSemaphore(1))
    monkeypatch.setattr(main, "AI_SLOT_WAIT_S", 0)
    main._ai_slots.acquire()
    res = client.post("/api/ask", json={"question": "hi"})
    assert res.status_code == 503 and BUSY in res.json()["error"] and not calls


def test_the_ai_slot_is_given_back_after_a_call_and_after_a_failure(client, monkeypatch):
    monkeypatch.setattr(main, "_ai_slots", threading.BoundedSemaphore(1))
    monkeypatch.setattr(main, "AI_SLOT_WAIT_S", 0)
    assert client.post("/api/ask", json={"question": "hi"}).status_code == 200

    def boom(*_):
        raise RuntimeError("upstream")
    monkeypatch.setattr(ai, "ask", boom)
    assert client.post("/api/ask", json={"question": "hi"}).status_code == 502
    monkeypatch.setattr(ai, "ask", lambda *args: "answer")
    assert client.post("/api/ask", json={"question": "hi"}).status_code == 200


def test_the_ai_pool_is_capped_by_a_named_constant():
    assert main.MAX_AI_CALLS == 8


@pytest.mark.parametrize("code, error", [(429, errors.ClientError), (503, errors.ServerError)])
def test_gemini_rate_limit_or_overload_answers_busy(client, monkeypatch, code, error):
    def limited(*_):
        raise error(code, {"error": {"message": "secret quota detail", "status": "RESOURCE_EXHAUSTED"}})
    monkeypatch.setattr(ai, "ask", limited)
    res = client.post("/api/ask", json={"question": "hi"})
    assert res.status_code == 503 and BUSY in res.json()["error"] and "secret" not in res.text


def test_other_gemini_errors_stay_a_502(client, monkeypatch):
    def refused(*_):
        raise errors.ClientError(400, {"error": {"message": "bad request", "status": "INVALID_ARGUMENT"}})
    monkeypatch.setattr(ai, "ask", refused)
    assert client.post("/api/ask", json={"question": "hi"}).status_code == 502


# --- the rate limiter's check and append are one step ---

class SlowDeque(deque):
    """Yields the thread inside the limiter's read of the count, so an unlocked check-then-append would let extra in."""
    def __len__(self):
        size = super().__len__()
        time.sleep(0.002)
        return size


def test_concurrent_requests_cannot_slip_past_the_limit(monkeypatch):
    monkeypatch.setattr(main, "_hits", defaultdict(SlowDeque))
    visitor = SimpleNamespace(headers={"x-forwarded-for": "203.0.113.9"}, client=None)
    allowed = []

    def hit():
        try:
            main._limit(visitor, "ai", 5)
            allowed.append(1)
        except HTTPException:
            pass

    threads = [threading.Thread(target=hit) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(allowed) == 5


# --- HEAD ---

@pytest.mark.parametrize("path", ["/api/status", "/api/data", "/api/areas", "/api/coverage"])
def test_head_is_answered_like_get_for_the_get_routes(client, path):
    head, get = client.head(path), client.get(path)
    assert head.status_code == get.status_code == 200
    assert head.headers["content-type"] == get.headers["content-type"]


def test_head_on_a_post_only_route_is_still_refused(client):
    assert client.head("/api/ask").status_code in (404, 405)


# --- photo types ---

@pytest.mark.parametrize("mime, raw", [("image/jpeg", JPEG), ("image/png", PNG), ("image/webp", WEBP)])
def test_photo_accepts_the_three_formats_by_their_first_bytes(client, mime, raw):
    res = client.post("/api/photo", json={"place": KNOWN_ID, "image": data_url(mime, raw)})
    assert res.status_code == 200


@pytest.mark.parametrize("mime, raw", [
    ("image/jpeg", b"0" * 64), ("image/jpeg", PNG), ("image/png", JPEG), ("image/webp", b"RIFF\x00\x00\x00\x00WAVE" + b"0" * 64),
])
def test_photo_refuses_bytes_that_are_not_the_type_it_claims_before_gemini(client, monkeypatch, mime, raw):
    calls = []
    monkeypatch.setattr(ai, "read_shop_photo", lambda *args: calls.append(args))
    res = client.post("/api/photo", json={"place": KNOWN_ID, "image": data_url(mime, raw)})
    assert res.status_code == 415 and "JPEG, PNG or WebP" in res.json()["error"] and not calls


def test_stock_photo_refuses_a_fake_image_before_gemini(client, monkeypatch):
    calls = []
    monkeypatch.setattr(ai, "read_stock_photo", lambda *args: calls.append(args))
    res = client.post("/api/stock", json={"place": KNOWN_ID, "image": data_url("image/png", b"0" * 64)})
    assert res.status_code == 415 and not calls


@pytest.mark.parametrize("path", ["/api/rain?area=sri-muda", "/api/place/node-13414432501"])
def test_head_is_not_answered_on_routes_that_bill_a_maps_call(client, path):
    assert client.head(path).status_code in (404, 405)
