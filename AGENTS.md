# AGENTS.md

This document explains the project architecture and operational workflow for coding agents (and humans) working in this repository.

## What this project is

**openports** is a small system to **track ComfyUI and Ollama instances** and surface useful metadata in a dashboard.

- **ComfyUI** default port: `8188`
- **Ollama** default port: `11434`

It is designed as:
- a **backend** that discovers/imports candidate hosts, verifies them via their HTTP APIs, and stores results
- a **frontend** (React) dashboard to view instances, models, and scan history
- optional **Telegram notifications** for newly discovered live instances

## Important operational note

Discovery of targets can come from:
- a third-party index (e.g. Shodan/Censys) **if you have API access**, or
- a manual import of IPs/hosts you are authorized to probe

The backend always performs **verification/fingerprinting** itself before storing/alerting.

## Repo layout

- `backend/`
  - FastAPI application (`backend/app/*`)
  - SQLite storage (by default) stored under `./data/`
  - fingerprinting logic for ComfyUI and Ollama
  - endpoints used by the dashboard
  - helper tools under `backend/tools/` (for debugging and enrichment)

- `frontend/`
  - Vite + React dashboard
  - calls backend endpoints under `/api/*`

- `legacy/`
  - older prototype scripts kept for reference

- `deploy/`
  - nginx reverse proxy config for docker deployment

## Current architecture (high level)

### 1) Discovery

The current codebase includes Shodan discovery scaffolding:
- `backend/app/shodan_client.py`
- `backend/app/scanner.py: run_shodan_scan()`

If Shodan Search API is not available (403), use manual import tooling or add another provider.

### 2) Verification / Fingerprinting

Verification is **HTTP-based** and best-effort. Core functions:
- `backend/app/fingerprints.py`
  - `verify_comfyui(base_url, client)`
    - `GET /system_stats` (GPU/system info; version may be nested under `system.comfyui_version`)
    - `GET /models` and `GET /models/<type>` (models by folder)
    - fallback `GET /` contains “comfy”
  - `verify_ollama(base_url, client)`
    - `GET /api/version`
    - `GET /api/tags`
    - `POST /api/show` for each model (limited by `OLLAMA_SHOW_LIMIT`)

Notes:
- ComfyUI often exposes GPU info via `/system_stats`.
- Ollama generally does **not** expose GPU hardware info via the public HTTP API.

### 3) Storage

- SQLModel models live in `backend/app/models.py`
  - `Instance` stores:
    - `service` (`comfyui|ollama`), `ip`, `port`
    - timestamps + `is_alive`
    - `service_metadata` (raw-ish JSON)
    - `models` (raw-ish JSON)
    - `shodan` (compact subset)
    - derived convenience fields: `version`, `gpu_name`
  - `ScanRun` stores a history row per scan attempt

DB configuration:
- `DATABASE_URL` in `.env`
- default: `sqlite:///./data/openports.db`

### 4) API

Backend entrypoint:
- `backend/app/main.py`

Endpoints (current):
- `GET /api/instances` list instances
- `GET /api/instances/{id}` instance detail
- `GET /api/scan/runs` scan history
- `POST /api/scan/shodan` trigger scan (optional auth)

Auth:
- If `ADMIN_TOKEN` is set, `POST /api/scan/shodan` requires header:
  - `Authorization: Bearer <ADMIN_TOKEN>`

Implementation detail:
- The scan trigger uses `BackgroundTasks` and runs `asyncio.run(...)` in a worker thread.

### 5) Notifications

- `backend/app/telegram.py` sends messages via the Telegram Bot API
- On scan, newly created + verified instances are announced.

Env vars:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Helper to discover chat id:
- `backend/tools/get_telegram_chat_id.py`

### 6) Frontend dashboard

- `frontend/src/ui/*`
- Uses `/api/*` via Vite dev proxy (`frontend/vite.config.ts`)

Pages:
- Instances list
- Instance detail (raw JSON for models + metadata)
- Scan runs + trigger scan

## Running the project (dev)

### Backend (uv)

```bash
cd backend
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt

cp ../.env.example .env
# Fill in keys. If you don’t want to set DATABASE_URL, remove it or leave it unset.

uv run uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open: http://localhost:5173

## Docker deployment (basic)

```bash
cp .env.example .env
# fill env

docker compose up --build
```

Frontend: http://localhost:8080
Backend: http://localhost:8000

## Debugging / enrichment tools

Tools are intentionally separated from the FastAPI app so agents can test fingerprint extraction without clicking around.

- Verify a single service:
  - `uv run python -m tools.verify_target comfyui http://HOST:8188`
  - `uv run python -m tools.verify_target ollama  http://HOST:11434`

- Scan a set of IPs quickly:
  - `uv run python -m tools.scan_ips 1.2.3.4 5.6.7.8`

- Enrich targets and print a JSON summary:
  - `uv run python -m tools.enrich 1.2.3.4 5.6.7.8`

- Shodan sanity check:
  - `uv run python tools/test_shodan.py`

## Guidance for coding agents

When extending this project:

1. **Prefer adding new discovery sources** as separate modules (`*_client.py`) that yield candidate `(ip, port)` pairs.
2. Keep **verification/fingerprinting** logic in `backend/app/fingerprints.py` and make it:
   - best-effort
   - timeout-bounded
   - able to run concurrently
3. Store raw-ish JSON under `Instance.service_metadata` and `Instance.models`, but avoid huge payloads.
   - If needed, add summarization/normalization later.
4. Any endpoint that triggers scans should be protected behind `ADMIN_TOKEN`.
5. Frontend should render backend responses as raw text (use `<pre>` for raw JSON).

## Known limitations / TODO

- Shodan Search API may be unavailable depending on plan; add Censys/Zoomeye/FOFA or implement manual import.
- No scheduled scanning yet (only manual trigger).
- Dashboard currently renders raw JSON; add nicer summary views (model counts, GPU, VRAM, etc.).
- Ollama GPU detection is not available via HTTP API; only host-side metrics would show it.
