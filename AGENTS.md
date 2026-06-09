# AGENTS.md

handoff doc for any agent working on openports. **mirrored to [`CLAUDE.md`](./CLAUDE.md) and [`GEMINI.md`](./GEMINI.md) — when one changes, update all three so they stay byte-identical.**

---

## 1. what this project is

openports discovers, fingerprints, and tracks **publicly exposed ai/ml service instances** on the internet. it works in three steps:

1. **discover candidates** from third-party search-engine apis (shodan, netlas, censys, zoomeye) — never raw scanning
2. **fingerprint each (ip, port)** with a single targeted http request to confirm the service and pull metadata (version, gpu, models, vram, …)
3. **persist + diff** — track each instance over time, surface change history (alive flips, new models, version bumps), fire telegram alerts on standing rules

it ships a fastapi backend, a vite/react dashboard, and a telegram bot, all in one process.

### scope guardrails

- **never** add raw nmap/masscan/zmap-style internet sweeps from this project. discovery must go through authorized search-engine apis. verification must be a single fingerprint http request to one already-discovered (ip, port).
- never commit secrets, `.env`, `backend/.env`, or `*.db`.
- when changing deploy behavior, update this file (and the two mirrors).

### ownership map

| repo | owns | branches | deploy path | env source | smoke test |
|------|------|----------|-------------|------------|------------|
| `openports` | FastAPI scanner/API, Vite dashboard, Telegram bot, service fingerprints, candidate-source adapters, SQLite model/history/alerting | `main` is both default and current deploy branch; remote only exposes `main` | `docker compose up --build` from repo root, or backend/frontend run separately for dev | copy `.env.example` to `.env`; backend also supports `backend/.env` when running uvicorn from `backend/` | backend: `python -m compileall backend/app`; frontend: `cd frontend && npm run build` |

mirrored docs: `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md` must stay byte-identical. verify with `shasum AGENTS.md CLAUDE.md GEMINI.md`.

### supported services (16)

| service       | default port | verify\* | candidate fetch\*\* |
|---------------|--------------|----------|---------------------|
| comfyui       | 8188         | ✅       | ✅                  |
| ollama        | 11434        | ✅       | ✅                  |
| sdwebui       | 7860         | ✅       | ✅                  |
| openwebui     | 3000, 8080†  | ✅       | ✅                  |
| jupyter       | 8888         | ✅       | ✅                  |
| vllm          | 8000†        | ✅       | ✅                  |
| tgi           | 8080†        | ✅       | ✅                  |
| triton        | 8000†        | ✅       | ✅                  |
| ray           | 8265         | ✅       | ✅                  |
| tgwebui       | 5000         | ✅       | ✅                  |
| lmstudio      | 1234         | ✅       | ✅                  |
| sglang        | 30000        | ✅       | ✅                  |
| llamacpp      | 8080†        | ✅       | ✅                  |
| litellm       | 4000         | ✅       | ✅                  |
| tensorboard   | 6006         | ✅       | ✅                  |
| CLIProxyAPI   | 8317         | ✅       | ✅                  |

\* `backend/app/fingerprints.py:verify_<service>(base_url, client)` returns `(ok, meta, models, version, [gpu_name?], metrics)`.
\*\* one `port:<n>` query per port via `candidates_for_ports()` in each `*_client.py`.
† **collision ports** cascade through multiple verifiers in `scanner._verify_one`:
- port `8000` → triton → vllm
- port `8080` → tgi → llamacpp → openwebui

---

## 2. repo layout

