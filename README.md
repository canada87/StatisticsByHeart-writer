# StatisticsByHeart — Writer

Servizio self-hosted che riceve i dati di Health Connect inviati dall'app Android **Reader** e li archivia
in PostgreSQL. Fase 1 (core): API di ingestione, schema DB, auth token, aggregati giornalieri, Docker.
La dashboard web (React) arriverà in una fase successiva; il suo posto è già previsto nel Dockerfile.

Documenti da leggere: [`docs/api-contract.md`](docs/api-contract.md) (contratto Reader→Writer, **fonte di
verità**), [`docs/openapi.json`](docs/openapi.json), [`docs/adr/`](docs/adr/) (decisioni), e
[`../PROJECT_GUIDE.md`](../PROJECT_GUIDE.md) (visione generale).

```
backend/    FastAPI + SQLAlchemy 2 + Alembic (app/, alembic/, tests/)
docker/     Dockerfile, compose.yml (produzione), compose.dev.yml, .env.example
docs/       api-contract.md, openapi.json, adr/
frontend/   (fase 4)
```

## Avvio in locale (sviluppo, dati SINTETICI)

Serve Docker. Dalla radice del repo:

```bash
docker compose -f docker/compose.dev.yml up --build
```

Parte Postgres 16 + l'API su <http://127.0.0.1:8000>, applica le migrazioni e carica 30 giorni di dati
**sintetici** (mai dati reali). Nei log trovi un token di ingest «dev»; l'admin è `admin` /
`dev-password-change-me`. Prova:

```bash
curl http://127.0.0.1:8000/api/v1/health
curl -H "Authorization: Bearer <token-dai-log>" http://127.0.0.1:8000/api/v1/ping
```

Il codice in `backend/app` è montato con `--reload`. Per ripartire da zero: `docker compose -f docker/compose.dev.yml down -v`.

### Test, lint, tipi

```bash
cd backend
uv sync                      # Python 3.12 + dipendenze
uv run pytest                # Postgres 16 reale via testcontainers (serve Docker acceso)
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

Per usare un Postgres già esistente invece di testcontainers: `SBH_TEST_DATABASE_URL=postgresql+psycopg://…` (verrà
migrato e **svuotato** a ogni test: usa un DB usa-e-getta).

Se cambi payload/endpoint: `uv run python -m app.cli export-openapi ../docs/openapi.json`, aggiorna
`docs/api-contract.md` **e il suo changelog** (un test blocca il merge se OpenAPI è obsoleto o se il contratto non
cita un tipo/campo del registro) e avvisa chi sviluppa il Reader.

CLI operativa (`python -m app.cli …`): `create-admin`, `create-token --name …`, `seed`, `recompute`, `export-openapi`.

## Build dell'immagine (comando esatto)

Dalla **radice del repo** (il contesto di build è la radice; il Dockerfile sta in `docker/`):

```bash
docker build -f docker/Dockerfile -t statisticsbyheart-writer:0.1.0 .
```

Il tag è versionato (cambialo ad ogni rilascio: `0.1.1`, …) così si può tornare indietro; `compose.yml` usa
`image: statisticsbyheart-writer:${SBH_IMAGE_TAG:-0.1.0}` e **non** ha `build:`.

## Deploy sulla VM `docker2404-real` (manuale, da Portainer)

### 0. Controlli prima di cominciare (sulla VM)

```bash
free -h                                   # RAM libera (vedi stima sotto)
docker ps --format '{{.Names}}\t{{.Ports}}' | grep -E '8742|:8742->'   # nessun output = 8742 libera
ls -la /mnt/StatisticsByHeart             # solo se userai il backup: deve esistere ed essere montata
```

Se `8742` è occupata scegline un'altra e usa quella ovunque sotto. Se `/mnt/StatisticsByHeart` non esiste, **non
crearla a mano**: crea/monta prima la share SMB (guarda `uid`, `gid`, `file_mode`, `dir_mode` delle opzioni di
mount) oppure lascia il backup disattivato. Prima del **primo deploy e di ogni upgrade con migrazioni** fai uno
snapshot/backup manuale da PBS.

### 1. Aggiorna il codice e builda l'immagine

```bash
cd <cartella-del-clone>/StatisticsByHeart-writer     # il percorso del clone lo scegli tu
git pull
docker build -f docker/Dockerfile -t statisticsbyheart-writer:0.1.0 .
```

### 2. Crea la cartella del DB (disco locale della VM)

```bash
mkdir -p /home/docker2404/StatisticsByHeart/db
```

(Postgres sistema da solo i permessi al primo avvio. **Mai** mettere il DB su `/mnt/…`/SMB.)

### 3. Stack in Portainer

*Stacks → Add stack* → **Web editor** → incolla il contenuto di `docker/compose.yml` → nome stack a piacere
(es. `statisticsbyheart`). In *Environment variables* inserisci (vedi `docker/.env.example`, puoi anche usare
«Load variables from .env file»):

