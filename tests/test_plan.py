"""Plan card G2: a one-page flood plan in Bahasa Melayu or English. The facts are ours (app/plan.py), Gemini only
writes the steps from them, and the contacts are added by us, never by the model."""
import json

import pytest
from fastapi.testclient import TestClient

import tiff_fixture as fx
from app import ai, areas, floodtools, main, places, plan
from test_place_ai import gemini_says, scripted_gemini

SRI_MUDA = areas.default()
KNOWN = floodtools.premises()[0]   # Anetas: 1.35, 1.88 and 2.11 m
WRITTEN = {
    "title": "Pelan banjir kedai anda",
    "summary": "Dalam model, air boleh sampai 1.88 m di jalan dalam banjir sekali dalam 100 tahun.",
    "before": ["Simpan dokumen penting di rak atas.", "Ambil gambar stok untuk insurans."],
    "warning": ["Angkat stok ke tempat tinggi.", "Telefon 03-1234 5678 untuk bantuan."],
    "during": ["Tutup suis utama elektrik."],
    "after": ["Lihat https://example.com untuk tuntutan.", "Bersihkan dan keringkan kedai."],
}


# --- the facts: ours, from the data ---

def test_the_facts_of_a_business_hold_its_depths_chances_and_area():
    facts = plan.facts(places.resolve(KNOWN["id"]), SRI_MUDA)
    assert facts["place"] == "Anetas KARUPATI COFFEE RESTAURANT" and facts["area"] == SRI_MUDA.name
    assert [f["size"] for f in facts["floods"]] == ["1 in 10 years", "1 in 100 years", "1 in 500 years"]
    assert [f["street_depth_m"] for f in facts["floods"]] == [1.35, 1.88, 2.11]
    assert [f["chance_in_10_years_pct"] for f in facts["floods"]] == [65, 10, 2]
    assert facts["floor_height_cm"] == 0 and [f["water_above_floor_m"] for f in facts["floods"]] == [1.35, 1.88, 2.11]
    assert facts["estimate"] is None and facts["relief_centre"] is None


def test_a_floor_and_an_estimate_go_into_the_facts():
    found = floodtools.estimate_for(places.resolve(KNOWN["id"]), 50_000, floor_height_cm=40)
    facts = plan.facts(places.resolve(KNOWN["id"]), SRI_MUDA, floor_cm=40, estimate=found)
    assert [f["water_above_floor_m"] for f in facts["floods"]] == [0.95, 1.48, 1.71]
    assert facts["estimate"]["expected_yearly_loss_rm"] == found["expected_yearly_loss_rm"]
    assert facts["estimate"]["value_of_stock_and_equipment_rm"] == 50_000
    assert [f["loss_rm"] for f in facts["floods"]] == [found["per_flood"][rp]["total_rm"] for rp in ("10", "100", "500")]


def test_a_points_facts_name_no_place_and_hold_no_coordinates(tmp_path, monkeypatch):
    folder = fx.write_depth_set(tmp_path / "rasters")
    monkeypatch.setenv("BANJIR_RASTER_DIR", str(folder))
    point = places.point(6.4321, 101.1987)
    text = json.dumps(plan.facts(point, None))
    assert plan.facts(point, None)["place"] == floodtools.SELECTED_POINT
    assert "6.43" not in text and "101.1" not in text and "pt:" not in text and "6.37" not in text


def test_contacts_are_ours_and_name_the_areas_council():
    contacts = plan.contacts(SRI_MUDA)
    assert contacts[0] == {"name": "Emergency (police, fire, ambulance)", "how": "999"}
    assert any("publicinfobanjir.water.gov.my" in c["how"] for c in contacts)
    assert contacts[-1]["name"] == SRI_MUDA.council
    assert all(c["name"] != SRI_MUDA.council for c in plan.contacts(None))


def test_steps_with_a_phone_number_or_a_link_from_the_model_are_dropped():
    cleaned = plan.clean(ai.FloodPlan.model_validate(WRITTEN), plan.facts(places.resolve(KNOWN["id"]), SRI_MUDA), "ms")
    assert cleaned["warning"] == ["Angkat stok ke tempat tinggi."]
    assert cleaned["after"] == ["Bersihkan dan keringkan kedai."]
    assert cleaned["summary"].startswith("Dalam model, air boleh sampai 1.88 m")


# --- Gemini, with only HTTP faked ---

def test_the_plan_is_written_from_the_facts_as_data_in_the_language_asked(monkeypatch):
    sent = scripted_gemini(monkeypatch, lambda n, body: gemini_says({"text": json.dumps(WRITTEN)}))
    facts = plan.facts(places.resolve(KNOWN["id"]), SRI_MUDA)
    written = ai.write_plan(facts, "ms")
    assert written.title == WRITTEN["title"]
    body = sent[0]
    assert "Bahasa Melayu" in body["systemInstruction"]["parts"][0]["text"]
    assert json.dumps(facts, ensure_ascii=False) in body["contents"][0]["parts"][0]["text"]
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert "English" in ai.PLAN_LANGUAGES["en"]


# --- the endpoint ---

@pytest.fixture
def client(monkeypatch):
    main._hits.clear()
    seen = []
    monkeypatch.setattr(ai, "write_plan", lambda facts, language: seen.append((facts, language)) or ai.FloodPlan.model_validate(WRITTEN))
    test_client = TestClient(main.app)
    test_client.seen = seen
    return test_client


