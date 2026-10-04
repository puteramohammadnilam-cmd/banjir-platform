# Banjir Check

Banjir Check shows a small business how much river flood water a place could get in the model, and what that could roughly cost. It is an entry for the AI Builder Cup 2026.

You pick a business on the map, or check any point in Malaysia by dropping a pin or using GPS. You see the modelled water depth for a 1 in 10, 20 and 50 years flood; floods bigger than 1 in 50 years are not shown. A form turns that into a rough ringgit loss. An assistant powered by Gemini answers questions about it in Bahasa Melayu or English. It reads its numbers from the data through tools, and never does the sums itself.

What Gemini does here:
- **Chat with tools:** function calling over the flood data, the cost engine, Google Weather and Google Maps.
- **Voice:** ask out loud in Bahasa Melayu or English; Gemini writes down the question and the answer is read back.
- **Photos:** a shop-front photo gives the floor height; a photo of the stock inside gives a list of what would sit under the water, with rough values, to fill in the cost form.
- **A one-page flood plan** in Bahasa Melayu or English, written from this tool's own figures, ready to print.
- **Flood news** grounded on Google Search, with sources.

Honest wording matters here. Every depth is "in the model". This is a global river flood model at 90 m squares, not an official Malaysian flood map. It does not say a place is safe, and it does not say a place will flood.

## Quick start

You need Python 3.12 and the nine flood depth files (see "Flood depth rasters" below).

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env        # then add your keys, see below
.venv/bin/uvicorn app.main:app --port 8081
```

Open http://localhost:8081.

- Gemini key: get a free one at https://aistudio.google.com/apikey and put it in `.env` as `GOOGLE_API_KEY`. Without it the map and cards still work. The chat and photo features say the AI is not connected.
- Google Maps Platform key (optional): put it in `.env` as `GOOGLE_MAPS_API_KEY`. Enable the Weather API and Places API (New) on it. Without it the rain forecast and the open or closed check are left out.
- Without the flood depth files, the two built areas still work, because their depths are already in the repo. Checking any point does not: `/api/status` then says `points_ready: false`.

Try a point check from the command line:

```bash
curl -s -X POST localhost:8081/api/point -H 'content-type: application/json' \
  -d '{"lat":3.0297599,"lon":101.5364982,"source":"pin"}'
```

That is a spot in Taman Sri Muda. The answer names its square `pt:3.02998,101.53667` and gives 1.35, 1.54 and 1.76 m for the 1 in 10, 20 and 50 years floods.

## Areas

An area is a folder in `app/data/areas/{id}/`:

| File | What it holds |
|---|---|
| `area.json` | Name, map view and zoom, the words the AI prompt and the news question use, the council, notes on the data, and past floods if any were collected. Written by hand. |
| `premises.json` | Businesses mapped on OpenStreetMap, each with its modelled depths and nearest road. |
| `town.json` | The 90 m flood squares around them, and any relief centres. |

Five areas are built in:

| Area | Businesses | Wet at 1 in 50 (model) | Flood squares | Past floods in the sources checked |
|---|---|---|---|---|
| Taman Sri Muda, Shah Alam, Selangor (the default) | 204 | 183 | 1,514 | 10 |
| Kuantan town centre, Pahang | 300 | 191 | 1,085 | 5 (2012 to 2021) |
| Kota Bharu town centre, Kelantan | 491 | 100 | 618 | 3 (2014 to 2025) |
| Kuala Terengganu town centre, Terengganu | 158 | 85 | 588 | 5 (1999 to 2025) |
| Kota Tinggi town centre, Johor | 27, picked by hand | 19 | 382 | none collected; 2 relief centres |

Kuantan, Kota Bharu and Kuala Terengganu were picked on 3 Oct 2026 from a screen of eleven river towns (OpenStreetMap
business count and the share wet in the model) and built with `tools/build_area.py`. In all three the model gives
5 to 10 m at some businesses, where news reports of real floods give about 0.1 to 2 m; each area's notes say so on
the page and to the AI. Only Kota Tinggi has relief centres.

The page opens on the default area; `?area=kuantan` (or another id) opens another. A new area needs its own folder; the server checks every `area.json` when it starts, so a typo stops it at once.

Place names live only in `area.json`. The backend and the page scripts carry none, and a test guards that.

## Check any point

"Check any point in Malaysia" works anywhere the flood model files cover, not only in an area.

1. Move the map until the cross sits on your premises, or choose "Use my location". The page explains first, then the browser asks.
2. The page snaps the spot to the 90 m model square it falls in and sends the square's centre to `POST /api/point`. The server snaps it again.
3. A covered point gives its depths, a square outline, and the wet squares around it. The business, cost and chat tabs then work for the point.

The result is one 90 m square, not a building. Several shops can share a square, and the model knows no floor heights.

A point is named by its square, for example `pt:3.02998,101.53667`. A shared link keeps it after the `#`: `#place=pt:3.02998,101.53667`. A business uses `?place=node-…` in the query. Old `?shop=` links still work.