```
openports/
├── AGENTS.md / CLAUDE.md / GEMINI.md   ← this doc (3 mirrored copies)
├── README.md                           ← user-facing intro (stale; describes only comfyui+ollama)
├── docker-compose.yml                  ← option a deploy
├── deploy/nginx.conf                   ← frontend container nginx
├── data/openports.db                   ← sqlite (production) — do not commit
├── .env / .env.example                 ← root env (used by docker compose)
│
├── backend/
│   ├── Dockerfile                      ← python:3.13-slim + uvicorn
│   ├── requirements.txt                ← fastapi, sqlmodel, httpx, shodan, apscheduler, pydantic-settings
│   ├── README.md
│   ├── data/openports.db               ← sqlite (local dev) — do not commit
│   ├── .env                            ← backend env (loaded by uvicorn cwd) — do not commit
│   └── app/
│       ├── main.py                 (707 lines) ← all http routes, spa fallback, startup hooks
│       ├── config.py               (67)   ← pydantic-settings; reads `backend/.env`
│       ├── db.py                   (90)   ← engine + `_apply_lightweight_migrations()`
│       ├── models.py               (150)  ← Service enum + Instance/InstanceCheck/InstanceChange/Alert/ScanRun
│       ├── scanner.py              (483)  ← run_shodan_scan + run_multi_source_scan + _upsert_instance + _verify_one
│       ├── recheck.py              (~100) ← run_recheck loop; dispatches via fingerprints.verify_for_service
│       ├── scheduler.py            (85)   ← apscheduler AsyncIOScheduler wiring
│       ├── fingerprints.py         (~950) ← verify_<service> per type + verify_for_service dispatcher
│       ├── shodan_client.py        (45)   ← uses official shodan pkg + SHODAN_API_KEY
│       ├── censys_client.py        (125)  ← search v2 api, basic auth or PAT
│       ├── zoomeye_client.py       (94)   ← api.zoomeye.ai/host/search
│       ├── netlas_client.py        (148)  ← app.netlas.io/api/responses/, round-robin keys
│       ├── enrich_hosting.py       (428)  ← classify_provider() via ASN + PTR + shodan org/isp
│       ├── alerts.py               (184)  ← evaluate_alerts() — match instance vs standing rules → telegram
│       ├── telegram.py             (61)   ← send_telegram_message + poll_telegram_updates
│       ├── commands.py             (307)  ← bot dispatcher: /help /ping /status /top /find /diff /alerts /scan /recheck
│       ├── security.py             (24)   ← require_admin (Bearer ADMIN_TOKEN)
│       └── models_summary.py       (93)   ← model_names() per service shape, diff_names()
│
├── backend/tools/                      ← one-off scripts (not loaded by the app)
│   ├── shodan_scraper.py               ← cookie-auth shodan scraper (not yet plumbed into multi-source)
│   ├── import_ips.py / scan_ips.py     ← bulk import from a file
│   ├── enrich.py                       ← backfill provider/reverse_dns
│   ├── verify_target.py                ← one-shot verify
│   ├── mock_comfyui.py / mock_ollama.py ← local stubs for dev
│   ├── get_telegram_chat_id.py
│   └── test_shodan.py
│
├── frontend/
│   ├── Dockerfile                      ← node:20-alpine build → nginx:alpine
│   ├── vite.config.ts                  ← dev port 5173, /api → http://localhost:8000
│   ├── package.json                    ← react 18, react-router-dom 6, vite 5, typescript 5
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── index.css                   ← cream/ink design tokens, dark mode, component classes
│       └── ui/
│           ├── App.tsx                 ← header + theme toggle + router (5 routes)
│           ├── api.ts                  ← all fetch wrappers + Service type union
│           ├── format.ts               ← provider styles, country flag emoji map, time formatters
│           ├── InstancesPage.tsx       (857) ← list + filters + saved searches + watch list + keyboard shortcuts
│           ├── InstanceDetailPage.tsx  (407) ← history sparkline + change list
│           ├── ModelsPage.tsx          (159) ← unique-model catalog with counts
│           ├── AlertsPage.tsx          (312) ← alert CRUD form
│           └── RunsPage.tsx            (125) ← scan run history
│
└── legacy/                             ← old prototype scripts; reference only
```

---

## 3. data model

`backend/app/models.py` defines five sqlmodel tables. all created lazily on startup; new columns are auto-added by `_apply_lightweight_migrations`.

### `Instance` (one row per discovered (service, ip, port))
- ids: `id` PK, `service` (Service enum, indexed), `ip` (indexed), `port` (indexed)
- timestamps: `first_seen_at`, `last_seen_at`, `last_checked_at`, all indexed
- liveness: `is_alive` (indexed)
- enrichment: `provider` (indexed: `aws|gcp|azure|digitalocean|vultr|linode|hetzner|ovh|residential|unknown|...`), `reverse_dns`
- json blobs: `shodan` (compact match: ip_str/port/org/isp/asn/hostnames/domains/transport/timestamp/product/version/os/location), `service_metadata`, `models`
- derived metrics: `title`, `version`, `gpu_name`, `vram_total_gb`, `vram_free_gb`, `ram_total_gb`, `ram_free_gb`, `model_count`, `max_model_params` (B params), `max_context`, `node_count`
- discovery: `discovery_sources` (json array, e.g. `["shodan","netlas"]`)
- `last_error`

### `InstanceCheck` (history of fingerprint attempts)
one row per verify call. captures `is_alive`, `version`, `gpu_name`, vram, model_count, max_model_params, max_context, error, `checked_at`. used to draw history sparklines and the `/api/instances/{id}/history` feed.

