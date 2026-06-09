# PRODUCT.md

product overview, surface-by-surface feature inventory, and bot↔webui parity matrix.

scope: this is the **what users actually see and do**. for internals (data model, deployment, source-api state) see [`AGENTS.md`](./AGENTS.md).

---

## 1. what the product does (user view)

openports is a **persistent observatory of publicly exposed ai/ml services**. you point it at search-engine apis (shodan, netlas, …), and it gives you back:

- a continuously-updated catalog of every comfyui / ollama / vllm / etc. instance it has seen
- per-instance fingerprints — version, gpu, vram, model list, max-params, country, provider
- a full timeline per instance — every fingerprint check + every change event (alive flip, version bump, models added/removed)
- standing alert rules that fire to telegram when a new match shows up
- a multi-source scan engine you can trigger on demand or on a cron

day-to-day you use it through one of three surfaces:

| surface              | best for                                                   |
|----------------------|------------------------------------------------------------|
| **webui** (port 8000) | exploration, filtering, drilling into one instance, alert CRUD |
| **telegram bot**      | quick lookups, push notifications, hands-free triggers     |
| **http api**          | scripting, csv export, headless integrations               |

---

## 2. webui — what each page does

5 routes, all rendered by a single SPA served from `frontend/dist/` by uvicorn (or by nginx in docker mode).

### `/` instances list (the workhorse)

the densest page. `frontend/src/ui/InstancesPage.tsx`.

- **stats bar (top):** total / alive · by-service breakdown (clickable badges) · new in 24h / 7d · stale > 24h · cron schedule
- **filters (toolbar 1):** service dropdown (all 16 with counts) · free-text search (ip / gpu / version / hostname / reverse_dns) · model substring · provider · gpu (distinct list) · country (distinct list) · min vram (GB)
- **toggle chips:** alive only · seen ≤ 24h · stale > 24h · ★ starred only · clear-all
- **table columns:** ★ · service · ip:port · provider · country · alive/down · version · gpu · vram · models · max params · ctx · last seen (with discovery-source badges) · actions (open ↗ / copy ⧉)
- **sortable:** vram, model_count, max_params, max_context, last_seen (asc/desc)
- **pagination:** 50 / 100 / 200 / 500 per page; url is the source of truth (every filter is a query-param so links are shareable)
- **persistent state (localStorage):** ★ starred ids, named saved views, compact-row toggle
- **actions:** `↻` refresh · `auto on/off` (30s poll) · `↧ csv` (filtered csv export) · `recheck` · `shodan` (scan) · `multi-scan`
- **keyboard shortcuts:** `/` focus search · `m` focus model · `r` reload · `a` toggle alive · `c` toggle compact · `?` help · `Esc` clear

### `/instances/:id` instance detail

`frontend/src/ui/InstanceDetailPage.tsx`.

- header chips: service badge · ip:port · alive/down · provider
- header buttons: `↗ open` · `⧉ copy url` · `↻ refresh` (re-fingerprint on demand, admin)
- **kv card:** last seen · first seen · last checked · version · gpu · vram · ram · models · max params · max context · node count · reverse dns · country/city · org/isp · asn · discovery sources · last error
- **history sparkline:** every `InstanceCheck` rendered as a coloured bar (green=alive, red=down), oldest → newest, hover for timestamp
- **changes feed:** chronological list of `InstanceChange` rows — first_seen, alive_changed, version_changed, gpu_changed, models_changed (with expandable +/- model diff)
- **models view:** comfyui → grouped lists (checkpoints, loras, vae, controlnet); ollama → table with family, params, quant, size, context. ⚠ other 14 services have no specialised view yet (shows raw json blob).
- raw `service_metadata` and raw `shodan` record under `<details>` toggles

### `/models` model catalog

`frontend/src/ui/ModelsPage.tsx`. unique model names across the fleet, with the count of instances that expose each. supports a service filter, substring query, and alive-only toggle.