## Flood depth rasters

The depths come from nine JRC GeoTIFF files: three 10 x 10 degree grids, each with one file per return period (10, 20 and 50 years):

```
ID211_N10_E100_RP{10,20,50}_depth.tif     Peninsular Malaysia (except Langkawi), far west Sarawak
ID220_N10_E110_RP{10,20,50}_depth.tif     the rest of Sarawak, and Sabah
ID202_N10_E90_RP{10,20,50}_depth.tif      Langkawi
```

They are about 73 MB together, so they are not in git (`.gitignore` skips `app/data/rasters/*.tif`). Download them from the JRC portal (https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/CEMS-GLOFAS/flood_hazard/, folder `RP10`, `RP20` or `RP50`) into `app/data/rasters/`. The dataset is described at https://developers.google.com/earth-engine/datasets/catalog/JRC_CEMS_GLOFAS_FloodHazard_v2_1 (the link recorded in `SOURCES.txt`).

- `app/data/rasters/SOURCES.txt` is committed. It records the source, licence, size and SHA-256 of each file. `tests/test_rasters_shipped.py` checks your copies against it, and skips a file that is absent.
- `BANJIR_RASTER_DIR` points the app at another folder, for example one outside the repo.
- `deploy.sh` stops before it touches Google Cloud unless all nine files are there. It names each missing file and points to `SOURCES.txt` for the download links.
- `app/raster.py` reads them with the standard library only. It refuses any file layout other than the one JRC ships, rather than guessing.

What they cover: 89.977 to 119.975 E and 0.008 to 10.007 N, which holds all of Malaysia. The grids are rectangles, so they also take in Singapore, Brunei, southern Thailand, eastern Sumatra and part of Kalimantan. In this build the app uses coarse boxes, not national borders, so it answers for points there too. A point outside every box gets "outside".

Langkawi is covered, but the model has no flood water anywhere on the island (every square checked), so every point there reads "No water in the model".

The app works with any subset of the files: a region whose grid is missing gets a "not in this build yet" answer.

## Endpoints

Every answer is JSON in one envelope: `{success, data, error}`. Responses of 1 KB or more are gzip-compressed.

| Method and path | Returns |
|---|---|
| GET `/api/data` | The default area's `{area, premises, town, limits}` |
| GET `/api/areas` | `{default, areas:[{id, name, display_name, view, zoom, counts, has_history, has_shelters}]}` |
| GET `/api/areas/{id}/data` | `{area, premises, town, limits}` for one area. 404 for an unknown id. |
| GET `/api/status` | `{ai_ready, model, maps_ready, points_ready}` |
| GET `/api/coverage` | `{data_version, return_periods, block_cells, grids, regions}`: what the page needs to snap a point, and coarse boxes for Langkawi, the Peninsula and Borneo |
| POST `/api/point` | Body `{lat, lon, source: "pin" or "gps"}`. Returns `{coverage, region, place, blocks, cells}`. `coverage` is `covered`, `not_loaded` or `outside`. Only a covered point has a place (its depths, its square, its area if it lies in one), and the wet squares around it in `blocks` and `cells`. If a neighbouring flood tile cannot be read, `blocks` and `cells` are null but the place is still returned. |
| POST `/api/ask` | `{question, place, area_id, history}`. The chat answer. `place` is a business or point id (`business_id` is accepted as an older name). |
| POST `/api/photo` | `{place, image}`. Gemini reads floor height from a shop-front photo (JPEG, PNG or WebP, 4 MB at most). |
| POST `/api/stock` | `{place, image, floor_height_cm}`. Gemini lists the stock and equipment in a photo of the shop's inside, with rough value ranges; the server works out which of it sits under the modelled water in each flood size (`app/stock.py`) and suggests a value for the cost form. |
| POST `/api/plan` | `{place, language: "ms" or "en", …the owner's figures if any}`. A one-page flood plan: our facts (`app/plan.py`), Gemini's steps written from them (links and phone numbers it adds are dropped), and our contacts. |
| POST `/api/voice` | `{audio, place, area_id, history}`. A spoken question as 16 kHz mono WAV (30 s, 1 MB at most). Gemini writes down the words, which are then asked like a typed question. Returns `{question, language, answer}`. |
| POST `/api/estimate` | `{place, …the owner's figures}`. The ringgit estimate, no AI. |
| POST `/api/news` | `{area_id}`. Gemini grounded on Google Search: the latest flood news for the area, with sources. The question is fixed in code. |
| GET `/api/rain?area=` | Rain expected in the next 12 hours, from Google Weather, at the area's centre |
| GET `/api/place/{id}` | How Google Maps lists a mapped business. 404 for a point id. |

