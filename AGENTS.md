# AGENTS.md

this file is the handoff doc for any agent setting up openports on a server.

## what this repo is

openports tracks publicly exposed comfyui (`8188`) and ollama (`11434`) instances.

it has:
- `backend/` — fastapi api + scanning/fingerprinting + sqlite
- `frontend/` — vite/react dashboard
- `docker-compose.yml` — easiest deployment path
- `deploy/nginx.conf` — frontend container nginx config

## preferred way to move it to a server

use git, not zip.

this repo already exists on github, so the clean path is:
1. push code changes from the dev machine
2. clone or pull on the server
3. run `docker compose up -d --build`

only use a zip if git access is impossible.

## deployment goal

after setup:
- frontend should be reachable on `http://SERVER_IP:8080`
- backend api should be reachable on `http://SERVER_IP:8000`
- frontend should proxy `/api/*` to backend automatically
- sqlite data should persist across restarts

## important gotchas

1. docker deployment uses repo-root `./data/openports.db`
   - this is important
   - local dev may have used `backend/data/openports.db`
   - if you want to preserve old scan history, copy the old db into `./data/openports.db` on the server before first boot

2. for docker deployment, use repo-root `.env`
   - do not rely on `backend/.env`
   - compose reads `./.env`

3. do not commit secrets or db files
   - `.env`
   - `backend/.env`
   - `*.db`

4. this project is meant to use third-party indexes / authorized sources for discovery, then verify targets itself
   - do not add raw internet-wide scanning from the server unless explicitly asked and authorized

## exact server setup steps

### option a: fresh server setup (recommended)

run these commands on the server:

```bash
mkdir -p /opt
cd /opt

# clone the repo
# replace with ssh remote if that is what the server uses
git clone https://github.com/safzanpirani/openports.git
cd openports

# create runtime env file
cp .env.example .env
```

then edit `.env` and fill the values you actually want.

minimum useful env:
- `SHODAN_API_KEY=` if scans will use shodan

optional env:
- `TELEGRAM_BOT_TOKEN=`
- `TELEGRAM_CHAT_ID=`
- `ADMIN_TOKEN=` to protect scan-trigger endpoints
- `CENSYS_*`, `ZOOMEYE_*`, cookies, etc if those providers are needed

then start it:

```bash
mkdir -p data
docker compose up -d --build
```

verify it:

```bash
curl http://127.0.0.1:8000/api/instances
curl -I http://127.0.0.1:8080
```

expected result:
- backend returns json or `[]`
- frontend returns `200 OK`

### option b: preserve existing sqlite history from the dev machine

if the old machine has data at:
- `backend/data/openports.db`

then on the source machine, copy it to the server as:
- `/opt/openports/data/openports.db`

example shape:

```bash
# run from the source/dev machine
scp backend/data/openports.db USER@SERVER_IP:/opt/openports/data/openports.db
```

after the db is in place, start or restart:

```bash
cd /opt/openports
docker compose up -d --build
```

## day-2 operations

### update the app

```bash
cd /opt/openports
git pull --ff-only
docker compose up -d --build
```

### view logs

```bash
cd /opt/openports
docker compose logs -f backend
docker compose logs -f frontend
```

### restart services

```bash
cd /opt/openports
docker compose restart
```

### stop services

```bash
cd /opt/openports
docker compose down
```

## how the app is wired

- backend container:
  - serves fastapi on port `8000`
- frontend container:
  - serves built static assets on port `80` inside container
  - exposed as host port `8080`
  - proxies `/api/*` to backend using `deploy/nginx.conf`
- persistent sqlite storage:
  - host path: `./data`
  - container path: `/app/data`

## quick health checklist

after deployment, confirm all of these:

- `docker compose ps` shows both `backend` and `frontend` running
- `curl http://127.0.0.1:8000/api/instances` works
- opening `http://SERVER_IP:8080` loads the dashboard
- opening browser devtools on the dashboard shows `/api/*` requests succeeding
- `data/openports.db` exists on disk if persistence is expected

## if something breaks

### frontend loads but api calls fail
check:
- backend container is up
- port `8000` is listening
- frontend nginx proxy config is present at `deploy/nginx.conf`
- browser requests are going to `/api/...`, not `localhost`

### backend starts but data is missing
check:
- whether you expected old data from `backend/data/openports.db`
- whether that file was copied to `data/openports.db` on the server
- whether docker created a fresh empty db because `data/` was empty

### compose build fails
check:
- docker and docker compose plugin are installed
- server has outbound internet for pip/npm package installs
- repo was cloned completely

## fallback path if docker is not available

only use this if docker is unavailable.

backend:

```bash
cd /opt/openports/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

frontend:

```bash
cd /opt/openports/frontend
npm install
npm run build
```

then serve `frontend/dist/` with nginx and proxy `/api/` to `http://127.0.0.1:8000`.

docker is still the preferred path.

## agent policy for this repo

if you are an agent operating on this repo:
- prefer small, explicit changes
- do not commit secrets
- do not commit `.env` or db files
- if changing deployment behavior, update this file too
- if you need to preserve existing scan history, ask whether the old sqlite db should be copied before first boot