### `InstanceChange` (detected diffs between consecutive fingerprints)
emitted by `_upsert_instance` after a verify. `kind ∈ {first_seen, alive_changed, version_changed, gpu_changed, models_changed}`. `before`/`after` are json. `models_changed.after` carries `{count, added: [...], removed: [...]}`. drives the `/api/instances/{id}/changes` feed and `/diff` telegram command.

### `Alert` (standing rules, fired by `alerts.evaluate_alerts`)
- `kind ∈ {new_instance, models_added, alive_changed}`
- `filter_json` (all optional, ANDed): `service`, `gpu` (substring, case-insensitive), `min_vram` (float GB), `model` (substring), `country` (exact name), `min_max_params` (float B), `provider` (`vps|residential|unknown` or specific provider key)
- bookkeeping: `enabled`, `last_fired_at`, `fired_count`

### `ScanRun`
one row per scan invocation. `source` is `shodan` / `multi:<sources_csv>` / `recheck`. tracks `candidates`, `verified`, `new_instances`, `started_at`, `finished_at`, `error`. `finished_at IS NULL` means the worker died mid-scan (see troubleshooting).

### lightweight migrations

`backend/app/db.py:_apply_lightweight_migrations()` runs on every startup after `create_all`. it diffs `SQLModel.metadata` against the live schema via `sqlalchemy.inspect`, then issues `ALTER TABLE <t> ADD COLUMN <c> <type>` for any missing columns. **safe to add new fields freely.** for non-additive changes (rename / drop / type-change), you must write explicit sql or wipe the db.

---

## 4. discovery pipeline

### candidate fetchers

every source client (`shodan_client`, `censys_client`, `zoomeye_client`, `netlas_client`) exposes:

- `_enabled() -> bool` — true iff credentials are configured
- `candidates_for_ports(limit: int) -> list[dict]` — iterates `SUPPORTED_PORTS` and yields **compact-shape** dicts

#### compact shape (the contract every source must conform to)

```python
{
  "ip_str": "1.2.3.4",
  "port": 11434,
  "org": "Example LLC" | None,
  "isp": "Example Telecom" | None,
  "asn": 12345 | None,                  # int, not "AS12345"
  "hostnames": ["foo.example.com"],     # list[str]
  "domains": ["example.com"],
  "transport": "tcp",
  "timestamp": "2026-05-07T...",        # source-reported
  "product": None,
  "version": None,
  "os": None,
  "location": {
    "country_name": "US" | None,
    "region_code": "CA" | None,
    "city": "Mountain View" | None,
    "latitude": 37.4 | None,
    "longitude": -122.1 | None,
  },
  "_source": "shodan" | "censys" | "zoomeye" | "netlas",
}
```

if you add a new source, output exactly this shape.

### orchestrator (`scanner.run_multi_source_scan`)

1. starts a `ScanRun` row with `source="multi:<csv>"`
2. calls each enabled source's `candidates_for_ports(limit)` synchronously (sources are sync httpx; this blocks the event loop briefly)
3. **dedupes by `(ip, port)`** — keeps the first (richest) record but unions `_source` values into `discovery_sources`
4. for each unique target, looks up `_service_from_port(port)` and creates a `_verify_one` task; runs them under `asyncio.Semaphore(VERIFY_CONCURRENCY)` (default 50)
5. on each result, calls `_upsert_instance` which:
   - inserts/updates the `Instance` row
   - appends an `InstanceCheck`
   - emits `InstanceChange` rows for any diffs vs the snapshot it took before commit
   - calls `evaluate_alerts(...)` (best-effort, never aborts)
   - if newly-created and alive, sends a telegram dm
6. updates the `ScanRun` with `verified`, `new_instances`, `finished_at`

### shodan-only (`scanner.run_shodan_scan`)

simpler path used by the legacy `/api/scan/shodan` endpoint and the apscheduler `_scan_job`. queries shodan only, no dedupe across sources. useful when shodan is your only credentialed source.

### recheck loop (`recheck.run_recheck`)

re-fingerprints **already-stored** instances (no new candidates from search engines). filters:
- `only_alive`: skip dead ones
- `only_stale`: skip rows whose `last_checked_at` is fresher than `RECHECK_STALE_AFTER_MINUTES`
- `limit`: cap how many

ordered oldest-checked-first. dispatch is via `fingerprints.verify_for_service(inst.service, base_url, client)` — the same helper backs `POST /api/instances/{id}/refresh`. all 16 services are routed to their own verify_*.

### service-from-port mapping