`/api/point`, `/api/ask`, `/api/photo`, `/api/stock`, `/api/plan`, `/api/voice`, `/api/estimate` and `/api/news` take only POST. A GET to them is a 405. Input that does not fit is a 422 with a plain message that does not repeat what was sent.

`/api/rain`, `/api/place/{id}` and `/api/point` send `Cache-Control: no-store`.

Rate limits, per visitor in each 5 minute window, counted in memory by each server instance:

| Limit | Applies to |
|---|---|
| 20 | `/api/ask`, `/api/photo`, `/api/stock`, `/api/plan`, `/api/news`: each one is a Gemini call. `/api/voice` counts twice (the words, then the answer). |
| 60 | `/api/rain` and `/api/place/{id}`: Google Maps lookups |
| 120 | `/api/estimate` |
| 120 | `/api/point` |
| 1200 | `/api/coverage` |

The data and status endpoints have no limit. One chat question may make at most 3 Google Maps lookups. A business with no name on the map is never looked up.

## What is sent where

These are the claims this app makes about your location, and what backs each one.

- Your point is sent only in the body of a POST. The page sends the centre of the 90 m square, not the exact pin or GPS fix. A POST body is not in a URL, so it is not in URL-based request logs.
- The server does not write a point to its logs. `tests/test_place_ai.py` runs a full point flow with log capture and checks that no point or coordinate appears.
- A point's square goes in the link only after the `#`. Browsers do not send that part to any server.
- `Referrer-Policy: strict-origin` means a request carries only this site's address as its referrer, not the full page link.
- `Permissions-Policy: geolocation=(self), microphone=(self)` lets this page, and no frame, ask for GPS and the microphone. The camera is off (photos come from the file picker, which can open the camera on a phone).
- Gemini gets the label "the selected point", the area's name, the modelled depths, and the nearest relief centre with its distance. It never gets coordinates or the square's id.
- Rain: for a point outside the listed areas, Google Weather gets the square's centre rounded to 0.01 degrees, about 1 km. Inside an area, it gets the area's centre.
- Google Places is asked only about mapped businesses, by OpenStreetMap name and coordinates. It is never asked about a point.
- The map tiles come from OpenStreetMap's servers, which see the map area you view. After a GPS fix the map opens at street level (zoom 17), where one tile is about 300 m wide.
- A photo you upload (of the shop front, or of the stock inside) is sent to Gemini to be read. This app does not save it. Google's Gemini API terms apply to it.
- A voice question is recorded only while the Speak button is on, sent to Gemini as audio to write down the words, and not saved or logged by this app (`tests/test_voice.py`). Answers to spoken questions are read aloud by your browser's own speech voice (some browsers use an online voice for this).
- The flood plan is written by Gemini from facts this app gives it: for a point you picked, the same as the chat gets, never coordinates.

## Coverage and limits

- Depths are river floods on land, from a global model at 90 m. The model does not show flash floods, blocked drains or the sea. "No water in the model" is not a promise that a place stays dry. It can be a hill, the sea, or a place the model does not flood.
- Points anywhere in Malaysia have depths. Langkawi has no flood water in the model. See "Flood depth rasters".
- Only the two built areas have mapped businesses. The counts are "businesses mapped on OpenStreetMap", not all businesses. Nobody has checked them on the ground. Banks, clinics and fuel stations are left out.
- Relief centres: Kota Tinggi's two were named in news reports and located on OpenStreetMap. They are not an official list. Taman Sri Muda has none.
- Floods more frequent than 1 in 10 years, and bigger than 1 in 50 years, are not in the data. The JRC set has bigger ones (1 in 75 years and up); the app shows 1 in 10, 20 and 50 only, and says bigger floods are not shown.
- Past floods are collected only for Taman Sri Muda.

