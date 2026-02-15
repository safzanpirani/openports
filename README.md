# openports

Find and track *publicly exposed* ComfyUI (8188) and Ollama (11434) instances.

> Note: Internet-wide scanning can be illegal/abusive if you do it yourself. The intended approach for this repo is to use **third-party indexes** (e.g., Shodan/Censys) to discover candidates, then **verify + fingerprint** them, and store results for later viewing.

## Goals
- Discover candidate IPs via Shodan (and later Censys)
- Verify services:
  - ComfyUI: confirm API + collect `/system_stats` (GPU), `/models/*` (models)
  - Ollama: confirm API + collect `/api/version`, `/api/tags`, and per-model `/api/show`
- Notify via Telegram when new instances are found
- Store results in a DB
- Provide a small hosted dashboard to view history and metadata

## Repo layout
- `legacy/` – old prototype scripts (kept for reference)
- `backend/` – FastAPI API + scanner + SQLite storage
- `frontend/` – React dashboard (Vite)

## Quickstart (dev)

### 1) Backend
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp ../.env.example .env
# edit .env (SHODAN_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)

uvicorn app.main:app --reload --port 8000
```

### 2) Frontend
```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

## Notes
- ComfyUI GPU details: usually available via `GET /system_stats`.
- Ollama GPU model: **not reliably available** via the public HTTP API; we still collect model lists via `/api/tags` + `/api/show`.
- To protect triggering scans, set `ADMIN_TOKEN` in `.env` and send `Authorization: Bearer <token>`.
