# openports

Discover, fingerprint, and track **publicly exposed AI/ML service instances** on the internet — ComfyUI, Ollama, vLLM, SGLang, llama.cpp, Jupyter, Open WebUI, and 9 more.

> openports does **not** scan the internet. It pulls candidate `(ip, port)` pairs from third-party search engines (Shodan, Censys, ZoomEye, Netlas), then sends **one** verification request per candidate to confirm the service and pull metadata (version, GPU, models, VRAM). Raw nmap/masscan/zmap-style sweeps are explicitly out of scope.

## What it does

1. **Discover** candidates from authorized search-engine APIs.
2. **Fingerprint** each `(ip, port)` with a single targeted HTTP request and pull service metadata.
3. **Persist + diff** — track each instance over time, surface change history (alive flips, new models, version bumps), and fire Telegram alerts on standing rules.

Ships as a single process: FastAPI backend, Vite/React dashboard, and a Telegram bot.

## Supported services (16)

ComfyUI · Ollama · SD WebUI · Open WebUI · Jupyter · vLLM · TGI · Triton · Ray · text-generation-webui · LM Studio · SGLang · llama.cpp · LiteLLM · TensorBoard · CLIProxyAPI

Per-service fingerprints live in `backend/app/fingerprints.py`. Collision ports (`8000`, `8080`) cascade through multiple verifiers.

## Repo layout

```
openports/
├── backend/    FastAPI + SQLModel/SQLite + scanner + fingerprints + telegram bot
├── frontend/   Vite + React dashboard (5 pages: instances, detail, models, alerts, runs)
├── deploy/     nginx config for the frontend container
├── legacy/     old prototype scripts — reference only
└── docker-compose.yml
```

For a deeper tour (data model, discovery pipeline, fingerprint contract, troubleshooting) see [`AGENTS.md`](./AGENTS.md).

## Quickstart

### Docker (recommended)

```bash
cp .env.example .env
# fill in at least one source key + telegram (see "Configuration" below)

docker compose up --build
```

- Frontend: http://localhost:8080
- Backend:  http://localhost:8000

The frontend nginx reverse-proxies `/api/*` to the backend.

### Local dev

```bash
# backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env   # or backend/.env
uvicorn app.main:app --reload --port 8000

# frontend (in another shell)
cd frontend
npm install
npm run dev   # http://localhost:5173, /api proxied to :8000
```

## Configuration

Copy `.env.example` to `.env` and set what you have. At minimum one discovery source key + a Telegram bot is useful.

| variable | required | purpose |
|---|---|---|
| `SHODAN_API_KEY` | one source required | Shodan candidate fetch |
| `CENSYS_API_KEY` *or* `CENSYS_API_ID`+`CENSYS_API_SECRET` | one source required | Censys Search v2 |
| `ZOOMEYE_API_KEY` | one source required | ZoomEye host search |
| `NETLAS_API_KEY` | one source required | Netlas (comma-separated for round-robin across keys) |
| `TELEGRAM_BOT_TOKEN` | optional | bot + alert delivery |
| `TELEGRAM_CHAT_ID` | optional | default chat for alerts (helper: `python backend/tools/get_telegram_chat_id.py`) |
| `ADMIN_TOKEN` | optional | protects `POST /api/scan/*` and `POST /api/recheck/*` — send `Authorization: Bearer <token>` |
| `SCAN_INTERVAL_MINUTES` | default `0` | run a multi-source scan every N minutes (`0` = disabled) |
| `RECHECK_INTERVAL_MINUTES` | default `0` | re-fingerprint stored instances every N minutes |
| `RECHECK_STALE_AFTER_MINUTES` | default `60` | skip instances checked more recently than this |
| `RECHECK_CONCURRENCY` | default `25` | cap concurrent re-fingerprints |

## Telegram bot

If `TELEGRAM_BOT_TOKEN` is set, the backend polls for updates on startup and dispatches commands via `backend/app/commands.py`:

- `/help` · `/ping` · `/status`
- `/top` — top instances by VRAM / model count
- `/find <query>` — search models, GPUs, providers
- `/diff` — recent `InstanceChange` events
- `/alerts` — list / manage standing alert rules
- `/scan` — kick a multi-source scan (admin)
- `/recheck` — kick a recheck pass (admin)

Standing alerts (created via the dashboard's Alerts page or `/alerts`) match new instances and changes against optional filters: `service`, `gpu` (substring), `min_vram`, `model` (substring), `country`, `min_max_params`, `provider`.

## Dashboard

Five pages (Vite + React + react-router):

- **Instances** — list with URL-synced filters, saved searches, watch list, keyboard shortcuts, density toggle, CSV export
- **Instance detail** — history sparkline + change feed for one instance
- **Models** — unique-model catalog with counts across all instances
- **Alerts** — CRUD for standing alert rules
- **Runs** — scan-run history

Styled with a small vanilla CSS design system (cream/ink tokens, dark mode, Manrope) — no Tailwind, no shadcn. See `frontend/src/index.css`.

## Data

SQLite at `data/openports.db` (Docker) or `backend/data/openports.db` (local). Five tables: `Instance`, `InstanceCheck`, `InstanceChange`, `Alert`, `ScanRun`. Schema is created lazily on startup; additive column changes auto-migrate via `db._apply_lightweight_migrations()`. See [`AGENTS.md`](./AGENTS.md#3-data-model) for the full schema.

## Notes

- ComfyUI GPU details come from `GET /system_stats`.
- Ollama GPU model is **not reliably exposed** over the public HTTP API; we still collect models via `/api/tags` + `/api/show`.
- The `legacy/` directory is the original prototype kept for reference — it's not loaded by the app.

## License

No license declared. Treat as source-available, not open source — fork and adapt for personal use, but don't redistribute without asking.
