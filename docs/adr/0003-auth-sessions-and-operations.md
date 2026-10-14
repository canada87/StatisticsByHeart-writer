# ADR 0003 — Autenticazione, sessioni e scelte operative

Stato: accettato · 2026-10-14

## Decisioni

1. **Token di ingest**: `sbh_` + 32 byte casuali (urlsafe). Il DB conserva solo SHA‑256 (hex). Per segreti a 256
   bit uno hash veloce è corretto (Argon2 serve per password umane). Revoca = `revoked_at`; risposte distinte
   `invalid_token` / `token_revoked` per dare al Reader un messaggio chiaro. `last_used_at` aggiornato al più
   una volta al minuto.
2. **Admin unico nel DB (`admin_user`)**, non nelle variabili d'ambiente: un hash Argon2id contiene `$` che
   `docker compose`/Portainer tentano di interpolare, e il DB permette di cambiare password senza ridistribuire.
   Creazione/reset via CLI: `python -m app.cli create-admin` (prompt, o `SBH_ADMIN_PASSWORD` per un solo uso).
   Argon2id con i default di `argon2-cffi`; rehash trasparente al login se i parametri cambiano.
3. **Sessione web**: cookie casuale (`HttpOnly; Secure; SameSite=Lax`), solo l'hash è salvato in `user_session`
   (TTL 7 giorni, revocabile). `Secure` configurabile (`SBH_COOKIE_SECURE`) per sviluppo su http.
4. **CSRF**: oltre a `SameSite=Lax`, le richieste che modificano stato autenticate da cookie richiedono l'header
   custom `X-SBH-Client` (un form cross-site non può impostarlo senza preflight CORS, che non abilitiamo).
5. **Rate limiting del login**: in memoria, 5 fallimenti / 15 min per IP **e** per username (singolo utente: un
   attaccante può bloccare il proprietario per 15 minuti, accettato; non può indovinare). Verifica password a
   tempo costante anche per utente inesistente. Richiede **un solo worker** uvicorn (anche per lo scheduler
   APScheduler): scelta voluta per un carico personale.
6. **Nessun valore sanitario nei log** né nelle risposte d'errore: gli errori di validazione per record
   riportano percorso e messaggio, mai l'input; il 422 della busta è riscritto senza `input`.
7. **Body guard** (ASGI): gzip accettato, limite 32 MiB *dopo* la decompressione (protezione da gzip bomb),
   `Content-Encoding` diverso da gzip → 415.
8. **Scritture di ingest serializzate** con `pg_advisory_xact_lock`: il ricalcolo di `daily_metric` è
   read‑modify‑write e i volumi sono irrisori; niente race.
9. **Migrazioni all'avvio** del container (`SBH_RUN_MIGRATIONS=true`): comodo per il flusso Portainer. Prima di un
   upgrade che include migrazioni, snapshot PBS (PROJECT_GUIDE §4). Disattivabile.
10. **Documentazione API**: `/api/openapi.json` solo per admin loggato. La UI Swagger/ReDoc standard carica
    asset da CDN, vietati dalla guida (§7): non è abilitata finché non verranno serviti in locale.
11. **Container**: utente non‑root (uid 10001), filesystem in sola lettura, `cap_drop: ALL`,
    `no-new-privileges`, limiti di memoria. DB senza porte sull'host, su rete `internal`.
