# openports backend

FastAPI backend that:
- imports candidates from Shodan (instead of doing internet-wide port scanning)
- verifies/fingerprints ComfyUI (8188) + Ollama (11434)
- stores results in SQLite
- exposes an API for the React dashboard
- optionally sends Telegram notifications for newly discovered instances

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp ../.env.example .env
# edit .env with your keys

# optional helper: print your TELEGRAM_CHAT_ID candidates
export TELEGRAM_BOT_TOKEN='...'
python3 tools/get_telegram_chat_id.py

uvicorn app.main:app --reload --port 8000
```

## Notes
- To protect `/api/scan/shodan`, set `ADMIN_TOKEN` and send `Authorization: Bearer <token>`.
- Ollama does not reliably expose GPU details via its HTTP API.
