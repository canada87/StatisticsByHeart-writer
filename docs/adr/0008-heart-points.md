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

## Limiti noti

- Senza FCmax i punti sono solo da cadenza e sottostimano le attività senza passi (ciclismo, nuoto, forza).
- L'età è per anno di nascita (±1 anno), la formula `220 − età` è approssimata: la FCmax reale può essere diversa
  (usare `SBH_HR_MAX`).
- La cadenza è una media sul record: una camminata registrata come un unico record di 40 minuti ha la stessa cadenza in
  ogni minuto; i record di 15 minuti sono il caso migliore.
- Un record di passi a cavallo della mezzanotte conta per il giorno in cui inizia; il carry-forward della FC non
  attraversa la mezzanotte.
- Il campione di FC di sorgenti diverse nello stesso minuto si media (non c'è priorità tra sorgenti per la FC).
