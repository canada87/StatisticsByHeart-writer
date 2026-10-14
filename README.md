# StatisticsByHeart — Writer

Servizio self-hosted che riceve i dati di Health Connect inviati dall'app Android **Reader**, li archivia in
PostgreSQL e li mostra in una dashboard web in stile HUD. Un solo container (FastAPI + SPA React) più un
Postgres dedicato.

Documenti: [`docs/api-contract.md`](docs/api-contract.md) (contratto Reader→Writer, **fonte di verità**),
[`docs/openapi.json`](docs/openapi.json), [`docs/adr/`](docs/adr/) (decisioni),
[`design-system/`](design-system/statisticsbyheart-writer/MASTER.md) (design system della dashboard),
[`docs/screenshots/`](docs/screenshots/) (schermate, **solo dati sintetici**).

```
backend/         FastAPI + SQLAlchemy 2 + Alembic (app/, alembic/, tests/)
frontend/        React 19 + Vite + TypeScript + Tailwind v4 (src/, e2e/)
docker/          Dockerfile multi-stage, compose.yml (produzione), compose.dev.yml, .env.example
docs/            api-contract.md, openapi.json, adr/, screenshots/
design-system/   MASTER.md + override per pagina
.github/         workflow CI e Release (immagine su GHCR)
```

## Avvio in locale (sviluppo, dati SINTETICI)

Serve Docker. Dalla radice del repo:

```bash
docker compose -f docker/compose.dev.yml up --build
```

Costruisce l'immagine (SPA inclusa), parte Postgres 16 + l'app su <http://127.0.0.1:8000>, applica le migrazioni e
carica 30 giorni di dati **sintetici** (mai dati reali). Login dashboard: `admin` / `dev-password-change-me`.
Nei log trovi anche un token di ingest «dev» per provare l'API del Reader:

```bash
curl http://127.0.0.1:8000/api/v1/health
curl -H "Authorization: Bearer <token-dai-log>" http://127.0.0.1:8000/api/v1/ping
```

Il codice di `backend/app` è montato con `--reload`. Ripartire da zero: `docker compose -f docker/compose.dev.yml down -v`.

### Sviluppo del frontend (hot reload)

Con lo stack dev acceso, in un altro terminale:

```bash
cd frontend
npm ci
npm run dev          # http://localhost:5173, proxy /api -> 127.0.0.1:8000
```

### Test, lint, tipi

```bash
# backend (serve Docker: Postgres 16 reale via testcontainers)
cd backend
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy

# frontend
cd frontend
npm run typecheck
npm test             # Vitest + Testing Library (contrasti dei token, range, login, pagine, stati)
npm run test:e2e     # Playwright contro lo stack dev: smoke, axe (a11y), screenshot 375/768/1024/1440
```

I test e2e richiedono lo stack dev in esecuzione e `npx playwright install chromium` la prima volta. Gli screenshot
finiscono in `docs/screenshots/`: usare **solo** lo stack dev (dati sintetici), mai un server con dati reali.

Se cambi payload/endpoint: `uv run python -m app.cli export-openapi ../docs/openapi.json`, aggiorna
`docs/api-contract.md` **e il suo changelog** (un test blocca il merge se OpenAPI è obsoleto o se il contratto non
cita un tipo/campo del registro) e avvisa chi sviluppa il Reader.

CLI operativa (`python -m app.cli …`): `create-admin`, `create-token --name …`, `seed`, `recompute`, `export-openapi`.

## Immagine Docker: pubblicazione automatica su GHCR

L'immagine **non si builda sulla VM**: la costruisce GitHub Actions e Portainer la scarica.

| Workflow | Quando | Cosa fa |
|---|---|---|
| `CI` (`.github/workflows/ci.yml`) | push su `main`, pull request | backend (ruff, mypy, pytest) · frontend (typecheck, Vitest, build) · verifica che l'immagine si costruisca |
| `Release` (`.github/workflows/release.yml`) | tag `vX.Y.Z` | rilancia i test, costruisce l'immagine multi-stage e la pubblica su `ghcr.io/canada87/statisticsbyheart-writer` con i tag `X.Y.Z` e `latest` (usa `GITHUB_TOKEN`, permesso `packages: write`) |