## Google services used

| Service | What it does here | Where |
|---|---|---|
| Gemini (AI Studio key or Vertex AI) | Answers in BM or English by calling six tools over the data: find a business, flood depth, area summary, ringgit estimate, rain, open or closed | `app/ai.py`, `app/floodtools.py` |
| Gemini, image input | Estimates floor height from a shop-front photo, as structured JSON | `app/ai.py` |
| Gemini grounded on Google Search | The "Latest flood news" button: an answer with its web sources and Google's search suggestions | `app/ai.py`, `app/main.py` |
| Google Weather API | Rain expected in the next 12 hours, as a banner and as a chat tool | `app/googlemaps.py` |
| Places API (New) | Whether Google Maps lists the selected shop as open, closed for now or closed for good | `app/googlemaps.py` |
| Cloud Run, Secret Manager | Hosting; the two keys are stored as secrets | `Dockerfile`, `deploy.sh` |
| Google Flood Hub | Linked for river flood forecasts. Its API is in a pilot with a waitlist | footer |

Terms followed: Google results are shown with Google attribution. Nothing from Google is cached: the Maps Platform terms allow caching only coordinates and place ids, and the Gemini API terms forbid caching or framing grounded results. Search suggestions are shown exactly as given, next to the answer. Coordinates from Google are never used to look up a depth: points come only from a pin, GPS or OpenStreetMap.

## Where things are

| File | What it does |
|---|---|
| `app/ai.py` | The only file that talks to an AI model. Swap providers here. |
| `app/floodtools.py` | Data lookups. Gemini calls these as tools, so its numbers come from the data. |
| `app/raster.py` | Reads the JRC files with the standard library only, and returns the depth at a point. |
| `app/areas.py` | Loads the curated areas from `app/data/areas`. |
| `app/places.py` | A place is a business or a point, with one id string. Snaps a point to its square, checks coverage, finds the squares around it. |
| `app/googlemaps.py` | Google Weather and Places calls, server side only. |
| `app/costs.py` | The ringgit loss arithmetic. No AI, no I/O. See "How the cost estimate works". |
| `app/main.py` | Web server: page, data, endpoints, limits, compression and security headers. |
| `app/static/` | The page, in four tabs: area overview, my business, flood cost, ask AI. Plain HTML, CSS and JavaScript, no build step. `place.js` holds ids, the link and snapping; `pin.js` the aim mode and GPS. |
| `app/data/areas/` | Built data for each area. |
| `app/data/rasters/` | The JRC files (not in git) and `SOURCES.txt`. |
| `tools/build_area.py` | Builds an area's `premises.json` and `town.json` from raw OpenStreetMap answers (Overpass) and the JRC rasters, with `--area --view --pois --roads`. It rebuilds Taman Sri Muda, Kuantan, Kota Bharu and Kuala Terengganu byte for byte. The built data is committed, so you do not need to run it. |
| `tools/resample_area.py` | Re-samples an area built on the old flood sizes (1 in 10, 100, 500) at 1 in 10, 20 and 50 when its OpenStreetMap inputs were not kept (Kota Tinggi): depths read again at each business and square; each road's square found from its stored old depths and distance, and refused if that is ambiguous. Needs the old JRC files. |
| `deploy.sh` | Cloud Run deploy with a post-deploy smoke test. |

## How the cost estimate works

An owner asks the chat what a flood would cost them. Gemini passes what the owner said to `damage_estimate`, which does the sums in `app/costs.py`. Gemini never does the arithmetic and never supplies a ringgit value or a shop size of its own. The Flood cost tab has a form that runs the same sums.