### `/alerts` alert rules

`frontend/src/ui/AlertsPage.tsx`. CRUD UI for standing alert rules.

- form fields: name · kind (`new_instance` / `models_added` / `alive_changed`) · service · gpu contains · min vram · min max params · model contains · country · provider · enabled checkbox · (for `alive_changed`) only-on-up / only-on-down
- table: id · enabled toggle · name · kind · filter summary · fired count · last fired · edit / delete
- service dropdown covers all 16 supported service types.

### `/runs` scan run history

`frontend/src/ui/RunsPage.tsx`. recent `ScanRun` rows: source (shodan / multi:… / recheck), candidates, verified, new instances, started_at, finished_at, errors.

---

## 3. telegram bot — what each command does

`backend/app/commands.py`. long-poll, no webhook. only the configured `TELEGRAM_CHAT_ID` is honoured.

### read commands

| command                            | does                                                                                          |
|------------------------------------|-----------------------------------------------------------------------------------------------|
| `/help`                            | print command list                                                                            |
| `/ping`                            | reply "pong" — health check                                                                   |
| `/status`                          | total / alive / per-service counts / stale 24h / last scan / scheduler intervals              |
| `/top [n]`                         | top `n` alive instances by `vram_total_gb` (n ∈ [1, 50], default 10)                          |
| `/find key=value [...]`            | multi-axis filter — `service`, `gpu`, `model`, `country`, `provider`, `version`, `vram>=N`, `params>=N`. legacy single-axis form (`/find gpu rtx`) still works. up to 50 results |
| `/diff <id> [n]`                   | last `n` change events for instance #id (n ∈ [1, 50], default 10)                             |
| `/show <id>`                       | full kv card: service · ip:port · alive · gpu · vram · models · max params · provider · location · discovery sources · last error |
| `/runs [n]`                        | last n scan runs (n ∈ [1, 20], default 5) — source, candidates, verified, new, finished, errors |
| `/catalog [svc] [q]`               | top model names by instance count across alive instances; optional service + substring         |
| `/alerts`                          | list standing alert rules (✓ enabled, ✗ disabled, with fired-count)                            |

### action commands

| command                            | does                                                                                          |
|------------------------------------|-----------------------------------------------------------------------------------------------|
| `/scan`                            | trigger one **shodan-only** scan via background executor                                       |
| `/recheck [n] [force] [alive]`     | trigger recheck. `force` clears `only_stale`, `alive` sets `only_alive`, int sets `limit`     |
| `/refresh <id>`                    | re-fingerprint one instance synchronously through `verify_for_service`; returns updated `/show` card |
| `/alert add <name> kind=<k> [filter_key=value ...]` | create a standing alert (kinds: new_instance, models_added, alive_changed) |
| `/alert edit <id> [name=<n>] [kind=<k>] [filter_key=value ...]` | partial update of an alert; `key=` (empty) removes a filter key |
| `/alert toggle <id>`               | flip an alert's enabled flag                                                                  |
| `/alert del <id>`                  | delete an alert                                                                                |
| `/scrape ...`                      | legacy cookie-auth shodan scraper (not part of multi-source pipeline)                          |

### push notifications (bot → user)

these arrive without you asking:

- **new alive instance found in a scan** — `new <service>: <ip>:<port>\nversion=<v> gpu=<g> via <sources>`
- **alert rule match** — `🔔 <alert name>` + service + gpu / vram / model count / max params + a per-kind extra line

---

## 4. feature parity — bot ↔ webui

legend: ✅ supported · 🟡 partial / has caveat · ❌ not supported · n/a not applicable

### read / browse

