# ADR 0011 — Esclusione manuale di misure errate

Stato: accettato · 2026-10-31 · **Migrazione `0005`** (tabella `record_exclusion`)

## Contesto

La bilancia ha più profili: il peso del figlio dell'utente è stato importato da Google Fit come se fosse dell'utente,
è arrivato in Health Connect (HC) e quindi nella dashboard. Né Fit né HC permettono di cancellare una singola misura,
quindi la correzione sta nel writer: l'utente deve poter **escludere** una misura sbagliata.

Decisioni dell'utente (vincoli di partenza):

- si escludono **singole misure** (record puntuali e sessioni: peso, pressione, SpO₂, FC a riposo, HRV, sonno,
  allenamenti), **non** giorni interi e **non** totali cumulativi giornalieri (passi, distanza, calorie, Punti cardio);
- escludere **non cancella**: il record resta nel database e l'esclusione è reversibile;
- una misura esclusa sparisce **ovunque**: grafici, KPI, medie, minimi e massimi, variazione sul periodo precedente,
  Report (schermo, PDF, CSV mese su mese), CSV dei grafici, aggregati calcolati (`daily_metric`), Panoramica, e i
  calcoli derivati (allenamenti veri, FC diurna/notturna, Punti cardio);
- **nessun segno nei grafici**: le esclusioni si vedono solo in una pagina dedicata, con «Ripristina»;
- l'esclusione deve **sopravvivere alle sincronizzazioni** (un record rinviato o aggiornato resta escluso) e non andare
  in errore se HC cancella il record.

## Decisioni

### 1. Tabella dedicata, non un flag sulla riga

`record_exclusion(type, hc_id, group_id, reason, created_at)` con chiave primaria `(type, hc_id)` e indice su
`group_id`. **Nessuna FK verso `health_record`.**

- *Perché una tabella e non una colonna `excluded` su `health_record`.* L'ingest fa upsert sulla stessa chiave: una
  colonna sarebbe una cosa in più che ogni percorso di scrittura deve ricordarsi di non sovrascrivere. Con una tabella
  separata l'ingest **non la tocca mai** e quindi l'esclusione sopravvive per costruzione a rinvii, aggiornamenti e
  ricostruzioni. È anche l'unica fonte di verità (nessun valore denormalizzato da tenere allineato).
- *Perché senza FK.* HC può cancellare il record (`deleted_at` oppure, in futuro, la riga sparisce): l'esclusione non
  deve né bloccare la cancellazione né sparire con essa. La pagina «Dati esclusi» mostra lo stato di ogni esclusione:
  `present`, `deleted_in_hc` (HC l'ha cancellato) o `missing` (la riga non c'è più); restano ripristinabili.
- `reason` (facoltativo, ≤ 200 caratteri, spazi tagliati) e `created_at` sono l'audit minimo.

### 2. Tipi escludibili

`Weight`, `BloodPressure`, `OxygenSaturation`, `RestingHeartRate`, `HeartRateVariabilityRmssd`, `SleepSession`,
`ExerciseSession`. Ogni altro tipo risponde `422 type_not_excludable`: i totali giornalieri e le serie dense (passi,
battiti) non hanno una «singola misura» sensata da togliere, e togliere un giorno è fuori scopo.

### 3. Copie della stessa misura: «gemelle» e `group_id`

Lo stesso peso arriva spesso da due app (bilancia + telefono): sono due record `health_record` con `hc_id` diversi.
Escluderne uno solo lascerebbe l'altro nei conti. Quindi:

- **gemelle** = stesso tipo e stesso `start_ts` per le misure puntuali; per le sessioni, sovrapposizione superiore al
  50 % della più breve;
- l'elenco delle misure raggruppa le gemelle in **una sola riga** (con le sorgenti), escludere una riga esclude **tutte**
  le gemelle presenti, che condividono un `group_id`, e «Ripristina» le riporta tutte insieme;
- la regola è la stessa usata dal conto senza doppioni (ADR 0002): una misura vale una volta.

**Limite noto.** Se una *nuova* copia della stessa misura arriva **dopo** l'esclusione (sync successiva da un'altra
app), non viene esclusa da sola: compare di nuovo e va esclusa a mano. Si poteva evitare con un'esclusione «per
istante» invece che «per record», ma significherebbe nascondere anche un valore *diverso* misurato nello stesso istante;
si è preferita l'esclusione esplicita (la scelta sbagliata più innocua è mostrare un dato in più).

### 4. Un solo predicato di visibilità, ovunque si legga

`app/services/visibility.py` espone `not_excluded()`: `NOT EXISTS (SELECT 1 FROM record_exclusion WHERE type = … AND
hc_id = …)` correlato a `health_record`. Si aggiunge **accanto a `deleted_at IS NULL`** in ogni query di analisi:
ricalcolo giornaliero (`daily._fetch_rows`), attività recenti, record intraday e riconciliazione (`queries`),
allenamenti (`workouts.load_workouts`), notti di sonno (`daypart._sleep_spans`), minuti di sessione per i Punti cardio
(`heartpoints.session_minutes`).

- *Inventario e spazio* (pagina Sync / Dati) **non** lo applicano di proposito: descrivono ciò che è **memorizzato**
  (quanti record ci sono, da quale sorgente), non ciò che si mostra. Un test fissa l'elenco delle tabelle ammesse.
- Poiché `daily_metric` è un aggregato **già calcolato**, ogni lettura del Report e dei grafici che parte da lì è
  coerente solo se l'aggregato viene ricalcolato: vedi punto 5.

### 5. Ricalcolo mirato, sotto lo stesso lock dell'ingest

