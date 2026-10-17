# ADR 0010 — Preferenze sul server, PDF pulito, allarme «sync ferma» per Home Assistant

Stato: accettato · 2026-10-18 · **Migrazione `0004`** (tabella `user_preference`, colonna `ingest_token.scope`)

## Contesto

Tre richieste: scegliere cosa mostra il Report (a schermo e nel PDF) e ritrovare la scelta da qualsiasi dispositivo;
ottenere un PDF senza l'intestazione e il piè di pagina del browser (titolo, indirizzo, data); avere in Home Assistant
(HA) un allarme quando la sincronizzazione dal telefono si ferma.

## Decisioni

### 1. Preferenze salvate sul server (non nel browser)

- Tabella generica `user_preference(key varchar(64) pk, value jsonb, updated_at)`: il writer **non interpreta** il valore.
  Una sola persona usa la dashboard, quindi nessuna colonna utente: le preferenze sono del writer, come l'admin.
- API (solo dashboard, fuori contratto Reader): `GET/PUT/DELETE /api/v1/preferences/{key}`. Richiedono la sessione admin;
  `PUT` e `DELETE` anche l'header `X-SBH-Client` (stessa protezione CSRF dell'override degli allenamenti). `GET` di una
  chiave mai salvata risponde `200` con `value: null`. Limiti: chiave `[a-z0-9][a-z0-9_.-]{0,63}`, valore ≤ 16 KiB, ≤ 100
  chiavi (`422` oltre). Il `PUT` **sostituisce** il valore.
- «Ripristina predefiniti» = `DELETE` della chiave (non un valore speciale).
- Chiave `report-sections`: mappa `{ "<id>": true|false }`. **Un id assente vale «acceso»**: una sezione nuova, aggiunta da
  una versione futura, compare da sola; un id sconosciuto (scelta salvata da una versione più nuova) è ignorato dalla
  pagina e **conservato** quando si salva di nuovo; un valore non booleano è scartato. Se la preferenza non si può
  leggere (errore di rete, 404) il report si mostra **completo**: una preferenza mancante non deve mai nascondere dati.
- Sezioni: Riepilogo, Mese su mese, Allenamenti, Grafici; misure: Passi, Distanza, Calorie (attive e totali), FC, FC
  diurna e notturna, FC a riposo, HRV, SpO₂, Sonno, Peso, Pressione, Punti cardio. Una **misura** si spegne dappertutto:
  riga del riepilogo, colonna dei mesi, grafico, e il blocco Sonno / Punti cardio. Gli id sono in
  `frontend/src/lib/reportSections.ts`.
- **I CSV restano sempre completi.** Sono per l'elaborazione, non per la lettura: una scelta di presentazione non deve
  farli mancare di colonne senza che l'utente se ne accorga. Il pannello lo dice.
- Una sezione spenta **non viene montata**: sparisce dallo schermo e dalla stampa, e non costa chiamate (i grafici
  spenti non interrogano il server).

### 2. PDF senza intestazioni del browser