| capability                                                  | webui                          | bot                                                      | gap                                                              |
|-------------------------------------------------------------|--------------------------------|----------------------------------------------------------|------------------------------------------------------------------|
| list all instances                                          | ✅ paginated, sortable          | 🟡 only via `/find` or `/top`                            | bot has no general "list all" / pager                            |
| filter by service                                           | ✅ dropdown all 16              | 🟡 implicit via `/find`                                  | no `/list service=ollama`                                        |
| filter by gpu (substring)                                   | ✅ chip + select                | ✅ `/find gpu`                                            | —                                                                |
| filter by model (substring)                                 | ✅                              | ✅ `/find model`                                          | —                                                                |
| filter by country                                           | ✅ select                       | ✅ `/find country` (exact)                                | —                                                                |
| filter by provider / cloud type                             | ✅                              | ❌                                                        | no `/find provider=…`                                            |
| filter by min vram                                          | ✅ numeric input                | ❌                                                        | no `/find vram>24`                                               |
| filter by min max-params                                    | ✅ via alerts; not list page    | ❌                                                        | —                                                                |
| sort by vram / params / context / models / last_seen        | ✅ all                          | 🟡 `/top` only sorts by vram                              | no `/top params`, `/top context`                                 |
| ★ starred / watch list                                      | ✅ persisted in browser         | ❌                                                        | bot can't pin or watch a specific instance                       |
| named saved views                                           | ✅                              | ❌                                                        | no saved searches in bot                                         |
| csv export                                                  | ✅ filtered                     | ❌                                                        | —                                                                |
| count summary (total / alive / by service)                  | ✅ all 16                       | ✅ `/status` iterates Service enum                       | —                                                                |
| count "stale > 24h"                                         | ✅                              | ✅ `/status`                                              | —                                                                |
| count "new in 24h / 7d"                                     | ✅                              | ❌                                                        | —                                                                |
| view one instance's full metadata                           | ✅ kv card                      | ❌ no `/show <id>`                                        | bot has no "details" command                                     |
| view history (alive timeline / sparkline)                   | ✅                              | ❌                                                        | —                                                                |
| view change feed                                            | ✅ list per instance            | ✅ `/diff <id>`                                           | —                                                                |
| view raw shodan / service_metadata                          | ✅ `<details>` blocks           | ❌                                                        | —                                                                |
| model catalog (unique-models, counts)                       | ✅ `/models` page               | ❌ no `/catalog`                                          | bot can't enumerate fleet-wide models                            |
| scan run history                                            | ✅ `/runs` page                 | ❌ no `/runs`                                             | only `/status` mentions the most recent run                      |

### actions

| capability                                                  | webui                          | bot                                                      | gap                                                              |
|-------------------------------------------------------------|--------------------------------|----------------------------------------------------------|------------------------------------------------------------------|
| trigger shodan scan                                         | ✅                              | ✅ `/scan`                                                | —                                                                |
| trigger multi-source scan (shodan + netlas + …)             | ✅ `multi-scan` button          | ❌ `/scan` is shodan-only                                 | no `/scan all` or `/scan netlas`                                 |
| trigger recheck (with `only_stale` / `only_alive` / `limit`)| ✅                              | ✅ `/recheck [n] [force] [alive]`                          | —                                                                |
| refresh / re-fingerprint single instance                    | ✅ button (works for all 16 services) | ✅ `/refresh <id>` (synchronous, returns updated /show card) | —                                                              |
| auto-refresh (poll backend)                                 | ✅ 30s toggle                   | n/a (push model)                                         | —                                                                |

### alerts

| capability                                                  | webui                          | bot                                                      | gap                                                              |
|-------------------------------------------------------------|--------------------------------|----------------------------------------------------------|------------------------------------------------------------------|
| list alert rules                                            | ✅                              | ✅ `/alerts`                                              | —                                                                |
| create alert rule                                           | ✅ form offers all 16 services  | ✅ `/alert add <name> kind=… filter_key=value …`          | —                                                                |
| edit alert rule                                             | ✅                              | ✅ `/alert edit <id> …`                                   | —                                                                |
| delete alert rule                                           | ✅                              | ✅ `/alert del <id>`                                      | —                                                                |
| toggle alert enabled                                        | ✅ click badge                  | ✅ `/alert toggle <id>`                                   | —                                                                |
| **receive** alert notifications                             | ❌ no SSE/websocket             | ✅ telegram dm                                            | webui can't show "🔔 fired just now"                              |
| **receive** new-instance notifications                      | ❌                              | ✅                                                        | —                                                                |