Per rilasciare (dal tuo PC):

```bash
git tag v0.2.0
git push origin main v0.2.0
```

### Una tantum: rendere pubblico il pacchetto

Al **primo** publish il pacchetto su GHCR nasce **privato**, anche se il repo è pubblico. Va reso pubblico una sola
volta, così la VM può fare il pull senza credenziali: GitHub → il tuo profilo → **Packages** →
`statisticsbyheart-writer` → **Package settings** → *Danger Zone* → **Change visibility** → *Public*.
(In alternativa lasciarlo privato e configurare in Portainer un registro `ghcr.io` con un token `read:packages`.)

Build locale per prove (facoltativa, dalla radice del repo):

```bash
docker build -f docker/Dockerfile -t statisticsbyheart-writer:dev .
```

## Deploy sulla VM Docker (da Portainer)

### 0. Controlli prima di cominciare (sulla VM)

```bash
free -h                                              # RAM libera (vedi stima sotto)
docker ps --format '{{.Names}}\t{{.Ports}}' | grep 8742   # nessun output = porta 8742 libera
```

Se `8742` è occupata scegline un'altra e usala ovunque sotto. Prima del **primo deploy** e di ogni **upgrade con
migrazioni** fai uno snapshot/backup manuale da PBS e, se vuoi, un dump (vedi «Backup»).

### 1. Crea la cartella del DB (disco locale della VM)

```bash
mkdir -p <SBH_DATA_DIR>/db      # SBH_DATA_DIR: vedi docker/.env.example (default nel compose)
```

(Postgres sistema da solo i permessi al primo avvio. **Mai** mettere il DB su SMB/NAS.)

### 2. Stack in Portainer

*Stacks → Add stack* → **Web editor** → incolla `docker/compose.yml` → nome stack a piacere. In *Environment
variables* (vedi `docker/.env.example`; puoi usare «Load variables from .env file»):

| Variabile | Valore |
|---|---|
| `SBH_DB_PASSWORD` | **obbligatoria**, es. output di `openssl rand -hex 24` |
| `SBH_IMAGE_TAG` | `0.2.0` (la versione da usare) oppure `latest` |
| `SBH_HTTP_PORT` | `8742` (o quella libera che hai scelto) |
| `SBH_DATA_DIR` | cartella locale della VM che contiene `db/` (default nel compose) |
| `SBH_SOURCE_PRIORITY` | opzionale: pacchetti Android in ordine di fiducia (i nomi esatti li mostra la pagina *Sync / Dati → Inventario*) |

*Deploy the stack*. Portainer scarica `ghcr.io/canada87/statisticsbyheart-writer:<tag>` e all'avvio il container applica
le migrazioni. Verifica: `curl http://127.0.0.1:8742/api/v1/health` → `{"status":"ok"}`.

### 3. Primo utente admin e token per il Reader

```bash
docker ps --filter name=sbh-api --format '{{.Names}}'
docker exec -it <nome-container-sbh-api> python -m app.cli create-admin        # chiede la password (≥12 caratteri)
docker exec -it <nome-container-sbh-api> python -m app.cli create-token --name "Telefono"
```

`create-token` stampa il token **una sola volta** (`sbh_…`): va nel campo Token del Reader (il server conserva solo
l'hash). La dashboard è su `https://<dominio>/` (login con l'admin creato sopra).

### 4. Nginx Proxy Manager (lo configuri tu)

*Hosts → Proxy Hosts → Add Proxy Host*:

