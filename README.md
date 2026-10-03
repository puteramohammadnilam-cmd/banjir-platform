# Banjir Check: platform draft

First draft of the hackathon entry (AI Builder Cup 2026). Written fresh on 2 October 2026.

A shop owner around Taman Sri Muda, Shah Alam (Selangor) picks their business on a map, sees how deep the water gets in a 10, 100 and 500 year flood, and asks Gemini about it in Bahasa Melayu or English. A shop-front photo lets Gemini estimate the floor height. Google Weather shows the rain due in the next 12 hours, Google Maps says whether the shop is listed as open, and a news button asks Gemini to search Google for the latest flood news, with sources.

This is a test build. Depths come from a global model, not an official flood map.

## Run it

```bash
cd 11_Platform_Draft
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env        # then paste your Gemini key into .env
.venv/bin/uvicorn app.main:app --port 8080
```

Open http://localhost:8080. Get a free key at https://aistudio.google.com/apikey.

Without a key the map and cards still work. The chat and photo features say the AI is not connected.

For the rain forecast and the open or closed check, add `GOOGLE_MAPS_API_KEY` to `.env` too: a Google Maps
Platform key with the Weather API and Places API (New) enabled. Without it those two items are left out.

## Google services used

| Service | What it does here | Where |
|---|---|---|
| Gemini (AI Studio key or Vertex AI) | Answers in BM or English by calling six tools over the data: find a business, flood depth, area summary, ringgit estimate, rain, open or closed | `app/ai.py`, `app/floodtools.py` |
| Gemini, image input | Estimates floor height from a shop-front photo, as structured JSON | `app/ai.py` |
| Gemini grounded on Google Search | The "Latest flood news" button: an answer with its web sources and Google's search suggestions | `app/ai.py`, `app/main.py` |
| Google Weather API | Rain expected in the next 12 hours around Taman Sri Muda, as a banner and as a chat tool | `app/googlemaps.py` |
| Places API (New) | Whether Google Maps lists the selected shop as open, closed for now or closed for good | `app/googlemaps.py` |
| Cloud Run, Secret Manager | Hosting; the two keys are stored as secrets | `Dockerfile`, `deploy.sh` |
| Google Flood Hub | Linked for river flood forecasts. Its API is in a pilot with a waitlist | footer |

Terms followed: Google results are shown with Google attribution. Nothing from Google is cached: the Maps
Platform terms allow caching only coordinates and place ids, and the Gemini API terms forbid caching or framing
grounded results. Search suggestions are shown exactly as given, next to the answer.

Spend guards: the news question is fixed in code, so the endpoint cannot be used as a general search service; each
chat question may make at most 3 Google Maps lookups; Gemini calls are limited to 20 and Maps lookups to 60 per
visitor per 5 minutes; shops with no name on the map are never looked up. These limits are per server instance,
so before sharing the link also set, in Google Cloud: a billing budget with alerts, and daily quotas on the
Gemini key, the Weather API and Places API Text Search.

## Check it

```bash
.venv/bin/python -m pytest -q
```

## Where things are

| File | What it does |
|---|---|
| `app/ai.py` | The only file that talks to an AI model. Swap providers here. |
| `app/floodtools.py` | Data lookups. Gemini calls these as tools, so its numbers come from the data. |
| `app/googlemaps.py` | Google Weather and Places calls, server side only. |
| `app/costs.py` | The ringgit loss arithmetic. No AI, no I/O. See "How the cost estimate works". |
| `app/main.py` | Web server: page, data, `/api/ask`, `/api/photo`, limits and security headers. |
| `app/static/` | The page. Plain HTML, CSS and JavaScript, no build step. |
| `app/data/` | Built data: 204 businesses and 1,575 flood squares around Taman Sri Muda, Shah Alam. |
| `tools/build_data.py` | Rebuilds `app/data` from the raw files in `../05_Raw_Data_Sources`. To move the study area, change `VIEW` and the two input files. |

## How the cost estimate works

An owner asks the chat what a flood would cost them. Gemini passes what the owner said to
`damage_estimate`, which does the sums in `app/costs.py`. Gemini never does the arithmetic and never
supplies a ringgit value or a shop size of its own.

| Step | Sum | Method from | What is Malaysian |
|---|---|---|---|
| Water above the floor | modelled depth − floor height | this tool | Shah Alam depths; floor height from the owner or the photo |
| Direct damage, owner knows their value | value at risk × damage share(water above floor) | ASEAN Flood Risk Assessment and Mapping Guideline, ch. 6 | the ringgit value is the owner's own |
| Direct damage, owner does not | figure for a small shop, a medium shop or a large complex × 1.65 for prices × 0.8 | JPS / KTA Tenaga 2003, Rapid Assessment Method | RM12,000 / 24,000 / 160,000 from the study of the 2001 Klang Valley flood; 0.8 is the ratio in the guideline's worked examples (it gives 0.5 to 0.9) |
| Indirect loss, owner gives closure | daily takings × days closed | Fadel et al. 2018, Table 2 | the owner's own figures |
| Indirect loss, otherwise | 30% of direct damage | JPS / KTA Tenaga 2003, section 3.5.1 | the guideline's allowance for most areas (it gives 20% to 45%) |
| Average loss per year | area under loss against yearly chance, for the 1 in 10, 100 and 500 year floods | Fadel et al. 2018, eq. 7; JPS 2003 calls it average annual damage | — |
| Loss over 10 years | yearly loss discounted at 4% | Zuriyati Yusof et al. 2024 (JPS), eq. 2–3 | 4% is the rate used for flood mitigation cost-benefit studies in Malaysia |
| Is a measure worth it | direct damage avoided over 10 years ÷ cost of the measure > 1. Only from the owner's own value; a shop-size figure cannot price a measure. | Zuriyati Yusof et al. 2024 (JPS), eq. 1 | — |

