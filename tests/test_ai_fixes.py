"""Gemini settings that keep answers whole: a pinned model, held-down thinking, retries, grounded news only, and
photo readings clamped instead of refused. No network: only HTTP is faked."""
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import ai
from test_place_ai import gemini_says, scripted_gemini

ROOT = Path(__file__).resolve().parents[1]
SHOP_FRONT = {"is_shop_front": True, "floor_height_cm": 30, "steps_counted": 2, "stock_at_floor_level": "no",
              "confidence": "medium", "reasoning": "Two steps up from the road."}
PLAN = {"title": "Pelan banjir", "summary": "Model menunjukkan air.", "before": ["Angkat stok."],
        "warning": ["Tutup kedai."], "during": ["Jauhi air."], "after": ["Bersihkan dengan selamat."]}


def model_without_override(**env) -> str:
    """ai.MODEL as a fresh process sees it, so the module under test here is not reloaded."""
    clean = {k: v for k, v in os.environ.items() if k != "GEMINI_MODEL"}
    out = subprocess.run([sys.executable, "-c", "from app import ai; print(ai.MODEL)"], cwd=ROOT,
                         env={**clean, **env}, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def test_the_model_is_a_fixed_stable_id_unless_overridden():
    assert model_without_override() == "gemini-3.8-flash"
    assert model_without_override(GEMINI_MODEL="gemini-3-flash-preview") == "gemini-3-flash-preview"


# --- thinking is held down on every request, so it cannot use up the answer's tokens ---

def every_request(monkeypatch) -> list[dict]:
    """One request from each of ask, flood_news, the photo readers and write_plan; returns the bodies sent."""
    def reply(n, body):
        schema = json.dumps(body.get("generationConfig", {}))
        if "is_shop_front" in schema:
            return gemini_says({"text": json.dumps(SHOP_FRONT)})
        if "warning" in schema:
            return gemini_says({"text": json.dumps(PLAN)})
        return gemini_says({"text": "Ok."})

    sent = scripted_gemini(monkeypatch, reply)
    ai.ask("Banjir tak?", None, [])
    ai.flood_news()
    ai.read_shop_photo(b"\xff\xd8\xff0000", "image/jpeg")
    ai.write_plan({"place": "Kedai"}, "en")
    return sent


def thinking(config: dict) -> dict:
    """The thinking settings as JSON carries them. The SDK sends this block with snake_case keys, which the API takes."""
    return {re.sub(r"_([a-z])", lambda m: m.group(1).upper(), key): value
            for key, value in json.loads(json.dumps(config["thinkingConfig"])).items()}


def test_gemini_2_5_gets_a_thinking_budget_on_every_request(monkeypatch):
    monkeypatch.setattr(ai, "MODEL", "gemini-2.5-flash")
    sent = every_request(monkeypatch)
    assert len(sent) == 4
    for body in sent:
        config = body["generationConfig"]
        assert thinking(config) == {"thinkingBudget": ai.THINKING_BUDGET} and "temperature" in config


def test_gemini_3_gets_a_low_thinking_level_and_its_default_temperature(monkeypatch):
    monkeypatch.setattr(ai, "MODEL", "gemini-3-flash-preview")
    sent = every_request(monkeypatch)
    assert len(sent) == 4
    for body in sent:
        config = body["generationConfig"]
        assert thinking(config) == {"thinkingLevel": "LOW"} and "temperature" not in config


def test_the_plan_has_room_for_a_whole_page(monkeypatch):
    sent = scripted_gemini(monkeypatch, lambda n, body: gemini_says({"text": json.dumps(PLAN)}))
    ai.write_plan({"place": "Kedai"}, "ms")
    assert sent[0]["generationConfig"]["maxOutputTokens"] == 4096


# --- busy or overloaded answers are tried again ---

@pytest.fixture
def fresh_client(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    ai._made_client.cache_clear()
    yield
    ai._made_client.cache_clear()


def test_two_first_questions_at_once_share_one_client(fresh_client, monkeypatch):
    # just after a restart two questions can ask for the client together; a second client, dropped at once, would
    # close its connection under its own request ("client has been closed", seen 6 Oct 2026)
    made = []

    def slow_client(**options):
        time.sleep(0.05)
        made.append(options)
        return SimpleNamespace(options=options)

    monkeypatch.setattr(ai.genai, "Client", slow_client)
    with ThreadPoolExecutor(4) as pool:
        clients = list(pool.map(lambda _: ai._client(), range(4)))
    assert len(made) == 1 and all(client is clients[0] for client in clients)


def test_the_client_retries_busy_and_overloaded_answers(fresh_client):
    options = ai._client()._api_client._http_options
    assert options.timeout == ai.TIMEOUT_MS
    assert options.retry_options.attempts == 3 and options.retry_options.http_status_codes == [429, 503]


# --- news without sources is not shown ---

def news_client(meta):
    response = SimpleNamespace(text="Banjir besar semalam di Shah Alam.", candidates=[SimpleNamespace(grounding_metadata=meta)])
    return SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kwargs: response))


