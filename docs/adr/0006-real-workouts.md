# ADR 0006 — Allenamenti «veri», verdetto manuale e FC diurna senza allenamenti

Stato: accettato · 2026-10-16 · **Migrazione `0003`** (tabella `exercise_override`)

## Contesto

L'orologio registra come `ExerciseSession` anche attività rilevate da sole (una camminata fino all'auto, qualche
minuto in bici): contate nel Report e nella FC diurna falsano sia il volume di allenamento sia la FC «a riposo di
giorno». L'utente vuole che contino solo gli allenamenti veri, poter correggere la classificazione, e una FC diurna
non gonfiata dagli sforzi. In parallelo il Reader comincia a inviare la traccia GPS (`data.route`), anche per le
sessioni passate.

## Decisioni

1. **Regola (0.5.1): un allenamento è vero se il tipo di attività non è una camminata.** Camminata = `exercise_type`
   `WALKING`; tutto il resto (corsa, ciclismo, **escursionismo/HIKING**, forza, qualunque altro tipo) è vero. La regola
   vive in un posto solo, l'insieme **`NOT_REAL_TYPES = {"WALKING"}`** in `services/workouts.py`: raffinarla è una
   modifica di una riga (più il testo «camminata → non vero» nell'interfaccia). Copertura FC, GPS e `recording_method`
   **non** fanno più parte della regola.
2. **Segnali solo informativi.** FC (quota di minuti con almeno un campione ≥ `HR_COVERAGE_MIN = 0.5`), GPS e «avviata da
   te» (`USER_STARTED_METHODS = {active, manual}`) restano calcolati e mostrati come badge accanto a ogni sessione, uniti
   tra le copie duplicate, ma non decidono il verdetto. Telefono e orologio registrano la stessa sessione: la copia
   migliore rappresenta l'allenamento (come per elenco e volume).
3. **Verdetto manuale.** Per sessione: *vero*, *non vero* o *automatico*. Vince sulla regola. Tabella
   `exercise_override(hc_id PK, is_real, updated_at)`: la chiave è l'**id Health Connect**, non l'id della riga, così il
   verdetto sopravvive al re-ingest, alla cancellazione e al reinserimento dello stesso record. «Automatico» cancella
   la riga. Il verdetto si scrive su tutte le copie della sessione. `PUT /api/v1/exercise/sessions/{id}/override`
   `{"value": true|false|null}` richiede la sessione di login e l'header `X-SBH-Client` (protezione CSRF come gli altri
   endpoint di scrittura).
4. **Elenco e Report.** `/exercise/sessions?scope=real|all` (default `all`, retrocompatibile; la pagina Attività chiede
   `real` e il filtro «Solo veri / Tutti» sta nell'URL: `?workouts=all`). Il **Report** conta e somma solo gli
   allenamenti veri (riga «Allenamenti», blocco allenamenti, tabella CSV giornaliera) e dice quante attività ha escluso
   (`workouts.excluded`). Volume settimanale e riepilogo seguono il filtro. L'elenco non carica più il JSON della
   `route` (fino a 50 000 punti per sessione): si leggono solo i flag.
5. **FC diurna.** `/heart/daypart` e i KPI escludono i campioni **dentro un allenamento vero più i 30 minuti
   successivi** (`RECOVERY_AFTER_S = 1800`). Le attività rilevate in automatico restano incluse. **La notte non cambia**
   (un campione notturno resta notturno anche dentro un allenamento). Il KPI generale «FC media» resta la media di tutto
   (con un'avvertenza). `?include_workouts=true` riporta gli allenamenti nella FC diurna; nell'interfaccia è
   l'interruttore «Includi allenamenti» (spento di default, nell'URL: `?incl=1`).
6. **Vista.** Con bucket 15 min/ora gli intervalli esclusi sono fasce tratteggiate ambra con etichetta e legenda
   «Allenamento», distinte dalle notti (viola, area piena). Con interruttore acceso non ci sono fasce da mostrare.
7. **Ingest.** Un `ExerciseSession` già noto con lo **stesso `last_modified` ma `data` diverso** (la `route` aggiunta)
   viene **aggiornato**, non contato come `unchanged`; un record cancellato non viene riattivato da un reinvio con lo
   stesso `last_modified`. Il confronto di `data` avviene solo per i record con `last_modified` uguale. Contratto
   `1.1.0` (additivo). **Se un aggiornamento successivo arriva senza `route`** (l'utente ha revocato il permesso delle tracce),
   il writer **conserva la route già salvata**: una versione senza `route` non la cancella; una versione con una
   `route` nuova la sostituisce. Il Reader rimanda le sessioni con la traccia a lotti di al massimo 5; finché non
   arrivano, la regola «FC + avvio da te» basta da sola. Una richiesta con una sessione da 50 000 punti in gzip è coperta da test; oltre 32 MiB
   decompressi il writer risponde `413 body_too_large`.

## Cronologia della regola

- **0.5.0:** FC presente (≥50% dei minuti) **E** (GPS **O** avviata da te). Provata in produzione con dati reali: **non
  funziona**, perché Google ricava la traccia GPS anche per attività che l'utente non ha avviato, quindi il GPS non
  distingue nulla (verificato dall'utente sui dati reali).
- **0.5.1:** regola semplificata: *non camminata → vero*. L'utente la raffinerà più avanti. Nessuna migrazione: la
  tabella `exercise_override` e i verdetti già salvati restano validi e vincono ancora sulla regola.

## Limiti noti

- **Una camminata vera** (una lunga camminata sportiva) non è un allenamento vero finché non la si corregge col
  verdetto manuale; viceversa **un'attività rilevata da sola di un altro tipo** (qualche minuto di «ciclismo» in
  macchina o in treno) risulta vera e dopo va corretta a mano. Senza FC, GPS o avvio la regola non può accorgersene.
- Il tipo dipende dall'app/orologio che registra: un'attività riclassificata dall'app cambia verdetto.
- I 30 minuti di recupero sono una costante, non una preferenza; un allenamento lungo che finisce a ridosso del sonno
  non toglie nulla alla notte.
- Il verdetto vale per l'id Health Connect: se un'app rigenera l'id della sessione, il verdetto va rimesso.
- Il Report storico cambia retroattivamente quando si riclassifica una sessione (i numeri non sono congelati).
