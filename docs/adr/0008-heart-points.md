# ADR 0008 — Punti cardio (Heart Points)

Stato: accettato · 2026-10-16 · Nessuna migrazione (righe `daily_metric` di un tipo calcolato)

## Contesto

L'utente vuole i «Punti cardio» di Google Fit / AHA: un obiettivo settimanale di 150 punti, visibile in Panoramica, e un
grafico a barre nella pagina Cuore. Health Connect non fornisce i punti: vanno ricalcolati dai battiti e dai passi.

## Decisioni

1. **Calcolo minuto per minuto, su tutta la giornata, con tutti i battiti e tutte le attività** (nessuna esclusione degli
   allenamenti, a differenza della FC diurna dell'ADR 0006). Un minuto vale:
   - da **FC** (media dei campioni del minuto): `≥ 50%` della FCmax → **1** punto, `≥ 70%` → **2**;
   - da **cadenza**: `≥ 100` passi al minuto → **1**, `≥ 130` → **2**;
   - il **massimo** dei due criteri, **mai la somma** (1 da FC e 2 da cadenza fanno 2).
   Le soglie sono confronti esatti (`bpm·100 ≥ 70·FCmax`, senza virgola mobile), provati a 49/50/69/70% e 99/100/129/130.
2. **Criterio MET saltato.** Google Fit conta anche i MET; Health Connect non li ha. Lo dice il pannello delle regole.
3. **FCmax = 220 − età**, con età = anno del giorno calcolato − `SBH_BIRTH_YEAR` (solo l'anno: ±1 anno). Override
   opzionale `SBH_HR_MAX`, che vince. Valori fuori range (FCmax 100–250, età 1–110) sono ignorati. **Nessuna delle due
   impostata** → i punti da FC non si calcolano, restano quelli da cadenza, e la UI avvisa («imposta SBH_BIRTH_YEAR nel
   .env»). Sono **valori personali**: solo nel `.env` privato; nel repo c'è un segnaposto vuoto in `docker/.env.example`
   e un anno fittizio (1990) nel solo compose di sviluppo. L'API restituisce la FCmax usata e da dove viene, mai l'anno.
4. **Dettagli.** Tutti come costanti nominate in `services/heartpoints.py`:
   - *carry-forward*: un minuto senza campioni ripete l'ultimo valore se il campione precedente è di al massimo
     `HR_CARRY_MAX` = 5 minuti prima, altrimenti nessun punto da FC; non attraversa la mezzanotte;
   - *cadenza*: dai record `Steps` (intervalli) i passi si ripartiscono uniformemente sui minuti coperti. Si usano i
     record grezzi **passando per `counted_values`** (ADR 0002): una sorgente di rango più basso contribuisce solo alla
     parte del suo intervallo non già coperta da una di rango più alto, quindi la stessa camminata scritta da Fit e da
     Withings conta **una volta** (la priorità è `SBH_SOURCE_PRIORITY`, altrimenti per volume). I passi totali sono
     conservati; la cadenza di un minuto parzialmente sovrapposto è una media. I record **più lunghi di
     `STEPS_MAX_SPAN` = 60 minuti** sono totali, non cadenza: ignorati prima della deduplica, così non nascondono i veri;
   - *settimana* = lunedì–domenica, `Europe/Rome`; il giorno è il giorno locale con l'offset del record (§5.2.3), quindi
     il cambio d'ora non sposta né duplica minuti (i minuti sono istanti UTC: il 02:30 ripetuto vale due minuti diversi).
     Un record di passi appartiene al giorno in cui inizia.
5. **Persistenza.** Un tipo calcolato `HeartPoints` in `daily_metric` (`source=computed`, `sum_value` = punti del giorno,
   `detail` = punti da FC e da cadenza, FCmax usata e una firma delle impostazioni). Si ricalcola per ogni giorno toccato
   da un ingest di `HeartRate` o `Steps`, nel ricalcolo notturno e **all'avvio** per i giorni che mancano o che furono
   calcolati con altre impostazioni (task in background, a blocchi, solo conteggi nei log). Per rifare tutto lo storico:
   `python -m app.cli recompute-heart-points [--from --to]` (primo deploy; dopo un cambio di `SBH_BIRTH_YEAR` /
   `SBH_HR_MAX`). Un giorno senza più dati perde la riga. `HeartPoints` non è un tipo di record: l'ingest non lo accetta.
6. **API additive** (dashboard, fuori contratto Reader): `GET /heart/points?bucket=week|month|year` (somma per periodo,
   settimane «complete» e quante superano l'obiettivo, periodo precedente), `GET /heart/points/week?date=` (la settimana
   con totale, mancanti, giorni rimasti), `GET /heart/points/rules` (le regole dalle costanti: soglie, FCmax usata e
   origine, carry-forward, cadenze, MET non usato, obiettivo). Il testo della pagina sono chiavi i18n con i valori del
   backend.
7. **Panoramica:** card «Punti cardio · settimana» con anello verso `WEEKLY_GOAL` = 150, valore, punti mancanti e giorni
   rimasti (oggi compreso), in testo oltre che nell'anello. **Non** segue il periodo selezionato: mostra la settimana che
   contiene **la fine** della finestra (quindi la settimana corrente, o quella raggiunta con le frecce).
8. **Cuore:** grafico a barre con granularità minima la settimana (settimana / mese / anno, mai il giorno); nella vista
   settimanale una linea tratteggiata «Obiettivo 150» con etichetta. Tabella, CSV e riepilogo («N settimane su M sopra
   l'obiettivo»; la settimana in corso non è conteggiata). Il confronto con il periodo precedente è nel riepilogo
   testuale (totale del periodo precedente), non una seconda serie.

## Aggiornamento 0.6.1 — granularità giornaliera

- `GET /heart/points` accetta anche `bucket=day` (additivo). Come per gli altri grafici vale `MAX_POINTS` (1000): oltre,
  il bucket si allarga da solo (giorno → settimana), la risposta riporta il bucket realmente usato e `coarsened: true`, e il
  grafico lo dichiara. Il default del grafico resta la settimana, tranne a 7G e 30G (finestre di al massimo 30 giorni) dove
  diventa il giorno; la scelta esplicita dell'utente vince.
- Nella vista giornaliera una linea tratteggiata a **`WEEKLY_GOAL / 7` ≈ 21,4 punti al giorno** (`daily_reference`,
  calcolata dalla costante, nessun numero scritto altrove), con etichetta «Riferimento ~21/giorno (150/7)». È **un
  riferimento indicativo, non un obiettivo giornaliero**: il riepilogo scrive «N giorni su M sopra ~21 (riferimento
  indicativo, non un obiettivo)» e non dichiara mai un obiettivo raggiunto. I giorni «completi» escludono oggi (parziale).
  Nelle viste mese/anno nessuna linea. La riga corrispondente è nel pannello delle regole, generata dal backend.

## Aggiornamento 0.8.1 — regole più severe (valori gonfiati sui dati reali)

Sui dati reali di una settimana: ~140 punti con la sola cadenza, **669** con `SBH_BIRTH_YEAR` impostato (≈ 95 min al
giorno sopra soglia), 290 per Google Fit. Causa: il criterio FC dava punti a **qualsiasi minuto del giorno** con FC ≥ 50%
della FCmax (~90 bpm), cosa che nella vita quotidiana succede spesso anche senza attività (in piedi, stress, caffè); il
carry-forward di 5 minuti lo amplificava con campioni radi. Google Fit usa le stesse soglie ma **durante l'attività** e
con un'altra FCmax. Cambia così (sostituisce i punti 1, 3 e il carry-forward del punto 4 sopra):

1. **FCmax = 205,8 − 0,685 × età** (la formula di Google Fit), arrotondata **al bpm più vicino** (`int(x + 0,5)`: 36 anni →
   181,14 → 181; 40 → 178,4 → 178; 50 → 171,55 → 172). `HR_MAX_INTERCEPT` e `HR_MAX_SLOPE` in `services/heartpoints.py`.
   `SBH_HR_MAX` resta l'override. Per la stessa età la FCmax scende di ~3 bpm rispetto a 220 − età, quindi le soglie
   (50%/70%) scendono a 91/127 bpm a 36 anni.
2. **La FC dà punti solo nei minuti attivi.** Un minuto è **attivo** se:
   - ha almeno `ACTIVE_CADENCE_MIN` = **60** passi (dalla stessa ripartizione deduplicata della cadenza), **oppure**
   - cade dentro una **qualsiasi** `ExerciseSession` non cancellata, di qualunque tipo e origine (vera o automatica,
     manuale o avviata dall'app): copre palestra, bici, cyclette, nuoto, forza, che non producono passi.
   Fuori da questi minuti la FC non dà punti. **Il criterio cadenza (≥ 100 → 1, ≥ 130 → 2) non cambia e non ha filtri**;
   il minuto vale sempre il massimo dei due. Una sessione che attraversa la mezzanotte attiva anche i minuti del giorno
   dopo.
3. **Carry-forward** `HR_CARRY_MAX` da 5 a **2 minuti**.
4. **Dettaglio diagnostico**, senza migrazione: nel `detail` jsonb già presente di `daily_metric` si salvano per giorno
   `hr_points` (da FC, minuti attivi), `hr_points_ungated` (quanto avrebbe dato la FC **senza** la regola: serve per
   tarare le soglie e confrontare con Fit), `cadence_points`, `points_by_hr` (minuti in cui ha deciso la FC, cioè
   FC ≥ cadenza), `points_by_cadence` (minuti in cui ha punteggio solo la cadenza), `minutes_active`, `minutes_by_session`,
   `minutes_by_steps` (un minuto con passi e sessione conta in entrambi e una volta sola in `minutes_active`) e `rules`.
   `GET /heart/points` aggiunge `detail` a ogni punto (somma per giorno/settimana/mese/anno) e `/heart/points/week` ai
   giorni; il grafico lo mostra nella **tabella**, nel **CSV** e nella lettura da tastiera. Sono campi additivi.
5. **Ricalcolo automatico.** `RULES_VERSION` (ora 2) entra nella firma di configurazione (`sha1` di
   `v<versione>|<anno>|<fcmax>`, nessun valore personale in chiaro). Dopo il deploy il task di avvio ricalcola da solo
   **tutti** i giorni con firma diversa: in background (l'avvio non aspetta), a blocchi di 30 giorni con un commit per
   blocco e il lock di ingest preso solo per il blocco, quindi non satura il DB né blocca la sync. **Non serve il CLI.**
   Chi cambia le regole deve incrementare `RULES_VERSION`.
6. **Trigger di ingest:** aggiungere, modificare o cancellare un `ExerciseSession` ricalcola i punti del suo giorno (e del
   successivo): prima solo `HeartRate` e `Steps` li toccavano.
7. Le costanti nuove stanno nello stesso modulo e `GET /heart/points/rules` le restituisce (formula, minuti attivi, carry,
   versione): il pannello «Regole dei Punti cardio» si aggiorna da solo. Il seed ha mercoledì con 50 minuti di FC alta a
   riposo («stress»): nessun punto da FC.

Prima/dopo sul seed dev (FC alta a riposo il mercoledì): `hr_points_ungated` > `hr_points` nei giorni di stress.

## Limiti noti

- Senza FCmax i punti sono solo da cadenza e sottostimano le attività senza passi (ciclismo, nuoto, forza).
- L'età è per anno di nascita (±1 anno), la formula `205,8 − 0,685 × età` è approssimata: la FCmax reale può essere diversa
  (usare `SBH_HR_MAX`).
- La cadenza è una media sul record: una camminata registrata come un unico record di 40 minuti ha la stessa cadenza in
  ogni minuto; i record di 15 minuti sono il caso migliore.
- Un record di passi a cavallo della mezzanotte conta per il giorno in cui inizia; il carry-forward della FC non
  attraversa la mezzanotte.
- Il campione di FC di sorgenti diverse nello stesso minuto si media (non c'è priorità tra sorgenti per la FC).