Il browser stampa titolo, URL e data nei **margini della pagina**. Con `@page { margin: 0 }` non c'è margine in cui
disegnarli (verificato su Chromium con `displayHeaderFooter: true`: nel PDF non compaiono né l'indirizzo né `localhost`).
I margini veri sono **padding del contenuto** (`main`, 14 mm; `box-decoration-break: clone` li ripete su ogni pagina: il
testo della pagina 2 parte a ~14 mm dal bordo) e il report disegna un **piè di pagina proprio** a posizione fissa
(ripetuto a ogni pagina): titolo, periodo e data di generazione, **senza URL**. Nelle impostazioni di stampa di Chrome,
«Altre impostazioni › Intestazioni e piè di pagina» può restare com'è: con margine 0 non producono nulla (README).

### 3. Allarme per Home Assistant: il writer viene interrogato (polling)

- **Perché polling e non push.** HA ha già i sensori REST e le automazioni; il writer non deve conoscere l'indirizzo di HA
  né tenere un segreto per chiamarlo, e un'uscita HTTP verso la LAN dal container sarebbe una superficie in più. Con il
  polling l'allarme scatta **anche se il writer è spento o irraggiungibile** (il sensore diventa `unavailable`), che è
  il caso che più interessa.
- **Token dedicato con scope.** Colonna `ingest_token.scope` (`'ingest'` per default — i token esistenti restano tali —
  oppure `'ha'`, con `CHECK`) invece di una tabella a parte: stessa gestione (hash SHA-256, revoca, elenco in
  amministrazione), una sola colonna. Creazione: `python -m app.cli create-token --name "Home Assistant" --scope ha`.
  **Separazione in entrambe le direzioni:** un token `ha` sull'ingest e su `/ping` risponde `403 wrong_token_scope`; un
  token `ingest` su `/api/v1/ha/status` risponde `403 wrong_token_scope`. Il token HA è di sola lettura e non vede dati
  sanitari.
- **`GET /api/v1/ha/status`** (Bearer, scope `ha`). Risposta minima, senza alcun valore sanitario: `status`
  (`ok` | `stale` | `never`), `last_sync_at`, `last_ingest_at`, `hours_since_sync`, `threshold_hours`, `version`.
  - `last_sync_at` = ultima sync **riuscita** (`sync_run.status` in `completed`, `partial`) tra **tutti** i dispositivi,
    alla `finished_at`. Una sync `failed` o ancora `running` non la aggiorna.
  - `last_ingest_at` = ultima attività del telefono qualunque esito (anche una sync fallita o in corso): serve a capire
    se il telefono è vivo ma fallisce, oppure è muto.
  - `stale` quando `hours_since_sync` **>** soglia (esattamente 6 h è ancora `ok`); `never` se non c'è alcuna sync
    riuscita. Soglia = `SBH_STALE_HOURS` (default 6, numero decimale accettato).
  - **Più dispositivi:** l'allarme guarda l'ultima sync riuscita di **qualsiasi** dispositivo, quindi un vecchio telefono
    fermo non fa scattare nulla finché un altro sincronizza. La scheda Sync mostra comunque l'ultima sync riuscita di
    ciascuno.
- **Rate limit leggero:** 30 richieste al minuto per token (finestra scorrevole in memoria, come il limite del login);
  oltre `429` con `Retry-After`. Basta e avanza per un polling ogni pochi minuti. Il contatore si azzera al riavvio.
- La dashboard (scheda Sync) mostra lo **stesso** stato (`alarm` aggiunto in modo additivo a `GET /api/v1/sync/status`,
  più `last_success_at` per dispositivo), e «Spazio e limiti» elenca la soglia nei limiti.

## Conseguenze

- Migrazione `0004`: crea `user_preference`; aggiunge `ingest_token.scope NOT NULL DEFAULT 'ingest'` + `CHECK`.
  `downgrade` toglie tutto (le preferenze salvate si perdono). Prima del deploy `pg_dump` (README).
- Contratto Reader → Writer: **additivo** (versione 1.2.0): i token `ha` non possono scrivere (`403`); nulla cambia per
  il Reader.
- Seed dev: due dispositivi (il secondo ha sincronizzato due ore fa), per mostrare l'elenco per dispositivo.

## Limiti noti

- Le preferenze sono una per chiave per tutto il writer (non per utente): giusto finché l'utente è uno.
- Se due dispositivi cambiano la scelta insieme vince l'ultimo salvataggio; una pagina già aperta non si aggiorna da sola
  finché non la ricarichi.
- Il rate limit è per processo (un solo worker, come il login).
- `last_ingest_at` considera ogni attività di sync (anche una sync che non conclude): non è una prova che i dati siano
  arrivati, per quello c'è `last_sync_at`.
