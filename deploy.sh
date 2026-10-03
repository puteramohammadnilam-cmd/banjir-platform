#!/usr/bin/env bash
# Deploy to Cloud Run from this folder. Needs: the gcloud CLI, logged in (gcloud auth login), curl, and a Google
# Cloud project with billing. Keys go in Secret Manager, never in the image or the repo.
#
#   PROJECT=my-project ./deploy.sh            first time: creates the two secrets, asks you to paste each key
#   PROJECT=my-project ./deploy.sh            later: redeploys with the stored secrets
#   PROJECT=my-project DOMAIN=banjir.example.org ./deploy.sh     also maps your own domain (see map_domain below)
#
# After the deploy it reads the service URL and calls the live service three times (a smoke test): /api/status,
# /api/coverage and a point check at a known square. If one fails it says which and exits non-zero.
# tests/test_deploy.py runs this script against a stub gcloud and a stub curl.
set -euo pipefail

PROJECT=${PROJECT:?Set PROJECT to your Google Cloud project id}
REGION=${REGION:-asia-southeast1}
SERVICE=${SERVICE:-banjir-check}
DOMAIN=${DOMAIN:-}   # optional: a domain you own, to map to the service

# The flood depth rasters are not in git (about 77 MB), but the service needs them. Stop here, before anything in
# Google Cloud is touched, if one of the three return periods is missing.
for pattern in \
  'app/data/rasters/*_RP10_depth.tif' \
  'app/data/rasters/*_RP100_depth.tif' \
  'app/data/rasters/*_RP500_depth.tif'; do
  if ! compgen -G "$pattern" >/dev/null; then
    echo "Missing flood depth raster: $pattern" >&2
    echo "Put the three JRC files in app/data/rasters/ first. Where to get them: app/data/rasters/SOURCES.txt." >&2
    echo "If you hold the project's raw data folder, copy them from there:" >&2
    echo "  cp ../05_Raw_Data_Sources/jrc_glofas_v2_1/ID211_N10_E100_RP*_depth.tif app/data/rasters/" >&2
    exit 1
  fi
done

# --- smoke test ---
# A point in Taman Sri Muda. Its 90 m square has the id pt:3.02998,101.53667 (SCALE_UP_PLAN section 6A).
SMOKE_POINT='{"lat":3.0297599,"lon":101.5364982,"source":"pin"}'
SMOKE_POINT_ID='pt:3.02998,101.53667'

# fetch PATH [JSON]: the response body (a POST when JSON is given), or nothing when the request failed.
fetch() {
  local path=$1 json=${2:-}
  if [ -n "$json" ]; then
    curl -fsS --max-time 30 -X POST -H 'content-type: application/json' -d "$json" "$URL$path" 2>/dev/null || true
  else
    curl -fsS --max-time 30 "$URL$path" 2>/dev/null || true
  fi
}

# check LABEL BODY NEEDLE...: passes when BODY holds every NEEDLE. It never prints BODY, which could be large.
check() {
  local label=$1 body=$2 needle
  shift 2
  for needle in "$@"; do
    if [[ $body != *"$needle"* ]]; then
      echo "Smoke test FAILED: $label (no $needle in the answer)" >&2
      return 1
    fi
  done
  echo "  ok: $label"
}

# Runs all three checks, so one run names every failure.
smoke_test() {
  local failed=0
  check "GET /api/status" "$(fetch /api/status)" '"success":true' || failed=1
  check "GET /api/coverage" "$(fetch /api/coverage)" '"success":true' || failed=1
  check "POST /api/point" "$(fetch /api/point "$SMOKE_POINT")" '"coverage":"covered"' "$SMOKE_POINT_ID" || failed=1
  return "$failed"
}

# --- custom domain (optional) ---
# Cloud Run domain mappings are a Preview feature. Google's page "Mapping custom domains" listed asia-southeast1
# among the regions that have them when it was read on 3 October 2026, but calls the feature not production-ready
# (latency issues) and points to a load balancer or Firebase Hosting instead. Check that page before relying on it.
# Google must also have verified that you own the domain (Search Console, once per project), or create is refused.
map_domain() {
  if gcloud beta run domain-mappings describe --domain "$DOMAIN" --region "$REGION" >/dev/null 2>&1; then
    echo "$DOMAIN already has a domain mapping; not creating it again."
  elif ! gcloud beta run domain-mappings create --service "$SERVICE" --domain "$DOMAIN" --region "$REGION"; then
    echo "Could not map $DOMAIN. Check that you verified it with Google and that domain mappings exist in $REGION." >&2
    return 1
  fi
  echo "Add these DNS records where $DOMAIN is registered (the mapping may take a while to start working):"
  gcloud beta run domain-mappings describe --domain "$DOMAIN" --region "$REGION" --format='yaml(status.resourceRecords)'
}

# --- deploy ---
gcloud config set project "$PROJECT"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com weather.googleapis.com places.googleapis.com

for secret in gemini-api-key maps-api-key; do
  if ! gcloud secrets describe "$secret" >/dev/null 2>&1; then
    read -rsp "Paste the value for $secret (input hidden): " value && echo
    printf '%s' "$value" | gcloud secrets create "$secret" --data-file=-
  fi
done

# The service runs as its own account that can read the two secrets and nothing else (the default compute
# account often holds project Editor).
RUNNER="${SERVICE}-run@${PROJECT}.iam.gserviceaccount.com"
gcloud iam service-accounts describe "$RUNNER" >/dev/null 2>&1 \
  || gcloud iam service-accounts create "${SERVICE}-run" --display-name="Banjir Check on Cloud Run"
for secret in gemini-api-key maps-api-key; do
  gcloud secrets add-iam-policy-binding "$secret" --quiet \
    --member="serviceAccount:${RUNNER}" --role=roles/secretmanager.secretAccessor >/dev/null
done

gcloud run deploy "$SERVICE" --source . --region "$REGION" --allow-unauthenticated \
  --service-account "$RUNNER" \
  --set-secrets GOOGLE_API_KEY=gemini-api-key:latest,GOOGLE_MAPS_API_KEY=maps-api-key:latest \
  --max-instances 2 --memory 512Mi --timeout 60

URL=$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')
URL=${URL%/}
if [ -z "$URL" ]; then
  echo "Deployed, but the service URL could not be read, so the smoke test did not run." >&2
  exit 1
fi
echo "Deployed to $URL. Smoke test:"
if ! smoke_test; then
  echo "The service is deployed at $URL but failed the smoke test above. Look at its logs before sharing it." >&2
  exit 1
fi

if [ -n "$DOMAIN" ]; then
  map_domain
fi

echo "Deployed and checked. Before sharing the link, set a billing budget alert and daily quotas (see README, Deploy)."
