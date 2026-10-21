#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
REPOSITORY="${REPOSITORY:-blogger}"
INSTANCE="${INSTANCE:-blogger-postgres}"
API_SERVICE="${API_SERVICE:-blogger-api}"
ADMIN_SERVICE="${ADMIN_SERVICE:-blogger-admin}"
ASSET_BUCKET="${ASSET_BUCKET:-${PROJECT_ID}-blogger-assets}"
TAG="${TAG:-$(date +%Y%m%d%H%M%S)}"

DATABASE_URL_SECRET="${DATABASE_URL_SECRET:-blogger-database-url}"
SECRET_KEY_SECRET="${SECRET_KEY_SECRET:-blogger-secret-key}"
ACCESS_KEY_PEPPER_SECRET="${ACCESS_KEY_PEPPER_SECRET:-blogger-access-key-pepper}"
TRANSLATION_API_KEY_SECRET="${TRANSLATION_API_KEY_SECRET:-blogger-translation-api-key}"
TRANSLATION_API_BASE_URL="${TRANSLATION_API_BASE_URL:-https://router.flatkey.ai}"
TRANSLATION_MODEL="${TRANSLATION_MODEL:-gpt-5.6-terra}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "PROJECT_ID is required" >&2
  exit 1
fi

gcloud config set project "${PROJECT_ID}" >/dev/null

API_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/${API_SERVICE}:${TAG}"
ADMIN_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/${ADMIN_SERVICE}:${TAG}"
CONNECTION_NAME="${PROJECT_ID}:${REGION}:${INSTANCE}"

submit_build() {
  local config="$1"
  local substitutions="$2"
  local build_id
  build_id="$(gcloud builds submit . \
    --config "${config}" \
    --substitutions "${substitutions}" \
    --async \
    --format='value(id)')"
  echo "Cloud Build started: ${build_id}" >&2
  while true; do
    local status
    status="$(gcloud builds describe "${build_id}" --format='value(status)')"
    case "${status}" in
      SUCCESS)
        echo "Cloud Build succeeded: ${build_id}" >&2
        return 0
        ;;
      FAILURE|INTERNAL_ERROR|TIMEOUT|CANCELLED|EXPIRED)
        echo "Cloud Build failed: ${build_id} status=${status}" >&2
        return 1
        ;;
      *)
        sleep 5
        ;;
    esac
  done
}

run_url() {
  local service="$1"
  gcloud run services describe "${service}" --region "${REGION}" --format=json | python3 -c 'import json,sys
obj=json.load(sys.stdin)
raw=obj.get("metadata", {}).get("annotations", {}).get("run.googleapis.com/urls", "[]")
urls=json.loads(raw)
print(urls[0] if urls else obj.get("status", {}).get("url", ""))'
}

submit_build deploy/cloudbuild-api.yaml "_IMAGE=${API_IMAGE}"

gcloud run deploy "${API_SERVICE}" \
  --image "${API_IMAGE}" \
  --region "${REGION}" \
  --allow-unauthenticated \
  --add-cloudsql-instances "${CONNECTION_NAME}" \
  --set-secrets "DATABASE_URL=${DATABASE_URL_SECRET}:latest,SECRET_KEY=${SECRET_KEY_SECRET}:latest,ACCESS_KEY_PEPPER=${ACCESS_KEY_PEPPER_SECRET}:latest,TRANSLATION_API_KEY=${TRANSLATION_API_KEY_SECRET}:latest" \
  --set-env-vars "^|^AUTO_CREATE_TABLES=true|ALLOWED_ORIGINS=http://localhost:5173,http://localhost:5174|GCS_BUCKET=${ASSET_BUCKET}|TRANSLATION_API_BASE_URL=${TRANSLATION_API_BASE_URL}|TRANSLATION_MODEL=${TRANSLATION_MODEL}" \
  --port 8080

API_URL="$(run_url "${API_SERVICE}")"

submit_build deploy/cloudbuild-admin.yaml "_IMAGE=${ADMIN_IMAGE},_VITE_API_URL=${API_URL}"

gcloud run deploy "${ADMIN_SERVICE}" \
  --image "${ADMIN_IMAGE}" \
  --region "${REGION}" \
  --allow-unauthenticated \
  --port 8080

ADMIN_URL="$(run_url "${ADMIN_SERVICE}")"

gcloud run services update "${API_SERVICE}" \
  --region "${REGION}" \
  --update-env-vars "^|^ALLOWED_ORIGINS=${ADMIN_URL},http://localhost:5173,http://localhost:5174|PUBLIC_ASSET_BASE_URL=${API_URL}/api/assets" >/dev/null

cat <<EOF
Deploy complete.
API_URL=${API_URL}
ADMIN_URL=${ADMIN_URL}
EOF