@pytest.mark.parametrize("meta", [
    None,
    SimpleNamespace(grounding_chunks=None, search_entry_point=None),
    SimpleNamespace(grounding_chunks=[], search_entry_point=None),
    SimpleNamespace(grounding_chunks=[SimpleNamespace(web=None)], search_entry_point=None),
])
def test_an_answer_without_search_sources_reads_as_nothing_found(monkeypatch, meta):
    monkeypatch.setattr(ai, "_client", lambda: news_client(meta))
    out = ai.flood_news()
    assert out["answer"] == ai.NEWS_NOTHING_FOUND and out["sources"] == []


# --- a photo reading just past its limits is clamped, not refused ---

@pytest.mark.parametrize("floor, steps, want", [(320, 25, (300, 20)), (-5, -1, (0, 0)), (42.6, 3.2, (43, 3))])
def test_a_shop_front_reading_past_the_limits_is_clamped(floor, steps, want):
    estimate = ai.PhotoEstimate.model_validate({**SHOP_FRONT, "floor_height_cm": floor, "steps_counted": steps})
    assert (estimate.floor_height_cm, estimate.steps_counted) == want


def test_a_shop_front_reply_past_the_limits_still_arrives(monkeypatch):
    reply = {**SHOP_FRONT, "floor_height_cm": 320, "steps_counted": 22}
    scripted_gemini(monkeypatch, lambda n, body: gemini_says({"text": json.dumps(reply)}))
    estimate = ai.read_shop_photo(b"\xff\xd8\xff0000", "image/jpeg")
    assert (estimate.floor_height_cm, estimate.steps_counted) == (300, 20)


# --- a question has an overall deadline, so retries cannot run past the platform's request timeout ---

def test_the_tool_loop_stops_asking_once_the_deadline_has_passed(monkeypatch):
    clock = [0.0]
    sent = []

    def generate_content(**kwargs):
        sent.append(kwargs)
        clock[0] += 25   # each request takes 25 s
        call = SimpleNamespace(name="rain_forecast", args={}, id="1")
        return SimpleNamespace(function_calls=[call], text=None,
                               candidates=[SimpleNamespace(content=SimpleNamespace(role="model", parts=[]))])

    monkeypatch.setattr(ai, "_client", lambda: SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))
    monkeypatch.setattr(ai.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(ai, "_run_tool", lambda call: ai.types.Part(text="ok"))
    ai._ask_model([], "system")
    assert len(sent) == 3 < ai.MAX_MODEL_REQUESTS   # 0 s, 25 s, 50 s; at 75 s it is past ASK_DEADLINE_S
    assert ai.ASK_DEADLINE_S == 60 and ai.TIMEOUT_MS == 30_000