| Step | Sum | Method from | What is Malaysian |
|---|---|---|---|
| Water above the floor | modelled depth − floor height | this tool | Modelled depths; floor height from the owner or the photo |
| Direct damage, owner knows their value | value at risk × damage share(water above floor) | ASEAN Flood Risk Assessment and Mapping Guideline, ch. 6 | the ringgit value is the owner's own |
| Direct damage, owner does not | figure for a small shop, a medium shop or a large complex × 1.65 for prices × 0.8 | JPS / KTA Tenaga 2003, Rapid Assessment Method | RM12,000 / 24,000 / 160,000 from the study of the 2001 Klang Valley flood; 0.8 is the ratio in the guideline's worked examples (it gives 0.5 to 0.9) |
| Indirect loss, owner gives closure | daily takings × days closed | Fadel et al. 2018, Table 2 | the owner's own figures |
| Indirect loss, otherwise | 30% of direct damage | JPS / KTA Tenaga 2003, section 3.5.1 | the guideline's allowance for most areas (it gives 20% to 45%) |
| Average loss per year | area under loss against yearly chance, for the 1 in 10, 20 and 50 years floods, with rarer floods counted at the 1 in 50 loss: 0.035 × L50 + 0.04 × L20 + 0.025 × L10 | Fadel et al. 2018, eq. 7; JPS 2003 calls it average annual damage | — |
| Loss over 10 years | yearly loss discounted at 4% | Zuriyati Yusof et al. 2024 (JPS), eq. 2–3 | 4% is the rate used for flood mitigation cost-benefit studies in Malaysia |
| Is a measure worth it | direct damage avoided over 10 years ÷ cost of the measure > 1. Only from the owner's own value; a shop-size figure cannot price a measure. | Zuriyati Yusof et al. 2024 (JPS), eq. 1 | — |

JPS / KTA Tenaga 2003 is "Flood Damage Assessment of 26 April 2001 Flooding Affecting the Klang Valley and the Generalised Procedures and Guidelines for Assessment of Flood Damages", Final Report Vol. 2, on the JPS website. The 1.65 is the World Bank consumer price index for Malaysia, 2001 to 2025 (CC BY 4.0).

Still not Malaysian, or weak, and said so in every answer:

- With the owner's own value, the damage share is the Asia average for shops (Huizinga et al. 2017, JRC, Table 3-6). None of the documents we hold gives a Malaysian depth-damage curve as numbers. To replace it, change `CURVE_DEPTH_M` and `CURVE_SHARE` in `app/costs.py`.
- The shop-size figures are from a 2001 flood, do not change with depth, and are adjusted by general consumer prices only (the guideline does not state its price year; we took 2001). They are averages meant for counting many properties, so using one for a single shop is our own stretch. The guideline does not define small or medium; its large class is "Large (Complexes)". It calls the method a first approximation and says it is not a basis for cost-benefit analysis for funding.
- Raising stock is assumed to lift everything the owner counted as value at risk. Fittings that cannot be raised make the real saving smaller.
- The yearly loss is a floor at both ends: floods more frequent than 1 in 10 years are not in the depth data, so shops that flood often lose more, and floods bigger than 1 in 50 years are counted as if they cost the same as the 1 in 50.
- The 10 year horizon is our own choice.

## Tests

```bash
.venv/bin/python -m pytest -q
node --test tests/*.test.mjs        # Node 22.7+ or 20.19+, no packages
.venv/bin/python -m pytest -q tests/test_raster.py -k parity -rs    # must say PASSED, not skipped
.venv/bin/python -m pytest -q --cov=app --cov-report=term-missing   # coverage (pytest-cov, in requirements-dev.txt)
node --test --experimental-test-coverage tests/*.test.mjs
```

Coverage on 3 October 2026: Python 98% of `app/` lines, JavaScript 94% of lines.

- Tests that need the real JRC files skip when the files are absent. The parity test checks every built business and flood square against a fresh read of the rasters, so run it with the files in place.
- `tests/test_rules.py` guards file size (800 lines), function size (50 lines), `innerHTML`, `console.log` and area place names in code.
- `tests/test_deploy.py` runs `deploy.sh` against a stub `gcloud` and a stub `curl`. It never touches the network.

## Deploy

Cloud Run, from this folder. You need the gcloud CLI, logged in, and a Google Cloud project with billing.

```bash
PROJECT=your-project-id ./deploy.sh
```

It does these things, in order:

1. Stops if any of the nine flood files is missing, before it touches Google Cloud.
2. Enables the APIs and stores both keys in Secret Manager. It asks you to paste each key once.
3. Creates a service account that can read only those two secrets. A new account can take a few seconds to show up in IAM, so it retries the secret access grant up to 5 times, 5 seconds apart.
4. Deploys the service `banjir-check` in `asia-southeast1` (override with `SERVICE` and `REGION`), with 2 instances at most, 512 MiB, a 60 second request timeout and startup CPU boost. It passes `--quiet`, so a first run does not stop to ask questions (for example about creating the Artifact Registry repository).
5. Reads the service URL and runs a smoke test: `/api/status` and `/api/coverage` must answer with success, and a point check at the Taman Sri Muda spot above must come back `covered` in square `pt:3.02998,101.53667`. If a check fails, it says which one and exits non-zero.

