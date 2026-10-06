"""Plan card G3: a spoken question. The page sends a short WAV; Gemini writes down what it heard; the words then go
through the same ask() as a typed question, with its tools and rules."""
import base64
import json
import logging

import pytest
from fastapi.testclient import TestClient

from app import ai, areas, chatguard, floodtools, main
from test_place_ai import gemini_says, scripted_gemini

KNOWN = areas.business("node-13414432501")[0]   # the checklist business, in the default city
WAV = "data:audio/wav;base64," + base64.b64encode(b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 52).decode()
HEARD = {"is_speech": True, "text": "Kedai ni kena air tak kalau banjir besar?", "language": "ms"}


# --- Gemini, with only HTTP faked ---

def test_the_recording_goes_to_gemini_as_audio_with_a_schema(monkeypatch):
    sent = scripted_gemini(monkeypatch, lambda n, body: gemini_says({"text": json.dumps(HEARD)}))
    heard = ai.transcribe(b"RIFF0000", "audio/wav")
    assert heard.text == HEARD["text"] and heard.language == "ms"
    parts = sent[0]["contents"][0]["parts"]
    assert parts[0]["inlineData"]["mime_type"] == "audio/wav" and "Write down" in parts[1]["text"]
    assert sent[0]["generationConfig"]["responseMimeType"] == "application/json"


# --- the endpoint ---

@pytest.fixture
def client(monkeypatch):
    main._hits.clear()
    asked = []
    monkeypatch.setattr(ai, "transcribe", lambda audio, mime: ai.Heard.model_validate(HEARD))
    monkeypatch.setattr(ai, "ask", lambda question, place, history, area, section=None: asked.append((question, place, history)) or "Dalam model, 1.88 m.")
    test_client = TestClient(main.app)
    test_client.asked = asked
    return test_client


def test_the_words_heard_are_asked_like_a_typed_question(client):
    history = [{"role": "user", "text": "hi"}, {"role": "model", "text": "Hai.", "sig": chatguard.sign("hi", "Hai.")}]
    res = client.post("/api/voice", json={"audio": WAV, "place": KNOWN["id"], "history": history})
    assert res.status_code == 200
    answer = "Dalam model, 1.88 m."
    assert res.json()["data"] == {"question": HEARD["text"], "language": "ms", "answer": answer, "sig": chatguard.sign(HEARD["text"], answer)}
    assert client.asked == [(HEARD["text"], KNOWN["id"], [{"role": "user", "text": "hi"}, {"role": "model", "text": "Hai."}])]


def test_a_recording_with_no_question_in_it_is_not_asked(client, monkeypatch):
    monkeypatch.setattr(ai, "transcribe", lambda audio, mime: ai.Heard(is_speech=False, text="", language="other"))
    res = client.post("/api/voice", json={"audio": WAV})
    assert res.status_code == 422 and "could not hear a question" in res.json()["error"]
    assert client.asked == []


@pytest.mark.parametrize("audio, status", [
    ("data:audio/webm;base64," + "A" * 40, 415),
    ("data:image/jpeg;base64," + "A" * 40, 415),
    ("data:audio/wav;base64," + "!" * 40, 400),
    ("data:audio/wav;base64," + base64.b64encode(b"0" * (main.MAX_AUDIO_BYTES + 1)).decode(), 413),
])
def test_recordings_that_cannot_be_used_are_refused_in_plain_words(client, audio, status):
    res = client.post("/api/voice", json={"audio": audio})
    assert res.status_code == status and res.json()["success"] is False and res.json()["error"]
    assert client.asked == []


def test_a_voice_question_counts_twice_against_the_ai_limit_and_takes_only_post(client, monkeypatch):
    monkeypatch.setattr(main, "RATE_LIMIT", 3)
    codes = [client.post("/api/voice", json={"audio": WAV}).status_code for _ in range(2)]
    assert codes == [200, 429]   # two Gemini calls each: the words, then the answer
    assert client.get("/api/voice").status_code == 405


def test_neither_the_recording_nor_the_words_are_logged(client, caplog):
    caplog.set_level(logging.DEBUG)
    client.post("/api/voice", json={"audio": WAV, "place": KNOWN["id"]})
    assert "Kedai ni kena air" not in caplog.text and "UklGR" not in caplog.text


def test_the_page_may_use_the_microphone_but_no_frame_may(client):
    policy = client.get("/").headers["permissions-policy"]
    assert "microphone=(self)" in policy and "camera=()" in policy and "geolocation=(self)" in policy


# --- review fixes ---

def test_audio_that_is_not_a_wav_file_inside_is_refused(client):
    fake = "data:audio/wav;base64," + base64.b64encode(b"OggS" + b"\x00" * 60).decode()
    res = client.post("/api/voice", json={"audio": fake})
    assert res.status_code == 415 and client.asked == []


def test_a_refused_recording_costs_one_slot_not_two(client, monkeypatch):
    monkeypatch.setattr(main, "RATE_LIMIT", 3)
    bad = "data:audio/webm;base64," + "A" * 40
    assert [client.post("/api/voice", json={"audio": bad}).status_code for _ in range(2)] == [415, 415]
    assert client.post("/api/voice", json={"audio": WAV}).status_code == 429   # 2 used, 1 left: a voice question needs 2


def test_a_long_transcript_is_cut_not_refused_and_a_bad_reply_never_logs_the_words(monkeypatch, caplog):
    assert ai.Heard(is_speech=True, text="kata " * 400, language="ms").text
    main._hits.clear()
    monkeypatch.setattr(ai, "transcribe", lambda audio, mime: ai.Heard.model_validate({"is_speech": "maybe", "text": "Kedai rahsia saya", "language": "ms"}))
    res = TestClient(main.app).post("/api/voice", json={"audio": WAV})
    assert res.status_code == 502 and "Kedai rahsia" not in caplog.text and "ValidationError" in caplog.text