def test_the_endpoint_gives_the_plan_cleaned_with_our_facts_and_contacts(client):
    res = client.post("/api/plan", json={"place": KNOWN["id"], "language": "ms"})
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["language"] == "ms" and data["plan"]["warning"] == ["Angkat stok ke tempat tinggi."]
    assert data["facts"] == plan.facts(places.resolve(KNOWN["id"]), SRI_MUDA)
    assert data["contacts"] == plan.contacts(SRI_MUDA, "ms")
    assert client.seen[0][1] == "ms"


def test_the_owners_figures_put_an_estimate_in_the_facts(client):
    body = {"place": KNOWN["id"], "language": "en", "value_at_risk_rm": 50_000, "floor_height_cm": 40}
    facts = client.post("/api/plan", json=body).json()["data"]["facts"]
    assert facts["estimate"]["value_of_stock_and_equipment_rm"] == 50_000 and facts["floor_height_cm"] == 40


@pytest.mark.parametrize("body, status", [
    ({"place": KNOWN["id"], "language": "fr"}, 422),
    ({"place": KNOWN["id"]}, 422),
    ({"place": "node-1", "language": "en"}, 404),
    ({"place": KNOWN["id"], "language": "en", "raise_cm": 30}, 422),   # a measure needs its cost and a value
])
def test_bad_requests_are_refused_in_the_envelope(client, body, status):
    res = client.post("/api/plan", json=body)
    assert res.status_code == status and res.json()["success"] is False and res.json()["error"]


def test_plans_share_the_ai_bucket_and_take_only_post(client, monkeypatch):
    monkeypatch.setattr(main, "RATE_LIMIT", 1)
    body = {"place": KNOWN["id"], "language": "en"}
    assert [client.post("/api/plan", json=body).status_code for _ in range(2)] == [200, 429]
    assert client.get("/api/plan").status_code == 405


# --- review fixes: what the model may not add ---

FACTS = plan.facts(places.resolve(KNOWN["id"]), SRI_MUDA)


def written(**change) -> "ai.FloodPlan":
    return ai.FloodPlan.model_validate({**WRITTEN, **change})


@pytest.mark.parametrize("step", [
    "Call 03.1234.5678 now.", "Ring 1-300-88-1234 for help.", "See mdkkrai.gov.my for news.", "Report it at bomba.gov.my",
    "Message wa.me/60123456789", "Email help@example.com", "Check facebook.com/mbsa", "Visit www.jps.gov.my",
    "Your losses could reach RM 80,000.", "There is a 40% chance of a flood.", "Water rose 3.20 m in 2014.",
    "Your shop is safe from floods.", "Kedai ini tidak akan banjir.", "This street will flood every year.",
])
def test_a_step_with_a_contact_an_invented_figure_or_a_promise_is_dropped(step):
    assert plan.clean(written(before=[step, "Simpan dokumen."]), FACTS, "ms")["before"] == ["Simpan dokumen."]


@pytest.mark.parametrize("step", [
    "Raise stock above 1.88 m, the water in a 1 in 100 years flood.", "There is a 65% chance within 10 years.",
    "Keep 3 days of supplies.", "Call 999 if the water rises.", "Move stock 2 m up if you can.",
    "Floods of 10, 100 and 500 years are shown.", "Keep documents safe and dry.", "Clean up safely after.",
])
def test_steps_with_the_facts_numbers_and_plain_words_are_kept(step):
    assert plan.clean(written(before=[step]), FACTS, "en")["before"] == [step]


def test_the_title_is_checked_too_and_lists_are_capped():
    cleaned = plan.clean(written(title="Call 03-1234 5678", before=[f"Step {i}." for i in range(9)]), FACTS, "en")
    assert cleaned["title"] == "Flood plan" and len(cleaned["before"]) == 6
    assert plan.clean(written(title="Call 03-1234 5678"), FACTS, "ms")["title"] == "Pelan banjir"


def test_a_long_or_extra_plan_from_the_model_is_trimmed_not_refused():
    long = ai.FloodPlan.model_validate({**WRITTEN, "before": ["x" * 400] * 9, "during": []})
    cleaned = plan.clean(long, FACTS, "en")
    assert len(cleaned["before"]) == 6 and all(len(step) <= plan.MAX_STEP_CHARS for step in cleaned["before"])
    assert cleaned["during"] == []


@pytest.mark.parametrize("floor", [-500, 301, "NaN", 1e9])
def test_a_floor_out_of_range_is_refused_even_without_other_figures(client, floor):
    res = client.post("/api/plan", json={"place": KNOWN["id"], "language": "en", "floor_height_cm": floor})
    assert res.status_code == 422


def test_names_from_the_map_are_flagged_to_the_model_as_untrusted():
    assert "untrusted" in ai.PLAN_SYSTEM and "public map" in ai.PLAN_SYSTEM


def test_contacts_are_in_the_plans_language():
    ms = plan.contacts(SRI_MUDA, "ms")
    assert ms[0] == {"name": "Kecemasan (polis, bomba, ambulans)", "how": "999"} and "majlis tempatan" in ms[-1]["how"]
    assert plan.contacts(SRI_MUDA)[0]["name"].startswith("Emergency")
