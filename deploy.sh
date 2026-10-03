#!/usr/bin/env bash
# Deploy to Cloud Run from this folder. Needs: the gcloud CLI, logged in (gcloud auth login), and a Google
# Cloud project with billing. Keys go in Secret Manager, never in the image or the repo.
#
#   PROJECT=my-project ./deploy.sh            first time: creates the two secrets, asks you to paste each key
#   PROJECT=my-project ./deploy.sh            later: redeploys with the stored secrets
set -euo pipefail

PROJECT=${PROJECT:?Set PROJECT to your Google Cloud project id}
REGION=${REGION:-asia-southeast1}
SERVICE=${SERVICE:-banjir-check}

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

echo "Deployed. Before sharing the link, set a billing budget alert and daily quotas (see README, Cloud Run)."
