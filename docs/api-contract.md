# StatisticsByHeart — Contratto API Reader → Writer

**Versione contratto: `1.2.0`** · API: `/api/v1` · Stato: **CONGELATO** (2026-10-14; 1.1.0 additiva 2026-10-16; 1.2.0 additiva 2026-10-18)

Questa è la **fonte di verità** per il Reader (app Android). Il file OpenAPI generato dal codice
(`docs/openapi.json`) descrive gli stessi payload in forma macchina; in caso di discrepanza fa fede
questo documento e va aperto un bug sul writer.

> **Regola di modifica.** Cambiamenti *compatibili* (nuovi campi opzionali, nuovi tipi, nuovi endpoint)
> si fanno aggiungendo una riga al [Changelog](#8-changelog) con versione `1.x.0` e si segnalano
> all'utente. Cambiamenti *incompatibili* → `/api/v2`. Il Reader **non deve** dipendere da
> comportamenti non scritti qui.

---

## 1. Basi

| Aspetto | Valore |
|---|---|
| Base URL | l'origine configurata nel Reader, es. `https://sbh.example.lan`; tutti i path sotto sono relativi, es. `{base}/api/v1/ping` |
| Auth ingest | `Authorization: Bearer <token>` (token `sbh_…`, creato dall'admin web, mostrato **una sola volta**, revocabile) |
| Formato | JSON UTF‑8, `Content-Type: application/json` |
| Compressione | Richiesta: `Content-Encoding: gzip` **accettato** (consigliato per i batch). Risposte non compresse |
| Dimensione | max **500 record/elementi** per richiesta (oltre → `413 batch_too_large`); max **32 MiB** di body *decompresso* (oltre → `413 body_too_large`). Consiglio: chiudere il batch anche a ~5 MiB di JSON |
| Timestamp | ISO‑8601 **con fuso esplicito** (`2026-10-14T08:15:00Z` oppure `…+02:00`). Timestamp senza fuso → il record è rifiutato. Il writer salva in UTC |
| Offset di fuso | `*_offset_s` = `ZoneOffset.totalSeconds` di Health Connect (secondi a est di UTC, es. CEST = `7200`). Opzionale: se manca, il writer usa `Europe/Rome` |
| Numeri | Unità fisse per tipo (§4). Il Reader converte (es. `Energy.inKilocalories`, `Length.inMeters`) |
| ID | `device_id`, `sync_id`: UUID (stringa). `hc_id`: `metadata.id` di Health Connect, stringa 1‑128 caratteri |

### 1.1 Identificatori di dispositivo e di sync

- `device_id`: UUID generato **una volta** dal Reader alla prima esecuzione e conservato (DataStore). Il
  writer registra il dispositivo al primo uso. Opzionale `device: {name, model, app_version}` (stringhe ≤100)
  per etichettarlo.
- `sync_id`: UUID nuovo per **ogni sync run** (backfill o incrementale). Tutte le richieste di una run
  (`records`, `deletions`, `daily-aggregates`, `sync-report`) usano lo stesso `sync_id`. Un retry dello stesso
  batch riusa lo stesso `sync_id`.

### 1.2 Errori

Tutti gli errori (non‑2xx) hanno questa forma:

```json
{ "error": { "code": "invalid_token", "message": "…", "details": [ { "loc": ["body","device_id"], "msg": "…" } ] } }
```

(`details` presente solo per `422`; non contiene mai i valori ricevuti.)

| HTTP | `error.code` | Significato | Azione del Reader |
|---|---|---|---|
| 200 | — | Richiesta elaborata. **Anche se alcuni elementi sono in `rejected`** | Batch consegnato: rimuovere dall'outbox |
| 400 | `invalid_body` | Body non è JSON valido / gzip corrotto | Bug del client: non ritentare in loop |
| 401 | `invalid_token` | Token mancante/sconosciuto | Fermare la sync, mostrare «token non valido» |
| 401 | `token_revoked` | Token revocato dall'admin | Idem |
| 413 | `batch_too_large` / `body_too_large` | Troppi elementi / body troppo grande | Dividere il batch a metà e ritentare |
| 422 | `validation_error` | **Busta** malformata (es. `device_id` non UUID, `records` non è una lista) | Bug del client: non ritentare in loop, loggare `details` |
| 5xx / timeout / rete | — | Errore transitorio | **Retry con backoff esponenziale** dall'outbox (idempotente) |

> I problemi sul **singolo record** (campo mancante, valore fuori range, tipo non supportato…) **non**
> producono 4xx: il record finisce in `rejected` con `reason`/`detail` e il resto del batch viene
> elaborato (200). Un record rifiutato **non va ritentato** (è permanente): contarlo nel `sync-report`.

### 1.3 Idempotenza, ordine, retry

- Ogni richiesta è **idempotente**: reinviare lo stesso batch (anche N volte) non crea duplicati né cambia i
  risultati oltre al contatore `unchanged`.
- Chiave di upsert dei record: `(type, hc_id)`. Un record già presente viene **aggiornato se
  `last_modified` in ingresso è maggiore** di quello salvato **oppure è uguale ma `data` è diverso** (es. la
  `route` GPS aggiunta a una sessione già inviata: il Reader può rimandare le sessioni passate con lo stesso
  `last_modified`); se `last_modified` è uguale e `data` identico, o è minore, è `unchanged`. Un record
  cancellato non viene mai riattivato da un reinvio con lo stesso `last_modified`. Un aggiornamento di una
  `ExerciseSession` **senza** `route` non cancella la `route` già salvata (permesso tracce revocato).
- Il Reader marca un batch come consegnato **solo dopo una risposta 2xx**.
- **Ordine:** consegnare i batch in ordine FIFO (un record modificato e poi cancellato deve arrivare come
  `records` e poi `deletions`). Il writer è comunque robusto a riordini di `records` (via `last_modified`), ma una
  `deletion` ricevuta *prima* del record corrispondente viene ignorata (`not_found`).
- Il writer serializza internamente le scritture; richieste concorrenti sono sicure ma una alla volta.

---

## 2. Endpoint

### 2.1 `GET /api/v1/health` — senza auth

Liveness/raggiungibilità. Il Reader lo usa per distinguere «server irraggiungibile» da «token invalido».

`200` → `{ "status": "ok" }`

### 2.2 `GET /api/v1/ping` — auth Bearer

Verifica connettività **e** token (schermata Config del Reader).

`200`:

```json
{
  "ok": true,
  "api_version": "1",
  "server_time": "2026-10-14T09:30:12.123456Z",
  "token": { "name": "Xiaomi 14T Pro", "prefix": "sbh_a1b2" },
  "limits": { "max_batch_records": 500, "max_body_bytes": 33554432 }
}
```

`401` con `invalid_token` / `token_revoked`. Il Reader può usare `limits` per dimensionare i batch e
`server_time` per rilevare un orologio del telefono sballato.

### 2.3 `POST /api/v1/ingest/records`

```json
{
  "device_id": "5b0c3c0e-6a7e-4a38-9f0e-0a9d3b1c2d4e",
  "sync_id":   "0f9c2f1e-7d2b-4a55-8d1e-2c7e5d9f6a10",
  "device": { "name": "Xiaomi 14T Pro", "model": "2407FRK8EG", "app_version": "0.1.0" },
  "records": [
    {
      "type": "Steps",
      "hc_id": "b7f1c0a2-3d44-4a0c-9d3a-111111111111",
      "start_time": "2026-10-14T08:00:00+02:00",
      "end_time":   "2026-10-14T08:15:00+02:00",
      "start_offset_s": 7200,
      "end_offset_s": 7200,
      "source": {
        "package": "com.google.android.apps.fitness",
        "device": { "type": "PHONE", "manufacturer": "Xiaomi", "model": "2407FRK8EG" },
        "recording_method": "automatic"
      },
      "last_modified": "2026-10-14T06:16:03Z",
      "data": { "value": 842 }
    }
  ]
}
```

Campi del record (busta — comune a tutti i tipi; **campi sconosciuti sono rifiutati**):

| Campo | Obbl. | Note |
|---|---|---|
| `type` | sì | Uno dei tipi di §4 (nome della classe HC senza `Record`). Altro → `rejected: unsupported_type` |
| `hc_id` | sì | `metadata.id` |
| `start_time` | sì | `startTime` / `time` per i record istantanei |
| `end_time` | dipende | **Obbligatorio** per tipi `interval`/`series`/`session`; **opzionale** per `instant` (omettere, o uguale a `start_time`). `end_time ≥ start_time` |
| `start_offset_s`, `end_offset_s` | no | `zoneOffset` HC (può essere `null` in HC → omettere il campo). Range ±64800 |
| `source.package` | sì | `metadata.dataOrigin.packageName` |
| `source.device` | no | `metadata.device`: `{type, manufacturer, model}` (stringhe, tutte opzionali) |
| `source.recording_method` | no | `unknown` (default) \| `active` \| `automatic` \| `manual` (da `metadata.recordingMethod`) |
| `last_modified` | sì | `metadata.lastModifiedTime` |
| `data` | sì (può essere `{}` solo se il tipo non ha campi obbligatori) | Payload specifico del tipo, §4. **Campi sconosciuti rifiutati** |

Risposta `200`:

```json
{
  "received": 500, "inserted": 120, "updated": 3, "upserted": 123, "unchanged": 375,
  "rejected": [
    { "index": 17, "hc_id": "…", "type": "Steps", "reason": "invalid_record",
      "detail": "value: Input should be greater than or equal to 0" }
  ]
}
```

- `received` = elementi nella richiesta; `upserted = inserted + updated`; `unchanged` include anche duplicati
  dello stesso `(type, hc_id)` *dentro* il batch (vince `last_modified` maggiore).
- `rejected[].reason`: `invalid_record` (validazione) · `unsupported_type`. `detail` è testo leggibile,
  **senza valori sanitari**.
- Un record precedentemente cancellato (soft delete) torna attivo **solo** se arriva con `last_modified`
  maggiore di quello salvato.

### 2.4 `POST /api/v1/ingest/deletions`

Inoltra le `DeletionChange` della Changes API.

```json
{
  "device_id": "5b0c3c0e-…", "sync_id": "0f9c2f1e-…",
  "items": [ { "hc_id": "b7f1c0a2-3d44-4a0c-9d3a-111111111111" },
             { "hc_id": "…", "type": "Steps" } ]
}
```

> ⚠️ **`type` è opzionale** perché `DeletionChange` di Health Connect contiene **solo l'id** del record. Se
> `type` è omesso il writer cancella (soft) tutti i record con quell'`hc_id`, di qualunque tipo. Se è
> presente, restringe a quel tipo.

Risposta `200`:
`{ "received": 2, "deleted": 1, "already_deleted": 0, "not_found": 1, "rejected": [] }`

Effetto: `deleted_at` valorizzato, i campioni delle serie del record vengono eliminati, i valori giornalieri
dei giorni coinvolti vengono ricalcolati. `not_found` = id mai ricevuto (ignorato, non è un errore).

### 2.5 `POST /api/v1/ingest/daily-aggregates`

Snapshot degli **aggregati ufficiali di Health Connect** (`aggregate()` / `aggregateGroupByPeriod`, che
applicano la priorità delle origini dati). Servono perché i totali giornalieri non si possono ottenere
sommando i record grezzi di più sorgenti (Fit, Feelfit, Withings scrivono tutte in HC).

```json
{
  "device_id": "5b0c3c0e-…", "sync_id": "0f9c2f1e-…",
  "items": [
    { "date": "2026-10-14", "type": "Steps", "sum": 8421, "data_origins": ["com.google.android.apps.fitness"],
      "snapshot_at": "2026-10-14T18:00:00Z" },
    { "date": "2026-10-14", "type": "HeartRate", "avg": 71.4, "min": 48, "max": 142, "count": 15234 },
    { "date": "2026-10-14", "type": "SleepSession", "sum": 26340 }
  ]
}
```

| Campo | Note |
|---|---|
| `date` | Giorno **locale** (`YYYY-MM-DD`) del periodo che il Reader ha interrogato (`aggregateGroupByPeriod` con `LocalDateTime` a mezzanotte del fuso del telefono) |
| `type` | Qualsiasi tipo di §4 |
| `sum`/`avg`/`min`/`max`/`count` | Almeno uno. Stesse **unità** di §4; per sonno ed esercizio `sum` = **secondi** (`SLEEP_DURATION_TOTAL`, `EXERCISE_DURATION_TOTAL`) |
| `data_origins` | Opzionale: pacchetti che HC indica come contributori (`AggregationResult.dataOrigins`) |
| `snapshot_at` | Opzionale (default = ora di ricezione). Una snapshot **più vecchia** di quella già salvata non sovrascrive |

Semantica: upsert su `(date, type)` con `source = hc_official`; l'ultima snapshot vince. Si può reinviare
il giorno corrente a ogni sync. Risposta: `{ "received", "upserted", "unchanged", "rejected":[…] }`
(`unchanged` = stessi valori già salvati).

Il writer tiene **separati** gli aggregati ufficiali dai valori che calcola lui dai record
(`computed`); la dashboard mostrerà l'ufficiale come valore principale.

### 2.6 `POST /api/v1/ingest/sync-report`

Chiude una run. Idempotente (un secondo invio sostituisce il primo).

```json
{
  "device_id": "5b0c3c0e-…", "sync_id": "0f9c2f1e-…",
  "mode": "incremental", "status": "completed",
  "started_at": "2026-10-14T08:00:00Z", "finished_at": "2026-10-14T08:00:07Z",
  "counts": { "records_sent": 123, "records_rejected": 1, "deletions_sent": 2, "batches": 3 },
  "errors": [ { "code": "type_read_failed", "type": "Power", "count": 1,
                "message": "SecurityException: missing permission" } ]
}
```

- `mode`: `backfill` | `incremental` · `status`: `completed` | `partial` | `failed`.
- `counts`: mappa libera `string → int` (≤50 chiavi) scelta dal Reader; salvata così com'è.
- `errors`: ≤50 voci; `message` ≤500 caratteri, **mai valori sanitari**.
- Risposta: `{ "ok": true, "sync_id": "…" }`.

Il writer tiene inoltre propri contatori per `sync_id` (record ricevuti/inseriti/aggiornati/rifiutati,
cancellazioni, aggregati), visibili all'admin: il confronto con `counts` rivela perdite.
Una run per la quale non arriva mai il report resta `running`.

---

## 3. Come il writer usa i dati (cosa il Reader deve sapere)

1. **Giorno locale.** Calcolato dal writer con l'offset *del record* (`start_offset_s`; per il sonno
   `end_offset_s`, cioè il giorno del **risveglio**); se l'offset manca, `Europe/Rome`. Un record viene attribuito
   a **un solo** giorno (quello di inizio; per il sonno quello di fine); non viene spezzato a mezzanotte.
2. **Totali giornalieri calcolati** (`computed`) dai record grezzi **non sommano ciecamente** le sorgenti: per
   i tipi cumulativi i record di sorgenti meno prioritarie vengono ridotti della parte che si sovrappone
   nel tempo a quelle più prioritarie (priorità configurabile; di default vince la sorgente con più dati del giorno).
   Per sonno ed esercizio una sessione sovrapposta per >50 % a una più prioritaria è considerata duplicata.
   Servono per i dettagli e come ripiego: **il valore ufficiale è l'aggregato HC** (§2.5).
3. Campioni delle serie (`HeartRate`, …): salvati uno per riga; i campioni duplicati (stesso timestamp nello
   stesso record) collassano.
4. Nessun valore sanitario viene scritto nei log del writer.

---

## 4. Tipi di record e payload `data`

Convenzione: i tipi *scalari* usano `data.value` nell'unità indicata. Campi marcati `?` sono opzionali.
**Il Reader converte nelle unità sotto.** Range violato → record rifiutato (`invalid_record`).

Colonna *forma*: `interval` = valore cumulato su `[start,end]` (end obbligatorio) · `instant` = punto nel tempo ·
`series` = `[start,end]` con campioni · `session` = struttura specifica.

### 4.1 Cumulativi (`interval`) — `data: {"value": number}`

| `type` | Unità | Range `value` | Note |
|---|---|---|---|
| `Steps` | `count` | 0 – 1 000 000 | `count` |
| `Distance` | `m` | 0 – 10 000 000 | `distance.inMeters` |
| `ActiveCaloriesBurned` | `kcal` | 0 – 100 000 | `energy.inKilocalories` |
| `TotalCaloriesBurned` | `kcal` | 0 – 100 000 | idem |
| `FloorsClimbed` | `floors` | 0 – 10 000 | |
| `ElevationGained` | `m` | 0 – 100 000 | |
| `Hydration` | `L` | 0 – 1 000 | `volume.inLiters` |
| `Nutrition` | `kcal` | — | `data` = `{name?, meal_type?, energy_kcal?, protein_g?, total_fat_g?, total_carbohydrate_g?, dietary_fiber_g?, sugar_g?}` (numeri ≥0). Il totale giornaliero usa `energy_kcal` |

### 4.2 Istantanei (`instant`; `end_time` opzionale) — `data: {"value": number, …}`

| `type` | Unità | Range `value` | Campi extra in `data` |
|---|---|---|---|
| `RestingHeartRate` | `bpm` | 10 – 300 | |
| `Weight` | `kg` | 1 – 700 | |
| `OxygenSaturation` | `percent` | 0 – 100 | |
| `HeartRateVariabilityRmssd` | `ms` | 0 – 10 000 | |
| `Vo2Max` | `ml/min/kg` | 0 – 120 | `measurement_method?` (stringa) |
| `RespiratoryRate` | `breaths/min` | 0 – 200 | |
| `BasalMetabolicRate` | `kcal/day` | 0 – 20 000 | |
| `Height` | `m` | 0.1 – 3.0 | |
| `BodyFat` | `percent` | 0 – 100 | |
| `LeanBodyMass` | `kg` | 0 – 700 | |
| `BoneMass` | `kg` | 0 – 100 | |
| `BodyWaterMass` | `kg` | 0 – 700 | |
| `BloodGlucose` | `mmol/L` | 0 – 100 | `specimen_source?`, `meal_type?`, `relationship_to_meal?` (stringhe) |
| `BodyTemperature` | `celsius` | 20 – 50 | `measurement_location?` (stringa) |
| `BloodPressure` | `mmHg` | — | **non** usa `value`: `data = {"systolic": 20–400, "diastolic": 10–300, "body_position?": str, "measurement_location?": str}` |

### 4.3 Serie (`series`; `end_time` obbligatorio)

`data = { "samples": [ { "time": <ISO con fuso>, "value": number }, … ] }` — fino a **20 000** campioni per record
(`samples` può essere vuoto). Il writer li esplode in una riga per campione.

| `type` | Unità di `value` | Campi extra in `data` |
|---|---|---|
| `HeartRate` | `bpm` | |
| `Speed` | `m/s` | |
| `Power` | `W` | |
| `StepsCadence` | `steps/min` | |
| `CyclingPedalingCadence` | `rpm` | |
| `SkinTemperature` | `celsius_delta` (differenza dalla baseline) | `baseline_celsius?`, `measurement_location?` |

### 4.4 Sessioni (`session`; `end_time` obbligatorio)

**`SleepSession`** — `data = { "title?": str, "stages": [ { "stage", "start_time", "end_time" } ] }`
(`stages` opzionale, ≤1000). `stage` ∈ `unknown | awake | sleeping | out_of_bed | light | deep | rem | awake_in_bed`
(mappa delle costanti `SleepSessionRecord.STAGE_TYPE_*`). Il «tempo addormentato» esclude
`awake`, `out_of_bed`, `awake_in_bed`; senza `stages` conta tutta la sessione.

**`ExerciseSession`** — `data = { "exercise_type": str, "exercise_type_id?": int, "title?": str, "route?": [ … ] }`
- `exercise_type`: nome costante HC in maiuscolo (`WALKING`, `RUNNING`, `BIKING`, …), obbligatorio;
  `exercise_type_id`: intero HC grezzo.
- `route` (opzionale, ≤50 000 punti): `{ "time", "lat" (−90..90), "lon" (−180..180), "alt_m?", "horizontal_accuracy_m?" }`.
  Il tipo separato `ExerciseRoute` della guida **non esiste**: la rotta viaggia dentro la sessione. Richiede il
  consenso per sessione di HC; inviarla solo se concessa. Una sessione con 50 000 punti pesa alcuni MiB di JSON:
  rientra nei limiti della §1 (500 elementi e 32 MiB decompressi per richiesta; gzip consigliato), ma conviene
  chiudere il batch a ~5 MiB e mandare le sessioni con rotta poche per volta.
- `source.recording_method` conta per la dashboard: **`active` e `manual` = sessione avviata dall'utente**,
  `automatic`/`unknown` = rilevata. È mostrato come informazione accanto alla sessione (insieme alla copertura della
  frequenza cardiaca e alla presenza della `route`); **non** decide se è un «allenamento vero»: dalla 0.5.1 conta solo
  `exercise_type` (non camminata → vero, ADR 0006). Inviare comunque il valore corretto di `metadata.recordingMethod`.

**`MindfulnessSession`** — `data = { "mindfulness_type?": str, "title?": str }`.

### 4.5 Aggiungere tipi

Un nuovo tipo è una riga nel registro del writer (`backend/app/health_types.py`) + una riga qui + riga di
changelog. Il Reader non può inventare tipi (rifiutati come `unsupported_type`): chiedere prima.

---

## 5. Flusso consigliato di una sync

```
sync_id = uuid()
GET  /health                      (opzionale, per diagnosticare)
GET  /ping                        (all'avvio della run, o nella schermata Config)
loop batch (≤500 record, ≤~5 MiB):
    POST /ingest/records          (gzip)  → se 2xx: segnare consegnato
POST /ingest/deletions            (se la Changes API ne ha restituite)
POST /ingest/daily-aggregates     (giorni toccati / ultimi N giorni)
POST /ingest/sync-report          (sempre, anche con status failed/partial)
```

- **Backfill:** finestre temporali (es. 7 giorni) × tipo; stesso formato dell'incrementale.
- **Token Changes scaduto** (`changesTokenExpired`): rifare un backfill/riconciliazione; il writer non ha
  bisogno di sapere nulla (l'upsert è idempotente).
- Mai loggare/mostrare in `sync-report.errors[].message` valori sanitari.

---

## 6. Autenticazione (per completezza; non usata dal Reader)

Il Reader usa **solo** `Authorization: Bearer`. I token si creano/revocano dall'admin web
(`POST/GET/DELETE /api/v1/admin/tokens`, sessione cookie). Il token in chiaro viene mostrato alla creazione
e **mai più**; il writer conserva solo l'hash SHA‑256. Un token revocato risponde `401 token_revoked`.

Dalla 1.2.0 ogni token ha uno **scope**: `ingest` (il Reader, tutto ciò che è in §2) oppure `ha` (Home Assistant, solo
`GET /api/v1/ha/status`, vedi §7). I due non sono intercambiabili: un token `ha` su un endpoint di ingest o su `/ping` risponde
`403` con `error.code = wrong_token_scope`. Il Reader usa token `ingest` (il default) e non cambia nulla.

---

## 7. Fuori contratto (non stabile)

`/api/v1/auth/*`, `/api/v1/admin/*`, `/api/docs`, `/api/openapi.json` e le API della dashboard sono
interne al writer e possono cambiare senza cambio di versione del contratto. Dalla 0.4.0 la dashboard
usa anche `GET /api/v1/heart/daypart` (FC diurna/notturna, vedi ADR 0005): è un'estensione additiva
della sola API dashboard e **non** modifica il contratto Reader → Writer. Dalla 0.5.0 anche
`PUT /api/v1/exercise/sessions/{id}/override` (verdetto manuale «allenamento vero»), `GET /api/v1/exercise/rules` (le regole attive,
generate dalle costanti del writer), `GET /api/v1/storage` (spazio, limiti e retention, sola lettura),
`GET /api/v1/report` esteso in modo additivo (campi `extra_metrics`, `points`, `monthly`, `workouts.by_type_detail`; ADR 0009) e le colonne
`hr_day`, `hr_night`, `heart_points` di `/report/daily`,
`GET /api/v1/heart/points`, `/heart/points/week` e `/heart/points/rules` (Punti cardio, ADR 0008; il tipo `HeartPoints` è
una metrica **calcolata** del writer, non un tipo di record: il Reader non lo invia), `?scope=real` su
`/exercise/sessions` e `?include_workouts` su `/heart/daypart` (ADR 0006). Dalla 0.8.0 anche `GET/PUT/DELETE /api/v1/preferences/{key}`
(scelte della dashboard salvate sul server, sessione admin + header CSRF) e `GET /api/v1/ha/status` (stato dell'allarme «sync ferma» per
Home Assistant: token con scope `ha`, nessun valore sanitario; ADR 0010).

---

## 8. Changelog

| Versione | Data | Modifica |
|---|---|---|
| **1.2.0** | 2026-10-18 | Additiva. I token hanno uno `scope` (`ingest` di default, oppure `ha`); un token `ha` sugli endpoint di ingest e su `/ping` risponde `403 wrong_token_scope` (il Reader non è toccato). Nuovo `GET /api/v1/ha/status` per Home Assistant (token `ha`; solo `status`, date e ore, nessun valore sanitario; limite 30 richieste/minuto per token). `GET/PUT/DELETE /api/v1/preferences/{key}` (dashboard, fuori contratto) e il blocco `alarm` di `/sync/status`. Vedi ADR 0010. |
| **1.1.0** | 2026-10-16 | Additiva, nessun campo nuovo. Chiarito e implementato: un record con `last_modified` uguale ma `data` diverso viene **aggiornato** (rotta GPS aggiunta a sessioni passate) invece di essere `unchanged`; documentati i limiti di dimensione per le sessioni con `route` (≤50 000 punti, 32 MiB decompressi) e il significato di `recording_method` (`active`/`manual` = avviata dall'utente). Le API della dashboard aggiunte (`/heart/daypart`, override degli allenamenti) sono fuori contratto (§7). |
| **1.0.0** | 2026-10-14 | Prima versione congelata. Differenze rispetto alla bozza di PROJECT_GUIDE §6: `device_id` e `sync_id` (UUID) obbligatori in **tutte** le richieste di ingest; `type` opzionale nelle deletions; risposta `records` con `inserted`/`updated` e `rejected[].index`; aggiunto `GET /health` pubblico; `ExerciseRoute` incorporato in `ExerciseSession.data.route`. |
