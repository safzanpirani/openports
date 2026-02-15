# Deployment notes

## Docker (simple)

```bash
# from repo root
cp .env.example .env
# fill SHODAN_API_KEY, TELEGRAM_* and optionally ADMIN_TOKEN

docker compose up --build
```

- Frontend: http://localhost:8080
- Backend: http://localhost:8000

The frontend reverse-proxies `/api/*` to the backend.