The smoke test has been run against stubs only.

An optional custom domain: `PROJECT=your-project-id DOMAIN=banjir.example.org ./deploy.sh` also creates a Cloud Run domain mapping and prints the DNS records to add. It skips creating one that already exists. Check before you rely on it:

- Domain mappings are a Preview feature. Google's page "Mapping custom domains" listed `asia-southeast1` among the regions that have them when it was read on 3 October 2026. The same page calls the feature not production-ready because of latency, and points to a load balancer or Firebase Hosting instead.
- Google must have verified that you own the domain first.

Before you share the link, set up cost guards in Google Cloud: a billing budget with alerts, and daily quotas on the Gemini key, the Weather API and Places API Text Search. The rate limits above are per server instance and reset when it restarts, so they are not a substitute.

Memory: the service is set to 512 MiB. The raster reader keeps at most 48 decoded tiles, about 13 MB. Measure the real use after the first deploy.

Swapping parts:

- AI Studio key to Vertex AI: change `.env` only. See `.env.example`.
- Another model: set `GEMINI_MODEL`.
- Another provider: rewrite `ask()` and `read_shop_photo()` in `app/ai.py`. Nothing else changes.

## Data used and licences

Only sources with clear terms, so the repo can be public.

- Code: MIT, see `LICENSE`.
- Flood depth: European Commission JRC global river flood hazard maps v2.1 (Baugh and others, 2024), CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/), from https://developers.google.com/earth-engine/datasets/catalog/JRC_CEMS_GLOFAS_FloodHazard_v2_1. The nine files in `app/data/rasters/` are used unchanged. Our changes in `app/data/areas/`: depths read at each business and its nearest road (`premises.json`) and for the 90 m squares of each area (`town.json`), rounded to the centimetre.
- Businesses, roads, base map: OpenStreetMap contributors, ODbL (https://opendatacommons.org/licenses/odbl/1-0/). Every `app/data/areas/*/premises.json` is built from OpenStreetMap data, so those files are under the Open Database License 1.0. © OpenStreetMap contributors.
- Kota Tinggi's relief centres were named in news reports and located on OpenStreetMap. They are not an official list.
- Past floods at Taman Sri Muda: ten reports from the news, DOSM and one journal paper (Rosmadi and others 2025, quoting MBSA's flood report for 2022), paraphrased with their sources in `app/data/areas/sri-muda/area.json` and on the page.
- Damage share by water depth: Huizinga, de Moel and Szewczyk (2017), Global flood depth-damage functions, European Commission JRC, Table 3-6. Nine published numbers, typed into `app/costs.py`.
- Consumer price index for Malaysia: World Bank, CC BY 4.0. It gives one factor, 1.65, in `app/costs.py`.
- `app/static/vendor/leaflet.js` and `leaflet.css`: Leaflet 1.9.4, BSD 2-Clause, see `app/static/vendor/LICENSE-leaflet.txt`.
- Google Weather, Places, Search and Gemini results are fetched live when someone uses the page. They are not stored in the repo and fall under Google's terms.

Left out on purpose until their terms are read: JPS river levels, PLANMalaysia zoning, JKR federal roads.

## Known limits of this draft

- The rate limit is in memory, per server instance. Fine for a demo, not for real traffic.
- The photo estimate is a guess from one image. It has not been tested against measured floors.
- The page text has a BM | EN switch. The area data (place names, flood-plan facts), server messages and OpenStreetMap business types are still English. The chat answers in BM or English.
- The Google Weather, Places and Search calls are tested against recorded response shapes, not live keys. Whether Google Weather covers a given place, and how well Places matches local shop names, is unknown until you try with keys.
- The cost estimate has not been tried through the chat with a live Gemini key. The sums, the form's endpoint and the tool schema are tested. The chat does not know the floor height from the photo unless the owner repeats it.
- The counter (0.9 m), adult (1.65 m), door (2.1 m) and storey (3 m) heights are typical values used to picture a depth, not measurements at any shop.
- The search suggestions are Google's HTML, put into the page inside a shadow root. The page's script policy stops any script in them. Checked with stand-in HTML only.
- The map tiles are OpenStreetMap's public servers, which is fine for a demo but not for heavy traffic.
