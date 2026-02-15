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

## Current state
- Old prototype scripts are in `legacy/`.
- New implementation TBD.

## Environment
Create a `.env` (not committed) based on `.env.example`.