```python
8188  → comfyui
11434 → ollama
7860  → sdwebui
3000  → openwebui
8888  → jupyter
8000  → vllm     (cascades: triton → vllm)
8080  → tgi      (cascades: tgi → llamacpp → openwebui)
8265  → ray
5000  → tgwebui
1234  → lmstudio
30000 → sglang
4000  → litellm
6006  → tensorboard
8317  → CLIProxyAPI
```

returning `None` from `_service_from_port` causes the candidate to be skipped (logged at debug only).

---

## 5. source-api state (as of 2026-05-07)

| source   | works? | env vars                                      | notes                                                                 |
|----------|--------|-----------------------------------------------|-----------------------------------------------------------------------|
| shodan   | ✅     | `SHODAN_API_KEY`                              | uses the official `shodan` python package                             |
| netlas   | ✅     | `NETLAS_API_KEY` (comma-separated for round-robin) | free tier 50 req/day per key. client auto-failover on 401/403/429. confirmed 140 candidates per scan. 30s timeout — the free endpoint is slow. |
| censys   | ❌     | needs `CENSYS_API_ID` + `CENSYS_API_SECRET` (or PAT, see below) | the existing PAT-style `censys_…` token does **not** authenticate against search v2; the client tries Bearer auth as a fallback but it returns 401. needs an actual API_ID + API_SECRET pair. |
| zoomeye  | ❌     | `ZOOMEYE_API_KEY`                             | endpoint is `https://api.zoomeye.ai/host/search` (the older `.org` returns 403 "service not available in your area"). current key auths but the account has 0 credits — zoomeye no longer offers free tier credits for these queries. |

**candidates worth wiring next** (all have free tiers in 2026-05):

- **onyphe** (`onyphe.io`) — ~100 results/day, api key. different crawler from netlas, fills coverage gaps.
- **leakix** (`leakix.net`) — different angle — explicitly indexes misconfigs/leaks. good for finding open admin panels and exposed ai dashboards.
- **fofa** (`fofa.info`) — small daily credits. best asia-region coverage. registration friction (email + key).
- **hunter.how** — china-focused, fast, ~100/day.
- **shodan cookie scraper** — `backend/tools/shodan_scraper.py` already exists; not yet wired into `run_multi_source_scan`. plumbing it in unlocks "free shodan" via your logged-in cookie.

to add one: copy `netlas_client.py`, rewrite `_search` against the new endpoint, ensure the output matches the compact shape, then add a branch in `run_multi_source_scan` (`scanner.py` ~line 339):

```python
if "<name>" in chosen and <name>_client._enabled():
    gathered.extend(<name>_client.candidates_for_ports(limit=limit))
```

and add `<name>` to the default `chosen` list.

---

## 6. http api surface

all routes return json unless noted.

### read

| method | path                                      | notes |
|--------|-------------------------------------------|-------|
| GET    | `/api/instances`                          | full filter set (see below); `limit` ≤ 1000, `offset` ≥ 0 |
| GET    | `/api/instances/count`                    | same filters minus pagination/sort |
| GET    | `/api/instances/{id}`                     | one instance |
| GET    | `/api/instances/{id}/history`             | InstanceCheck rows desc by checked_at; `limit` ≤ 2000 |
| GET    | `/api/instances/{id}/changes`             | InstanceChange rows desc by at; `limit` ≤ 1000 |
| GET    | `/api/instances/distinct/{field}`         | `field ∈ {gpu, provider, version, country}` |
| GET    | `/api/instances.csv`                      | streamed csv with same filters; 18 cols |
| GET    | `/api/stats`                              | totals, by_service, by_provider, recent_24h/7d, stale_24h, last_run, scheduler intervals |
| GET    | `/api/models/catalog`                     | unique model names with instance counts; supports `service`, `q`, `alive_only`, `limit` |
| GET    | `/api/scan/runs`                          | recent ScanRun rows; `limit` ≤ 500 |
| GET    | `/api/alerts`                             | all Alert rows |

#### `GET /api/instances` filter args

`service`, `alive` (bool), `provider` (`vps|residential|unknown` or specific key), `q` (substring match on ip/version/gpu_name/title/reverse_dns), `model` (substring match on json-cast `models`), `gpu` (substring on `gpu_name`), `country` (exact name), `since_hours` (last_seen_at within), `stale_hours` (last_checked_at older than), `min_vram` (float GB), `sort_by ∈ {last_seen_at, first_seen_at, vram_total_gb, vram_free_gb, model_count, max_model_params, max_context, node_count}`, `sort_dir ∈ {asc, desc}`.

`provider=vps` resolves to "anything not in `{residential, unknown, NULL}`".

