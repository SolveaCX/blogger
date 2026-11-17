# Blogger

Shared blog service for product websites. The repo contains:

- `backend`: FastAPI + SQLAlchemy API backed by Postgres.
- `admin`: React + Tailwind + shadcn UI management UI.
- `cli`: TypeScript npm CLI for operators and AI tools.
- `skills/blogger-integration`: Codex skill for product-site integration.
- `skills/blogger-operator`: Codex skill for AI/operator usage through the CLI.
- `agents/api-change-sync-agent.md`: API contract sync checklist for backend/admin/CLI/skills changes.
- `deploy`: Google Cloud deployment scripts and Cloud Run descriptors.

## Local Development

Start Postgres:

```bash
docker compose up -d postgres
```

Run the API:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env
uvicorn app.main:app --reload --port 8000
```

Run the admin app:

```bash
cd admin
pnpm install
pnpm dev -- --host 0.0.0.0
```

The admin UI is initialized with the official shadcn CLI for Vite/Tailwind v4:

```bash
pnpm dlx shadcn@latest init -t vite -b radix -p vega --force --reinstall
```

Run the CLI from source:

```bash
cd cli
npm install
npm run build
node dist/index.js --help
```

The CLI behaves like a persistent client. The hosted Blogger API is the default
target, and the first login creates and saves a CLI AccessKey in
`~/.blogger/config.json` so later commands do not need repeated API/auth flags:

```bash
blogger login --email user@example.com --password '...'
blogger whoami
blogger sites list
blogger logout
```

Use `--api-url`, `BLOGGER_API_URL`, or `blogger config set --api-url ...` only
when targeting a different deployment. Use `BLOGGER_CONFIG_PATH` to store config
somewhere other than `~/.blogger/config.json`.

## Authentication

The admin app uses email/password login and receives a JWT. The CLI and product-site integration use an AccessKey.

The first registered user is automatically `super_admin`; later users default to `operator`.
Only super admins can create/update/delete sites and manage users. Operators can manage content on existing sites.

Supported AccessKey headers:

```http
X-Access-Key: blog_sk_...
```

or:

```http
Authorization: Bearer blog_sk_...
```

## Public Integration API

Product websites should use the skill in `skills/blogger-integration`. The stable read path is:

- `GET /api/integration/sites/{site_slug}/posts?language=en-US`
- `GET /api/integration/sites/{site_slug}/posts/{post_slug}?language=en-US`
- `GET /api/integration/sites/{site_slug}/categories`

For a preview that reads one site's published content, generate a random
`blog_ro_` key (32 random bytes encoded as unpadded URL-safe base64 after the
prefix). Set `PUBLISHED_INTEGRATION_SITE_SLUG` and
`PUBLISHED_INTEGRATION_KEY_SHA256` (the lowercase SHA-256 of the complete key)
on the Blogger API. Store the raw key only in the preview's server environment
and pass it in `X-Access-Key` on the three routes above. This key has no access
to drafts, other sites, or management endpoints.

These endpoints return published content only and require an AccessKey.

Post language uses the site's configured language key. Each site stores its own
`languages` list, for example `[{ "key": "en-US", "label": "English" }]`.
Create/update post calls always save drafts; use publish/unpublish endpoints or CLI commands to change status.

## Google Cloud

The deploy scripts assume:

- Cloud Run for `blogger-api` and `blogger-admin`.
- Cloud SQL Postgres for database storage.
- Secret Manager for `DATABASE_URL`, `SECRET_KEY`, and `ACCESS_KEY_PEPPER`.
- Cloud Storage for uploaded avatars and cover images.
- Public upload URLs are served through the API asset proxy by default.
- Artifact Registry for container images.
- Optional translation provider config for draft generation:
  - `TRANSLATION_API_BASE_URL`
  - `TRANSLATION_API_KEY`
  - `TRANSLATION_MODEL`

Deploy from an authenticated `gcloud` shell:

```bash
PROJECT_ID="$(gcloud config get-value project)" REGION=us-central1 ./deploy/bootstrap-gcp.sh
PROJECT_ID="$(gcloud config get-value project)" REGION=us-central1 ./deploy/deploy-cloud-run.sh
```
