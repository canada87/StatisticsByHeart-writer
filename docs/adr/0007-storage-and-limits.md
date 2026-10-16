# ADR 0007 — Spazio occupato, limiti e retention (scheda di sola lettura)

Stato: accettato · 2026-10-16 · Nessuna migrazione

## Contesto

L'utente vuole vedere dall'interfaccia quanto spazio occupano i dati, quali sono i limiti del database e se esistono
retention o blocchi, senza accedere alla VM. La scheda **Spazio e limiti** (Sync / Dati) è **di sola lettura**: nessuna
azione di pulizia.

## Decisioni

1. **`GET /api/v1/storage`** (autenticato, solo dashboard, fuori contratto Reader): dimensione del database
   (`pg_database_size`), per ogni tabella totale / dati / indici (`pg_total_relation_size`, `pg_indexes_size`; dati =
   totale − indici) e righe, record cancellati, primo/ultimo dato, ultimo invio, versione di Postgres, disco e crescita.
   Usa solo funzioni di catalogo che ogni ruolo può chiamare sulle proprie tabelle: **funziona con l'utente DB normale**
   dell'app (un test lo prova con un ruolo non superuser). Non seleziona mai una misura: solo conteggi, dimensioni e date.
2. **Righe: stima o conteggio esatto.** Per le tabelle grandi si usa la stima del catalogo (`pg_stat_user_tables.n_live_tup`
   / `reltuples`: costo nullo); un `count(*)` esatto solo sotto `EXACT_COUNT_BELOW = 100 000` righe stimate, dove è
   economico. Ogni tabella dichiara se il valore è esatto (`rows_exact`) e l'interfaccia lo marca con «≈».
3. **Crescita = stima dichiarata.** Record (e campioni di serie, da `data.sample_count`) ingeriti negli ultimi 30 giorni
   per `ingested_at`, byte = righe × dimensione media di una riga di quella tabella, proiezione a un anno a pari ritmo. La
   finestra si accorcia all'età dei dati se più giovane di 30 giorni. Limite noto: un **backfill iniziale** (anni di dati
   vecchi inviati in pochi giorni) la gonfia; il testo lo dice.
4. **Disco = «Disco della VM (stima)».** `shutil.disk_usage("/")` sul filesystem che vede `sbh-api`: è il disco di Docker
   sulla VM, di norma lo stesso del database. Nessuna modifica al compose. Il valore è libero/usato/totale con barra e testo.
5. **Limiti e retention dalle costanti vere**, come le regole degli allenamenti: `describe_limits()` restituisce le voci
   con i valori reali (retention, soft delete, pulizia sessioni, ricalcolo notturno, limiti di ingest, punti di una traccia,
   giorni per richiesta, finestre intraday, punti per grafico) e la pagina le formula con chiavi i18n parametrizzate:
   nessun numero è scritto nel frontend. Le costanti che prima erano numeri sparsi (`MAX_ROUTE_POINTS`,
   `PURGE_SESSIONS_MINUTE`, `RECONCILE_HOUR/MINUTE`) hanno ora un nome.
6. **Fatti verificati nel codice:** nessuna retention sui dati sanitari (l'unica pulizia è `purge_sessions`, sessioni web
   scadute, ogni ora al minuto 17); le cancellazioni da Health Connect sono soft delete (`deleted_at`) e i loro
   `health_sample` vengono eliminati; il ricalcolo notturno delle metriche giornaliere non cancella dati.

## Limiti noti

- Le dimensioni sono quelle del catalogo: dopo molte cancellazioni/aggiornamenti includono spazio non ancora recuperato da
  autovacuum (bloat).
- Le stime di righe di una tabella grande possono ritardare finché Postgres non aggiorna le statistiche.
- Il disco misurato è quello del container; se i dati stanno su un volume diverso dal filesystem radice, il valore non lo
  rappresenta.