### housekeeping

| capability                                                  | webui                          | bot                                                      | gap                                                              |
|-------------------------------------------------------------|--------------------------------|----------------------------------------------------------|------------------------------------------------------------------|
| keyboard shortcuts                                          | ✅                              | n/a                                                      | —                                                                |
| theme toggle (cream / dark)                                 | ✅                              | n/a                                                      | —                                                                |
| live activity feed (events as they happen)                  | ❌                              | 🟡 push-on-event but no scrollback                       | F2 from round-7 list — not built                                 |
| help / discoverability                                      | 🟡 `?` shortcut + tooltips     | ✅ `/help`                                                | webui doesn't list "things you can do" in one place              |

---

## 5. known asymmetries & footguns

these are the spots where the two surfaces lie to you, or where one diverges from the other in a way that has bitten before:

> **fixed in tier-1 pass (this session):**
> - ~~`/status` only counts comfyui + ollama~~ → `_cmd_status` now iterates the `Service` enum and shows total/alive per service for whichever ones have rows.
> - ~~alert form service-select hardcoded to comfyui/ollama~~ → form now offers all 16 services from a shared `SERVICES` constant in `AlertsPage.tsx`.
> - ~~`recheck._verify` and `main.refresh_instance` only route comfyui/ollama~~ → both call `fingerprints.verify_for_service(inst.service, …)` which dispatches to all 16 verify_* functions. the UI "↻ refresh" button now works for every service type.
> - TODO(review): after deploy, check for pre-fix phantom `ollama` rows on non-11434 ports and remove them if they have a sibling real service row.

still outstanding:

1. **bot `/scan` ≠ webui multi-scan.** `/scan` calls `run_shodan_scan` only. the webui's `multi-scan` button calls `run_multi_source_scan` (shodan + netlas + censys + zoomeye, deduped by `(ip, port)`). a user expecting "scan everything" from the bot is undercounting.
2. ~~`/find` doesn't accept compound filters~~ → fixed: `/find service=ollama vram>=24 country="United States"` etc.
3. **collision-port ambiguity in logs:** ports 8000 (triton/vllm) and 8080 (tgi/llamacpp/openwebui) cascade through multiple verifiers. once the right one wins, the row is correctly tagged — but if you grep "vllm" in the logs you'll also see "skipped triton" lines that look like errors.
4. **no telemetry on scan runs per source.** `ScanRun.source` is a string like `multi:shodan,netlas`, but there's no breakdown of "netlas returned 140, shodan returned 200, dedup left 287, junk_skipped 47." useful when one source goes silent (zoomeye 0 credits, censys 401) — currently you have to read the python logs.
5. **webui has no inbound channel.** the only push surface is telegram. someone watching `/instances` in a browser doesn't see "🔔 alert fired 3 seconds ago" or "new instance just discovered" — they have to refresh.

---

## 6. improvement opportunities (prioritised)

ranked by core-functionality impact, not effort.

### tier 1 — fixes the "the surfaces lie" problems ✅ done

1. ~~fix recheck/refresh routing for all missing services~~ → introduced `fingerprints.verify_for_service(service, base_url, client)`; `recheck._verify` and `main.refresh_instance` now both dispatch through it.
2. ~~make `/status` and the alert form iterate the Service enum~~ → `_cmd_status` reports per-service total/alive for everything in the db; `AlertsPage.tsx` form now offers all 16 services from a shared `SERVICES` constant.
3. **align `/scan` with the webui's multi-scan default.** ⏳ still outstanding. either rename to `/scan shodan` and add `/scan` (= multi) and `/scan netlas` etc., or point `/scan` at `run_multi_source_scan`. credits are real, so probably gate behind `/scan all` rather than auto-promoting.