Dopo `exclude` e `restore` si ricalcolano **solo i giorni locali toccati** (`recompute_days`, fuso Europe/Rome), sotto
l'advisory lock dell'ingest (`INGEST_LOCK_KEY`): un'esclusione non corre contro una sync. Per le sessioni di
allenamento `recompute_days` ricalcola anche i Punti cardio del giorno e del successivo (il riporto di 2 minuti).
La risposta di `POST` riporta i giorni ricalcolati.

### 6. API (sessione admin; le scritture chiedono `X-SBH-Client`)

Fuori dal contratto Reader (`docs/api-contract.md`): il Reader legge `daily_metric` e `/records`, che il filtro rende
già coerenti, senza nessun campo nuovo.

| Metodo e percorso | Risposta |
|---|---|
| `GET /api/v1/measures?type&from&to` | misure singole (gemelle raggruppate) del periodo, **max 400 giorni**; `422` oltre o per tipo non escludibile |
| `POST /api/v1/exclusions` `{record_id, reason?}` | `201 {group_id, records, days, measure}`; **idempotente** (rifare l'esclusione dà lo stesso gruppo); `404` record sconosciuto, `422` tipo non escludibile |
| `GET /api/v1/exclusions` | elenco con tipo, data, valore, sorgenti, motivo, data di esclusione e `state` |
| `DELETE /api/v1/exclusions/{group_id}` | `204`, ricalcola i giorni; `404` gruppo sconosciuto |

### 7. Interfaccia

- **Nessun segno nei grafici** (né marcatori, né note, né colori): chi guarda il grafico vede solo i dati buoni. Le
  esclusioni stanno solo in **Sync / Dati › Dati esclusi**.
- Si esclude da: un punto del grafico (clic o tocco), il pulsante permanente **«Escludi un valore…»** (percorso da
  tastiera: la finestra elenca le singole misure del punto selezionato o dell'intero periodo), una riga di «Mostra
  tabella», le righe degli allenamenti e delle notti di sonno.
- Un punto che aggrega **più misure** (settimana, mese, o un giorno con più pesate) porta all'**elenco delle singole
  misure**; con una sola misura si passa direttamente alla conferma. La conferma mostra tipo, data e ora, valore e
  sorgenti, con il motivo facoltativo.
- Esito con **«Annulla»** nel toast (regione `aria-live="polite"`, 12 s, chiudibile); poi ogni query viene invalidata e
  grafici, KPI e Report si aggiornano.
- Accessibilità (§8.5): nessuna azione solo al passaggio del mouse, ogni controllo ha un'etichetta che nomina la misura,
  finestra di dialogo (Radix) con focus intrappolato e restituito al pulsante che l'ha aperta, bersagli ≥ 44 px.

### 8. Aggregato ufficiale di Health Connect (correzione 0.9.1)

Per ogni giorno e tipo la lettura preferisce la riga `daily_metric` con `source = 'hc_official'` (calcolata da HC dai
suoi dati) a quella `computed`. L'aggregato ufficiale **include** la misura esclusa, quindi nella 0.9.0 l'esclusione
ricalcolava la riga `computed` ma non cambiava ciò che si vedeva nei giorni con un ufficiale (caso reale: due pesi nello
stesso giorno, ufficiale = la loro media).

Regola: se nel giorno locale D esiste almeno un record **escluso e non cancellato** di tipo T (stessa attribuzione al
giorno del ricalcolo: `health_record.local_date`, il giorno del risveglio per il sonno), la riga `hc_official` di (T, D)
**viene ignorata** e vale la `computed`.

- Un solo punto: `visibility.daily_visible()` (predicato SQL, `NOT (source = 'hc_official' AND giorno con esclusione)`),
  aggiunto a **ogni** lettura di `daily_metric` che alimenta grafici, KPI, Panoramica, Report e CSV
  (`queries._daily`, ultimi valori, sonno, serie; `analytics._nights`, `report_daily`).
- È valutato **in lettura**: niente colonna o ricalcolo in più. Perciò copre l'aggregato che il Reader rimanda dopo
  l'esclusione (la riga ufficiale viene aggiornata ma resta ignorata), «Ripristina» riporta subito l'ufficiale, e le
  esclusioni già fatte con la 0.9.0 si correggono da sole al deploy.
- Se il record escluso è stato cancellato in Health Connect non impone più nulla: il prossimo ufficiale non lo contiene.
- Solo `ExerciseSession`/`count` e i Punti cardio leggono già solo `computed`.
- La riga ufficiale resta **memorizzata** intatta; l'inventario e la scheda **Riconciliazione** la mostrano ancora, con
  il campo `official_ignored` e una nota sobria («Esclusione manuale: …») nel giorno interessato. Nei grafici nessun
  segno, come deciso.
- Costo: una `NOT EXISTS` sulle sole righe ufficiali, con join sulla tabella delle esclusioni (di poche righe).

## Conseguenze

- **Migrazione `0005`**: una tabella nuova, nessuna colonna toccata, nessun dato spostato. Reversibile (`downgrade`
  la elimina e con essa le esclusioni). Prima di aggiornare, `pg_dump` come per ogni migrazione.
- Costo per riga: un `NOT EXISTS` con indice sulla chiave primaria `(type, hc_id)`; trascurabile finché le esclusioni
  sono poche (è il caso d'uso).
- Il seed sintetico contiene un peso palesemente non dell'utente (32 kg, da due app, tre giorni prima della fine) per
  mostrare e testare la funzione.
- Fuori scopo, volutamente: escludere un giorno intero, escludere totali cumulativi, escludere in blocco, esclusione
  automatica delle copie arrivate dopo, un segno nei grafici.