| Variabile | Valore |
|---|---|
| `SBH_DB_PASSWORD` | **obbligatoria**, es. output di `openssl rand -hex 24` |
| `SBH_IMAGE_TAG` | `0.1.0` (il tag che hai buildato) |
| `SBH_HTTP_PORT` | `8742` (o quella libera che hai scelto) |
| `SBH_SOURCE_PRIORITY` | opzionale: pacchetti Android in ordine di fiducia, es. `pkg.fit,pkg.withings` (i nomi esatti li mostra l'inventario del Reader) |
| `COMPOSE_PROFILES` | `backup` **solo** se vuoi il dump notturno su NAS (richiede `/mnt/StatisticsByHeart` montata) |

*Deploy the stack*. All'avvio il container applica le migrazioni (`alembic upgrade head`). Verifica:

```bash
curl http://127.0.0.1:8742/api/v1/health        # {"status":"ok"}
```

### 4. Primo utente admin e token per il Reader

Trova il container (con Portainer il nome dipende dal nome dello stack) e usa la CLI:

```bash
docker ps --filter name=sbh-api --format '{{.Names}}'
docker exec -it <nome-container-sbh-api> python -m app.cli create-admin          # chiede la password (≥12 caratteri)
docker exec -it <nome-container-sbh-api> python -m app.cli create-token --name "Xiaomi 14T Pro"
```

`create-token` stampa il token **una sola volta** (`sbh_…`): copialo nel campo Token del Reader (il server ne
conserva solo l'hash). I token si possono anche creare/revocare via API da admin loggato
(`POST/GET/DELETE /api/v1/admin/tokens`, vedi `docs/openapi.json`); la UI web arriverà con la dashboard.

### 5. Nginx Proxy Manager (lo fai tu: io non ho accesso)

*Hosts → Proxy Hosts → Add Proxy Host*:

| Campo | Valore |
|---|---|
| Domain Names | `sbh.local.smarthomeformyhouse.loan` |
| Scheme | `http` |
| Forward Hostname / IP | `100.84.182.8` |
| Forward Port | `8742` (la `SBH_HTTP_PORT` scelta) |
| Cache Assets | off |
| Block Common Exploits | on (facoltativo) |
| Websockets Support | **off** (non servono) |
| Access List | *Publicly Accessible* (la protezione reale è Tailscale + token/login) |

Tab **SSL**: scegli il certificato valido che usi per gli altri `*.local.smarthomeformyhouse.loan`, **Force SSL** on,
HTTP/2 on.

Tab **Advanced** → *Custom Nginx Configuration* (⚠️ importante: di default nginx rifiuta body > 1 MB e i batch di
backfill possono pesare qualche MB anche compressi):

```nginx
client_max_body_size 40m;
proxy_read_timeout 120s;
proxy_send_timeout 120s;
```

Verifica da un dispositivo sulla tailnet: `curl https://sbh.local.smarthomeformyhouse.loan/api/v1/health`.
Il Reader usa l'URL `https://sbh.local.smarthomeformyhouse.loan` (nessuna eccezione cleartext).

### Aggiornare / tornare indietro

1. `git pull`, `docker build … -t statisticsbyheart-writer:0.1.1 .` (nuovo tag), snapshot PBS se ci sono migrazioni.
2. In Portainer cambia `SBH_IMAGE_TAG=0.1.1` → *Update the stack*.
3. Rollback del codice: rimetti il tag precedente. Le migrazioni sono solo «in avanti»: se una migrazione va
   annullata, ripristina il backup (PBS o dump) invece di fare `downgrade`.

### Backup e ripristino

Con `COMPOSE_PROFILES=backup`, `sbh-backup` scrive ogni notte alle 03:00 (Europe/Rome) `sbh_AAAAMMGG_hhmmss.dump`
(formato custom di `pg_dump`) in `/mnt/StatisticsByHeart`, tenendo 14 giorni (`SBH_BACKUP_KEEP_DAYS`). Permessi
file `600`. I dump contengono dati sanitari: tieni la cartella NAS ad accesso ristretto. Dump manuale:

```bash
docker exec <nome-container-sbh-backup> sh -c 'pg_dump -Fc -f /backups/manuale.dump'
```

Ripristino (su stack fermo l'API, DB attivo): `pg_restore --clean --if-exists --no-owner -d sbh /backups/<file>.dump`
eseguito nel container `sbh-backup` o `sbh-db`.

## Impatto sulle risorse (stima)

Misurato in locale con dati sintetici a riposo: **API ~60–100 MB**, **Postgres ~20–65 MB** (cresce con la cache
fino al tetto), **backup ~1 MB** (dorme). Stima in esercizio: **~250–400 MB totali**, con limiti rigidi nel compose
(`mem_limit` 384 + 384 + 128 MB). Disco: ~0,5 MB per giorno di dati sintetici ricchi (30 giorni ≈ 15 MB); anche con
molti campioni reali di frequenza cardiaca restano ben sotto 1 GB/anno. Prima di deployare controlla `free -h`
sulla VM (10 GiB totali, ~24 container già presenti). CPU trascurabile (un worker, ingest a raffiche).

## Sicurezza in breve

Nessun servizio esterno/CDN/telemetria; token e sessioni salvati solo come hash; password Argon2id; cookie
`HttpOnly; Secure; SameSite=Lax`; rate limit sul login; nessun valore sanitario nei log o negli errori; DB solo
su rete interna; container non‑root con filesystem in sola lettura. Esposizione prevista: solo LAN + Tailscale,
mai Internet pubblico. Dettagli in [`docs/adr/0003-auth-sessions-and-operations.md`](docs/adr/0003-auth-sessions-and-operations.md).