### tier 2 — close the bot↔webui parity gaps that hurt most ✅ done

4. ~~`/show <id>` for the bot~~ → kv card mirrors webui detail page (service · ip:port · gpu / vram / models / max params / version / country / provider / last seen / discovery sources / last error).
5. ~~alert CRUD from the bot~~ → `/alert add <name> kind=… filter_key=value …`, `/alert edit <id> …`, `/alert toggle <id>`, `/alert del <id>`.
6. ~~`/refresh <id>` for the bot~~ → re-fingerprints synchronously through `verify_for_service`, returns updated `/show` card.
7. ~~multi-axis `/find`~~ → `/find service=ollama gpu=5090 vram>=24 country="United States"`; supports `=`, `>`, `>=`, `<`, `<=`. legacy `/find gpu rtx` still works.
8. ~~`/runs` and `/catalog` for the bot~~ → `/runs [n]` shows last n runs with cands/verified/new/errors; `/catalog [svc] [q]` shows top model names by instance count.

### tier 3 — webui live activity (closes the "no inbound" gap)

9. **SSE event stream + activity panel on `/`.** backend exposes `GET /api/events` (text/event-stream) emitting `new_instance`, `alert_fired`, `scan_started`, `scan_finished`. UI shows a small drawer with the last 50 events. this is the F2 round-7 item; it's the single most "alive-feeling" UX upgrade. ~half day for SSE + small panel.

### tier 4 — discovery breadth (more candidates → more reality)

10. **wire onyphe (free ~100/day) + leakix (different angle, misconfigs).** templates exist via `netlas_client.py`. each new source typically lifts the unique-instance count by 5-20 % and finds things shodan/netlas miss.
11. **plumb `tools/shodan_scraper.py` into `run_multi_source_scan`.** the cookie-auth scraper bypasses your 200/scan shodan-api budget. it already exists, just isn't called by the orchestrator.
12. **per-source telemetry on `ScanRun`.** add a `per_source: dict[str, {candidates, verified, new, error}]` json column. `/runs` page renders it; `/runs` bot command surfaces it. catches "censys is 401-ing again" without you tail-ing logs.

### tier 5 — polish

13. **per-service detail views.** instance detail currently has nice rendering for comfyui (grouped lists) and ollama (param/quant/context table). vllm, tgi, sglang, lmstudio, litellm have rich `/v1/models`-style payloads — currently shown as raw json. one shared "openai-compatible models table" component would cover most.
14. ~~honeypot / junk filter~~ → `fingerprints.classify_junk()` matches root-page responses against IIS dir listing, TOTVS, Zabbix, NF-validation, Google sign-in, IIS 404, WordPress, cPanel, Plesk. `_upsert_instance` refuses new junk inserts; existing rows that flip to junk get `last_error="junk:<sig>"`. on the first post-deploy multi-scan, all 219 candidates classified as junk → 0 polluting the catalog (vs. +79 dead rows pre-filter).
15. **ASN density chart.** B3 from round 7. pie or treemap of instance count by ASN/provider. great glance-able view to spot "huh, half of these are AS14618 (aws)."
16. **matchmaker page (B2).** "give me an ollama with llama-3.1-70b on 24GB+ in EU." essentially a saved-view preset surfaced as a quick-pick — kind of a UI for the alert filter set.
17. **per-service icon set** in the service badge (currently colour-only). minor, but helps at-a-glance scanning.

---

## 7. one-line recap

**the webui is the rich exploration surface; the bot is now at near-full parity for read/write flows (`/show`, `/refresh`, `/runs`, `/catalog`, multi-axis `/find`, full alert CRUD). the remaining gap is webui inbound (no SSE), bot `/scan` still being shodan-only, and per-source telemetry on `ScanRun` for "which source went silent" visibility.**