### admin (require `Authorization: Bearer <ADMIN_TOKEN>` if `ADMIN_TOKEN` is set)

| method | path                                      | notes |
|--------|-------------------------------------------|-------|
| POST   | `/api/instances/{id}/refresh`             | one-shot verify of one instance via `fingerprints.verify_for_service` |
| POST   | `/api/scan/shodan?limit=N`                | trigger one shodan scan (background task) |
| POST   | `/api/scan/multi?sources=shodan,censys,zoomeye,netlas&limit=N` | trigger a multi-source scan (background task). omit `sources` for "all enabled". |
| POST   | `/api/scan/recheck?only_stale=true&only_alive=false&limit=N` | trigger recheck (background task) |
| POST   | `/api/alerts`                             | body `{name, kind, filter_json, enabled?}` |
| PATCH  | `/api/alerts/{id}`                        | same body shape |
| DELETE | `/api/alerts/{id}`                        |  |

### spa fallback

`GET /{full_path:path}` (registered last) serves the built frontend from `frontend/dist/` if present:
- `/assets/*` mounted as `StaticFiles`
- any other path: serve the file if it exists, else `index.html` (so react-router handles it)
- requests starting with `api/` raise 404 instead

### startup hooks

- `init_db()` — creates schema + applies migrations
- `asyncio.create_task(_start_telegram_poller())` — long-poll bot in background
- `start_scheduler()` — register apscheduler jobs (only if intervals > 0)

---

## 7. telegram bot

long-polls `getUpdates` in-process — **no webhook**. only messages from the configured `TELEGRAM_CHAT_ID` are handled. all replies go to that same chat.

### commands

| command                            | does what |
|------------------------------------|-----------|
| `/help`                            | print command list |
| `/ping`                            | reply "pong" |
| `/status`                          | total / alive / by-service-counts / stale 24h / last scan / scheduler intervals |
| `/top [n]`                         | top n alive by `vram_total_gb` (n ∈ [1, 50], default 10) |
| `/find gpu \| model \| country <value>` | substring match (gpu/model) or exact match (country); returns up to 50 |
| `/diff <id> [n]`                   | last n InstanceChange rows for instance #id (n ∈ [1, 50], default 10) |
| `/alerts`                          | list standing alerts with `enabled` flag and fired_count |
| `/scan`                            | trigger one shodan scan via background executor |
| `/recheck [n] [force] [alive]`     | trigger recheck. `force` clears `only_stale`, `alive` sets `only_alive`, the int sets `limit` |
| `/scrape ...`                      | legacy cookie-based shodan scraper handler in `main.py` (gpu/model/force/--page args) |

### outbound notifications

- **new instance:** sent on `created and ok` from a scan: `new <service>: <ip>:<port>\nversion=<v> gpu=<g> via <sources>`
- **alerts:** `evaluate_alerts` sends per-match messages with `🔔 <name>` + service + facts (gpu, vram, model count, max params) + an "extra" line per kind

---

## 8. configuration

