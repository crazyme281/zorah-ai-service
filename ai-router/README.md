# Lite

```
backend/     Python AI router — provider routing, emotion/persona
             engine, tiers, payments, safety, RAG, education
             verification. Two entrypoints: main.py (CLI, local
             testing) and api.py (FastAPI, what Render actually runs).
frontend/    Ionic React app — sidebar (chats + projects), chat window,
             auth. Runs as a web app or as an iOS/Android app via
             Capacitor.
supabase/    Migrations for the shared Postgres schema.
render.yaml  Render blueprint for backend/ — see "Deploying" below.
```

Each of `backend/` and `frontend/` is self-contained with its own
dependency manifest. They connect over HTTP (`frontend/src/lib/aiBackend.ts`
calls `backend/api.py`'s `/chat` endpoint) and share the Supabase project
for chat/project/message data.

## Getting started locally

**Backend:**
```
cd backend
pip install -r requirements.txt
cp .env.example .env   # fill in your provider API keys
python main.py         # CLI, for quick testing
# or:
uvicorn api:app --reload   # HTTP API, what the frontend actually calls
```

**Frontend:**
```
cd frontend
npm install
npm run dev
```

**Database:** already applied to your live Supabase project. The SQL
in `supabase/migrations/` is there for version control / to reproduce
on a different project.

## Deploying the backend to Render

Render deploys from a git repo it can clone — there's nothing to
deploy until this project is pushed somewhere Render can reach
(GitHub/GitLab/Bitbucket, public or with Render's GitHub App installed
for private repos).

Once it's pushed:

**Option A — Blueprint (uses `render.yaml`, recommended):**
In the Render dashboard: New → Blueprint → point it at the repo. It
reads `render.yaml` at the repo root and creates the service with the
right build/start commands and health check already configured. You'll
be prompted to fill in the provider API keys (`sync: false` in the
blueprint means Render asks rather than expecting them committed).

**Option B — I create it directly** via the Render connector, given the
repo URL — same result, just skips the dashboard. Either way, `ALLOWED_ORIGINS`
should get tightened from `*` to the frontend's real deployed URL once
that exists, and `VITE_AI_BACKEND_URL` in `frontend/.env` should point
at the resulting `https://<name>.onrender.com` URL.

Note: the emotion/tier state in `api.py` currently lives in process
memory. Fine on Render's free/starter plan (one instance), but if you
scale to multiple instances later, that state needs to move to a real
store (Postgres/Redis) or it'll vary depending which instance handles
a given request.
