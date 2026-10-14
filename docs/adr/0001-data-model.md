# ADR 0001 — Modello dati (rifinitura della bozza di PROJECT_GUIDE §5.3)

Stato: accettato · 2026-10-14 · Migrazione: `backend/alembic/versions/20261014_0001_initial_schema.py`

## Contesto

Il writer riceve da Health Connect record di forme diverse (cumulativi su intervallo, punti, serie di
campioni, sessioni) da più sorgenti sovrapposte, con cancellazioni e modifiche. La bozza della guida elenca
le tabelle; qui si fissano i dettagli che la bozza lasciava aperti.

## Decisioni

1. **`health_record` unica per tutti i tipi**, chiave naturale `UNIQUE (type, hc_id)` (upsert idempotente).
   Il payload specifico del tipo sta in `data jsonb`, validato da un registro in codice
   (`app/health_types.py`); aggiungere un tipo non richiede migrazioni.
2. **`local_date date NOT NULL` denormalizzata** sul record (e sui campioni): giorno locale calcolato **una
   volta** all'ingest con l'offset del record (fallback `Europe/Rome`; sonno → giorno del risveglio). Rende il
   ricalcolo dei soli giorni toccati una query indicizzata e congela l'attribuzione anche se la config del
   fuso cambia. Costo: va ricalcolata se cambiasse la regola (migrazione dati).
3. **Timestamp `timestamptz` (UTC) + `start_offset_s`/`end_offset_s`** (interi, nullable) come da HC.
4. **Aggiornamento solo se `last_modified` è maggiore** di quello salvato (confronto in applicazione, sotto lock):
   rende innocui batch ripetuti e riordinati.
5. **Soft delete** con `deleted_at`; un record cancellato torna attivo solo con `last_modified` maggiore.
   La riga resta come tombstone (così un vecchio batch ritentato non lo resuscita). I **campioni** di un
   record cancellato vengono eliminati fisicamente (sono copie derivate).
6. **Cancellazioni senza tipo:** `DeletionChange` di HC porta solo l'id → indice su `hc_id`, il campo `type`
   delle deletions è opzionale.
7. **`health_sample (record_id, ts)` PK composta**, `ON DELETE CASCADE`; colonne `type`, `value`, `local_date`
   duplicate apposta per query di serie e aggregati senza join. Indici `(type, ts)` e `(type, local_date)`.
   I campioni di `HeartRate` **non** sono duplicati in `data` (solo `sample_count`).
8. **Indici parziali** `WHERE deleted_at IS NULL` su `(type, start_ts)` e `(type, local_date)`: le query della
   dashboard guardano solo il vivo.
9. **`daily_metric` PK `(local_date, type, source)`**, `source ∈ {hc_official, computed}` (CHECK): ufficiale e
   calcolato coesistono senza sovrascriversi. Colonne `sum/avg/min/max/count` + `unit` + `detail jsonb`
   (ripartizione per sorgente, metodo, ultimo valore, stadi del sonno…). Vedi ADR 0002.
10. **`sync_run.id` = `sync_id` del Reader** (UUID). Contatori lato server separati da `reported_counts`
    (cosa dice il Reader): la differenza svela perdite. `device.id` = UUID generato dal Reader.
11. **`ingest_token`**: solo `token_hash` (SHA‑256 hex) + `token_prefix` per riconoscerlo in UI; `revoked_at`
    invece di delete (audit). **`admin_user` aggiunta** (la bozza non la prevedeva): vedi ADR 0003.
12. **`user_session`**: hash del cookie, `expires_at`, `revoked_at`, IP/UA per audit.

## Conseguenze

- Una sola tabella larga per i record: query per tipo veloci grazie agli indici parziali; nessun JOIN per le
  serie temporali.
- Il registro dei tipi vive nel codice: il contratto (`docs/api-contract.md`) e il registro sono tenuti
  allineati da un test.
- Nessun partizionamento né Timescale: ~0,5 M campioni/anno sono banali per PostgreSQL 16. Rivalutare se
  `health_sample` supera decine di milioni di righe.