JPS / KTA Tenaga 2003 is "Flood Damage Assessment of 26 April 2001 Flooding Affecting the Klang Valley and
the Generalised Procedures and Guidelines for Assessment of Flood Damages", Final Report Vol. 2, on the JPS
website. The 1.65 is the World Bank consumer price index for Malaysia, 2001 to 2025 (CC BY 4.0), saved in
`../05_Raw_Data_Sources/worldbank_cpi_malaysia.json`.

Still not Malaysian, or weak, and said so in every answer:

- With the owner's own value, the damage share is the Asia average for shops (Huizinga et al. 2017, JRC,
  Table 3-6). None of the documents we hold gives a Malaysian depth-damage curve as numbers. To replace it,
  change `CURVE_DEPTH_M` and `CURVE_SHARE` in `app/costs.py`.
- The shop-size figures are from a 2001 flood, do not change with depth, and are adjusted by general consumer
  prices only (the guideline does not state its price year; we took 2001). They are averages meant for
  counting many properties, so using one for a single shop is our own stretch. The guideline does not define
  small or medium; its large class is "Large (Complexes)". It calls the method a first approximation and
  says it is not a basis for cost-benefit analysis for funding.
- Raising stock is assumed to lift everything the owner counted as value at risk. Fittings that cannot be
  raised make the real saving smaller.
- Floods more frequent than 1 in 10 years are not in the depth data, so the yearly loss is a floor,
  not a ceiling, for shops that flood often.
- The 10 year horizon is our own choice.

## Swapping the AI or the host

- AI Studio key to Vertex AI: change `.env` only. See `.env.example`.
- Another model: set `GEMINI_MODEL`.
- Another provider: rewrite `ask()` and `read_shop_photo()` in `app/ai.py`. Nothing else changes.
- Cloud Run: `PROJECT=your-project-id ./deploy.sh` from this folder. It enables the APIs, stores both keys in
  Secret Manager (it asks you to paste them once), creates a service account that can read only those two
  secrets, and deploys with a 60 second request timeout. Needs the gcloud CLI and a project with billing.

## Data used

Only sources with clear terms, so the repo can be public.

- Flood depth: European Commission JRC global river flood hazard maps v2.1, CC BY 4.0.
- Businesses, roads, base map: OpenStreetMap contributors, ODbL.
- Shelters: none shown. The build reads `05_Raw_Data_Sources/shah_alam/pps.json` if it exists, so add a relief
  centre list there once we have one we can cite.
- Damage share by water depth: Huizinga, de Moel and Szewczyk (2017), Global flood depth-damage functions,
  European Commission JRC, Table 3-6. Nine published numbers, typed into `app/costs.py`.

Left out on purpose until their terms are read: JPS river levels, PLANMalaysia zoning, JKR federal roads.

Google Weather, Places and Search results are fetched live when someone uses the page and are not stored in the
repo.

## Licence

- Code: MIT, see `LICENSE`.
- Flood depths in `app/data/`: European Commission JRC global river flood hazard maps v2.1 (Baugh and others,
  2024), CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/), from
  https://developers.google.com/earth-engine/datasets/catalog/JRC_CEMS_GLOFAS_FloodHazard_v2_1. Our changes: read
  at each business and its nearest road (`premises.json`) and for the 90 m squares around Taman Sri Muda
  (`town.json`), rounded to the centimetre.
- `app/data/premises.json` is built from OpenStreetMap data, so the file is under the Open Database License 1.0
  (https://opendatacommons.org/licenses/odbl/1-0/). © OpenStreetMap contributors.
- `app/static/vendor/leaflet.js` and `leaflet.css`: Leaflet 1.9.4, BSD 2-Clause, see
  `app/static/vendor/LICENSE-leaflet.txt`.
- The published figures typed into `app/costs.py` are cited under "How the cost estimate works".

## Known limits of this draft

- The rate limit is in memory, per server instance. Fine for a demo, not for real traffic.
- The photo estimate is a guess from one image. It has not been tested against measured floors.
- No Bahasa Melayu version of the page text yet. Only the chat answers in BM.
- Nobody has checked the 204 businesses on the ground. Banks, clinics and fuel stations are left out.
- The study area was Kota Tinggi, Johor until 2 October 2026. A copy of that build is in
  `../11_Platform_Draft_kota_tinggi_2026-10-02.zip`.
- The cost estimate is reachable through the chat only. There is no form for it on the page yet, and the
  chat does not know the floor height from the photo unless the owner repeats it.
- The cost estimate has not been tried against a live Gemini key. The sums and the tool schema are tested.
- The Google Weather, Places and Search calls are tested against recorded response shapes, not live keys. Check
  them once the keys are in. Whether Google Weather covers Shah Alam and how well Places matches local shop
  names are unknown until then.
- The search suggestions are Google's HTML, put into the page inside a shadow root. The page's script policy stops
  any script in them. Checked with stand-in HTML only.