`backend/app/config.py` uses `pydantic-settings` to read **`backend/.env`** (relative to uvicorn's cwd, which is `backend/` when launched from there). when running under `docker compose`, compose passes the **root** `.env` instead via `env_file: ./.env`.

### required-ish

```
SHODAN_API_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

### multi-source + secondary

```
NETLAS_API_KEY=key1,key2          # comma-separated → round-robin auto-failover
CENSYS_API_ID=...
CENSYS_API_SECRET=...
CENSYS_API_KEY=...                # PAT, currently ineffective for search v2
CENSYS_COOKIE=...                 # used by tools/shodan_scraper.py only
ZOOMEYE_API_KEY=...
ZOOMEYE_COOKIE=...                # used by tools/shodan_scraper.py only
SHODAN_COOKIE=...                 # used by tools/shodan_scraper.py only
```

### admin

```
ADMIN_TOKEN=...                   # if set, all /api/scan/*, /api/alerts CRUD, /api/instances/{id}/refresh require Bearer auth
```

### http / db / cors

```
DATABASE_URL=                     # default: sqlite:///./data/openports.db; empty string is coerced to default
CORS_ORIGINS=*                    # csv list; "*" disables credentials in cors
HTTP_TIMEOUT_SECONDS=4.0          # per-fingerprint timeout
SHODAN_LIMIT=200                  # default per-port limit on shodan/multi scans
VERIFY_CONCURRENCY=50             # asyncio.Semaphore for verify tasks
OLLAMA_SHOW_LIMIT=30              # cap on per-model /api/show calls during ollama verify
```

### scheduler

```
SCAN_INTERVAL_MINUTES=0           # 0 disables. multi-source scan tick (all enabled sources, not just shodan). off by default — credits are precious.
SCAN_SOURCES=                     # blank = all enabled. csv subset (e.g. "netlas") to keep the cron off shodan credits.
RECHECK_INTERVAL_MINUTES=120      # current production setting
RECHECK_STALE_AFTER_MINUTES=60    # only re-fingerprint instances older than this
RECHECK_CONCURRENCY=25            # cap on parallel recheck fingerprints
SCHEDULER_MISFIRE_GRACE_SECONDS=300  # how late a tick may fire before it's skipped. apscheduler's 1s default silently drops ticks when the loop is busy.
```

apscheduler runs an `AsyncIOScheduler` inside the same event loop as fastapi. only registers a job when its interval > 0. job defaults are `misfire_grace_time=SCHEDULER_MISFIRE_GRACE_SECONDS, coalesce=True, max_instances=1` so a briefly-busy loop doesn't silently drop a tick, backed-up runs collapse into one, and concurrent runs don't overlap. sync jobs run in the loop's default thread pool (so `asyncio.run` inside them is fine and blocking source clients never freeze the api). job executed/missed/error/max-instances events are logged, and `/api/stats.scheduler` exposes `running` + `next_scan_at` / `next_recheck_at`.

---

## 9. deployment

two supported paths.

### a) docker — single-host, recommended for new servers

```bash
git clone https://github.com/safzanpirani/openports
cd openports
cp .env.example .env
# fill: SHODAN_API_KEY, TELEGRAM_*, NETLAS_API_KEY, ADMIN_TOKEN, etc.
mkdir -p data
docker compose up -d --build
```

**ports & layout:**
- backend container: serves fastapi on `0.0.0.0:8000`, mapped host `8000`
- frontend container: nginx on `0.0.0.0:80` (build from `node:20-alpine`, served by `nginx:alpine`), mapped host `8080`
- frontend nginx (`deploy/nginx.conf`) proxies `/api/*` → `http://backend:8000/api/` over the compose default network; everything else falls back to `index.html`
- sqlite at host `./data/openports.db` ↔ container `/app/data/openports.db`

**env source:** root `.env` (compose `env_file: ./.env`). do **not** rely on `backend/.env` in docker mode.

**when migrating from local dev:** if you want to keep history, copy `backend/data/openports.db` → `data/openports.db` on the server before first boot.

**day-2:**
```bash
git pull --ff-only
docker compose up -d --build      # rebuild + restart
docker compose logs -f backend    # tail backend
docker compose ps                 # status
```

### b) windows scheduled task — current production

production runs on **`serverts`** (tailscale `100.94.255.59`, windows `DESKTOP-HANHL0U`, user `Admin`):

- repo at `C:\Users\Admin\Downloads\projects\openports`
- python venv at `backend\.venv\` (uv-installed, python 3.13.7-windows-x86_64)
- started by **scheduled task `OpenPorts Backend`** running `backend\run_openports_backend.ps1` (kept on the server, not in the repo)
- uvicorn binds `0.0.0.0:8000` (reachable over tailscale)
- env loaded from `backend\.env` (uvicorn's cwd is `backend\`)
- frontend served by uvicorn's spa fallback from `frontend/dist/` — no separate web server

#### why not git pull on the server

the server's `gh` is authed as a different github user (`rakhikaag`), without push/clone access to `safzanpirani/openports`. don't try to fix this — deploys are tarball-based instead.

#### deploy recipe (tarball + scp + powershell)

from your mac:

```bash
cd /Users/safzan/Development/projects/openports

# bundle only what changed (faster + safer than full repo)
COPYFILE_DISABLE=1 tar \
  --exclude='.venv' --exclude='__pycache__' --exclude='.git' \
  -czf /tmp/openports_patch.tgz \
  backend/app/<changed_files>

scp /tmp/openports_patch.tgz serverts:/tmp/openports_patch.tgz
# /tmp on serverts (over scp) maps to C:\tmp\, NOT %TEMP%

# write a ps1 locally that extracts + restarts, then run it on the server
scp /tmp/apply.ps1 serverts:/tmp/apply.ps1
ssh serverts 'powershell -ExecutionPolicy Bypass -File C:\tmp\apply.ps1'
```

**`COPYFILE_DISABLE=1` is mandatory** — macOS tar leaks `._*` AppleDouble files into the archive otherwise; they show up as garbage `app/._scanner.py` files on extract.

#### canonical restart pattern

`Stop-ScheduledTask` only kills the powershell wrapper; the python child stays bound to `:8000`. **always do both:**

```powershell
# capture the listener pid BEFORE asking the task to stop
$ownerPids = (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
              Select-Object -Expand OwningProcess -Unique)
Stop-ScheduledTask -TaskName 'OpenPorts Backend' -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1
foreach ($ownerPid in $ownerPids) { Stop-Process -Id $ownerPid -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2
Start-ScheduledTask -TaskName 'OpenPorts Backend'
Start-Sleep -Seconds 6
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/stats' -TimeoutSec 8
```

#### powershell / windows landmines

| pitfall | why it bites | fix |
|---------|--------------|-----|
| `$pid` as a variable name | powershell auto-var = current process pid; reassigning = chaos | always rename to `$ownerPid` (or anything else) |
| `Stop-ScheduledTask` alone | doesn't kill python child | also `Stop-Process` the listener pid |
| `--no-edit` on `git rebase` | not a valid flag (only on git pull/merge) | omit it or set `core.editor=true` |
| `scp …:/tmp/foo` | maps to `C:\tmp\`, not windows `%TEMP%` | upload to `C:\tmp\` deliberately, or use a fully-qualified path |
| heredoc python in `powershell -c '@\"…\"@'` over ssh | quoting eats the `'` and breaks the python source | write `.py` files locally, scp them, then run via `& '.\.venv\Scripts\python.exe' '.\file.py'` |
| `$ErrorActionPreference = 'Stop'` | only stops on cmdlet failures; native exit codes (tar, etc) are ignored | check `$LASTEXITCODE` after every native invocation |
| omitted `-File` on `powershell` | leading slashes in the script path get interpreted as positional args | always `powershell -ExecutionPolicy Bypass -File C:\tmp\foo.ps1` |
| macOS `tar` AppleDouble | leaks `._*` siblings | export `COPYFILE_DISABLE=1` before tar |

### dev (no docker, no remote)

```bash
# backend
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # then fill in keys
uvicorn app.main:app --reload --port 8000

# frontend
cd ../frontend
npm install
npm run dev               # vite on :5173, proxies /api → :8000
```

build the spa for production hosting:

```bash
cd frontend
npm run build              # output: frontend/dist/
# uvicorn now serves /frontend/dist via the spa fallback in main.py
```

---

## 10. conventions

### code style

- prose in lowercase across docs and ui copy (existing convention — match it)
- use type hints throughout backend; `from __future__ import annotations` at the top of every module
- async for any work that does i/o on more than one thing in flight; sync httpx is fine for single calls in source clients
- python 3.11+ idioms ok; production runs on 3.13
- never bare `except:` — at minimum `except Exception:` and log via `log.exception(...)` or swallow with a comment

### sqlmodel + sqlite gotchas

- json columns: declare with `sa_column=Column(JSON)`; sqlite stores them as text but `json_extract($.path)` works
- to substring-match a json column: `func.lower(cast(Instance.models, Text)).like("%foo%")` — `cast` from `sqlalchemy`, `Text` from `sqlalchemy`
- to filter on a json field: `func.json_extract(Instance.shodan, "$.location.country_name")`
- nulls-last sort: `Column.is_(None), Column.desc()` works on sqlite (avoid `.nullslast()` — deprecated in 2.x)

### adding a new service type

1. add to `Service` enum in `backend/app/models.py`
2. write `verify_<svc>` in `backend/app/fingerprints.py` — return `(ok, meta, models, version, [gpu_name?], metrics)` (5- or 6-tuple, match neighbors)
3. import + dispatch in `scanner._verify_one` (keyed on port)
4. add the port to `_service_from_port` in `scanner.py`
5. add the port to `SUPPORTED_PORTS` tuples in **all** four source clients (`shodan_client`, `censys_client`, `zoomeye_client`, `netlas_client`)
6. extend the `Service` union in `frontend/src/ui/api.ts`
7. add the option to the `<select>` in `frontend/src/ui/ModelsPage.tsx`
8. if the service exposes a model list, add a branch in `models_summary.model_names()` so the catalog and diff feeds work
9. add the new enum branch to `fingerprints.verify_for_service` so recheck and per-instance refresh dispatch correctly

### adding a new candidate source

1. copy `backend/app/netlas_client.py` as a template — it has the cleanest patterns (round-robin + auto-failover)
2. implement `_enabled()`, `_search()`, `candidates_for_ports()`
3. ensure `_compact()` returns the exact compact shape (see § 4)
4. add the import + branch in `scanner.run_multi_source_scan` and append the source name to the default `chosen` list
5. add the env var to `backend/app/config.py:Settings`
6. document the source in this file's § 5 table

### secrets hygiene

- never commit any of: `.env`, `backend/.env`, `*.db`, files in `data/`
- when you add a new env var, also add it to `.env.example` (without a real value)
- if you must show a key in logs, slice the last 6 chars only (`key[-6:]`) — see how `netlas_client._search` does it

---

## 11. troubleshooting

| symptom | cause | fix |
|---------|-------|-----|
| `no such column: instance.<X>` on api request | older db missing a column that was added to the model | restart the process — `_apply_lightweight_migrations` runs on startup. if it doesn't pick it up, check the column type rendering in `db.py` |
| `ScanRun` rows with `finished_at: null` and `cands=0` | the python worker was killed mid-scan (most often: forgot to `Stop-Process` before `Start-ScheduledTask`) | the row stays orphaned forever. ignore or delete it manually. for next time, follow the canonical restart pattern in § 9b |
| `port 8000 already in use` after `Start-ScheduledTask` | previous python child still alive | `Stop-Process` the owner of the listener pid before starting the task |
| netlas returns 0 hits with httpx ReadTimeout | server-to-netlas connection is slow on free tier | bump `httpx.Client(timeout=…)` in `netlas_client._search` (already 30s — try 45s if it persists) |
| censys 401 with token starting `censys_…` | not a valid search v2 credential — it's a PAT and the api doesn't accept Bearer auth despite advertising it | requires API_ID + API_SECRET pair from search.censys.io console |
| zoomeye 402 `credits_insufficent` | account has no credits | free tier is gone for these queries; need a paid plan |
| zoomeye 403 `service not available in your area` | hitting old `.org` endpoint | the client uses `https://api.zoomeye.ai/host/search`; verify if you copied an old client |
| `func.cast(col, text("TEXT"))` raises | sqlalchemy 2.x doesn't accept stringly-typed casts | use `cast(col, Text)` from `sqlalchemy` |
| cron tick logs but no scan happens | `SCAN_INTERVAL_MINUTES=0` (default) — only registers a job when > 0 | set `SCAN_INTERVAL_MINUTES=N` and restart |
| scan cron fires some ticks but skips others | event loop was briefly busy at tick time; apscheduler's old 1s misfire grace dropped the run | fixed: job default is now `misfire_grace_time=SCHEDULER_MISFIRE_GRACE_SECONDS` (300s). bump it higher if you still see "missed its run time" warnings |
| intermittent `database is locked` aborting a scan | concurrent writes from the scan worker thread + api reads on stock sqlite | fixed: db.py sets `journal_mode=WAL` + `busy_timeout=30000` on connect. confirm with `sqlite3 data/openports.db "PRAGMA journal_mode"` → `wal` |
| scheduled scan returns 0 even though netlas works | the cron used to query shodan only | fixed: the scheduled job now runs `run_multi_source_scan` across all enabled sources (override with `SCAN_SOURCES`) |
| `_apply_lightweight_migrations` warns `migrate <table>.<col> failed` | sqlite can't add a column with a non-trivial default or a non-rendered type | drop the default in the model, or add the column manually with `sqlite3 data/openports.db "ALTER TABLE …"` |
| `discovery_sources` is `null` on instances inserted before round-3 | older rows predate the column | running a `/api/scan/multi` will populate it on next sighting |

### health check after any deploy

```bash
curl http://127.0.0.1:8000/api/stats
# {"total":311,"alive":138,"by_service":{...},"scheduler":{"scan_interval_minutes":0,"recheck_interval_minutes":120},...}

# the scheduler.* values must match the env you intended to set
# the most recent ScanRun should have finished_at ≠ null
curl http://127.0.0.1:8000/api/scan/runs | head -c 500
```

ui:

- `http://SERVER_IP:8080` (docker) or `http://SERVER_IP:5173` (dev) or `http://SERVER_IP:8000` (when uvicorn serves the built spa)
- `/instances`, `/models`, `/alerts`, `/runs` all load
- on each page, devtools network tab shows `/api/*` requests succeeding

---

## 12. policy for agents

- prefer **small explicit changes** over sweeping refactors. show diffs, not rewrites.
- if you change the deploy story (a new env var, a new port, a new source client, a schema migration that's not additive), update this file in all three mirrors.
- if a task touches the production server, follow § 9b's restart pattern exactly. don't invent shortcuts; the windows quirks are non-negotiable.
- if you're about to add internet-wide scanning, **stop and ask** — that's outside the scope of this project (see § 1 scope guardrails).
- when in doubt about a source's compact-shape mapping, run a single `_search()` from a python repl with the venv and inspect a sample response before committing.