| Campo | Valore |
|---|---|
| Domain Names | `<il-tuo-dominio>` (es. `sbh.<tuo-dominio-locale>`) |
| Scheme | `http` |
| Forward Hostname / IP | `<IP della VM raggiungibile da NPM, p.es. l'IP Tailscale>` |
| Forward Port | `8742` (la `SBH_HTTP_PORT` scelta) |
| Cache Assets | off |
| Block Common Exploits | on (facoltativo) |
| Websockets Support | **off** (non servono) |
| Access List | *Publicly Accessible* (la protezione reale è Tailscale + login/token) |

Tab **SSL**: certificato valido per quel dominio, **Force SSL** on, HTTP/2 on.

Tab **Advanced** → *Custom Nginx Configuration* (⚠️ importante: di default nginx rifiuta body > 1 MB e i batch di
backfill possono pesare qualche MB anche compressi):

```nginx
client_max_body_size 40m;
proxy_read_timeout 120s;
proxy_send_timeout 120s;
```

Verifica da un dispositivo sulla tailnet: `curl https://<il-tuo-dominio>/api/v1/health`. Il Reader usa
`https://<il-tuo-dominio>` (nessuna eccezione cleartext).

### Aggiornare e tornare indietro

1. Rilascia un nuovo tag (`git tag v0.2.1 && git push origin v0.2.1`) e attendi che il workflow *Release* finisca.
2. Prima di un upgrade con migrazioni: snapshot PBS (e dump, vedi sotto).
3. In Portainer cambia `SBH_IMAGE_TAG=0.2.1` → **Update the stack** con *Re-pull image* attivo. Se usi `latest`:
   *Update the stack* con **Pull latest image**.
4. **Rollback**: rimetti il tag precedente (`SBH_IMAGE_TAG=0.2.0`) e aggiorna lo stack. Le migrazioni sono solo «in
   avanti»: se una migrazione va annullata ripristina lo snapshot PBS (o il dump) invece di fare `downgrade`.

### Backup

Il DB sta sul disco locale della VM ed è coperto dai backup PBS della VM. I dati inoltre si possono ricostruire con un
nuovo backfill dal telefono. Prima di un upgrade con migrazioni è comunque prudente un dump manuale (sulla VM):

```bash
docker exec <nome-container-sbh-db> pg_dump -U sbh -Fc sbh > ~/sbh_$(date +%Y%m%d_%H%M).dump
```

Ripristino (su DB vuoto o con `--clean`): `docker exec -i <nome-container-sbh-db> pg_restore -U sbh -d sbh --clean --if-exists --no-owner < file.dump`.
Il dump contiene dati sanitari: conservalo in una cartella a permessi ristretti e non committarlo.

## Impatto sulle risorse (stima)

Misurato in locale con dati sintetici a riposo: **API ~60–100 MB**, **Postgres ~20–65 MB** (cresce con la cache fino
al tetto). Stima in esercizio: **~200–350 MB totali**, con limiti rigidi nel compose (`mem_limit` 384 + 384 MB). La SPA
è servita dallo stesso processo: nessun container in più. Disco: ~0,5 MB per giorno di dati sintetici ricchi; anche
con molti campioni reali di frequenza cardiaca restano ben sotto 1 GB/anno. Prima di deployare controlla `free -h`
sulla VM.

## Sicurezza in breve

Nessun servizio esterno/CDN/telemetria (font e librerie self-hosted, CSP restrittiva); token e sessioni salvati solo
come hash; password Argon2id; cookie `HttpOnly; Secure; SameSite=Lax` + header anti-CSRF; rate limit sul login;
nessun valore sanitario nei log o negli errori; DB solo su rete interna; container non-root con filesystem in sola
lettura. Esposizione prevista: solo LAN + Tailscale, mai Internet pubblico. Dettagli in
[`docs/adr/0003-auth-sessions-and-operations.md`](docs/adr/0003-auth-sessions-and-operations.md).

> **Repo pubblico:** nei file versionati non ci sono più IP, domini o segreti personali, ma restano nella
> **cronologia git** dei commit precedenti. Se vanno considerati riservati serve riscrivere la storia (o ricreare il repo).
