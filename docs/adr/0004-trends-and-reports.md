# ADR 0004 — Trend, confronto tra periodi e report

Stato: accettato · 2026-10-15 · Nessuna migrazione di schema (solo letture su `daily_metric`/`health_record`/`health_sample`)

## Contesto

L'obiettivo dell'utente è osservare **trend storici** di 12 metriche e **generare report**. Le API devono restare veloci
anche su anni di storico e i numeri mostrati devono coincidere con quelli ufficiali di Health Connect.

## Decisioni

1. **Sorgente dei trend = `daily_metric`** (ufficiale se presente, altrimenti calcolato). Le serie sub‑giornaliere (15 min / ora)
   esistono solo per ≤ 3 / ≤ 14 giorni e leggono i campioni grezzi.
2. **Aggregazione lato server.** Granularità `giorno | settimana (lunedì) | mese`. Il tetto è ~1000 punti: se la richiesta lo
   supera il bucket viene reso più grosso (`coarsened: true`, il bucket effettivo è nella risposta). Il client sceglie
   «automatica» = giorno fino a 120 giorni, poi settimana/mese.
3. **Opzioni calcolate dal server**, non dal browser: banda min–max (`band`), media mobile trailing (`ma`: 7 giorni /
   4 settimane / 3 mesi, ignorando i buchi), periodo precedente (`compare`: stessa lunghezza, immediatamente prima, allineato
   per posizione; per i bucket intraday per spostamento di tempo). Il client le mostra/nasconde senza nuove richieste.
4. **Giorno = giorno locale Europe/Rome** (già calcolato all'ingest con l'offset del record): i confini di giorno, settimana e
   mese non dipendono dal fuso del browser. Test su cambio ora legale.
5. **Pressione arteriosa**: sistolica/diastolica sono due valori di un solo record; `field=systolic|diastolic` legge la seconda
   dal `detail` di `daily_metric`.
6. **Allenamenti**: le sessioni duplicate tra app (stesso allenamento su telefono e orologio) si deduplicano (>50 % di
   sovrapposizione, vince la sorgente prioritaria, a parità quella con rotta). Le kcal della sessione sono le kcal attive
   deduplicate sovrapposte alla finestra; la FC media è la media dei campioni nella finestra.
7. **Report**: `/report` calcola in una chiamata statistiche del periodo, del periodo precedente, delta, giorno migliore/peggiore
   (solo dove «meglio» ha senso: FC a riposo → più bassa; peso e FC → nessun giudizio) e sparkline (giornaliere fino a ~93 giorni,
   poi settimanali/mensili). `/report/daily` restituisce la tabella giornaliera da cui il browser genera il CSV.
8. **Export CSV nel browser** (RFC 4180, virgola, punto decimale, BOM UTF‑8; le celle di testo che iniziano con `= + - @` sono
   neutralizzate contro la formula injection). Nessuna libreria PDF lato server: *Stampa / Salva PDF* del browser con un foglio di stile `@media print`.
9. **Fasce di riferimento** (pressione) sono solo «indicative», etichettate nel grafico e in una nota; nessuna diagnosi.

## Conseguenze

- Le risposte sono piccole (≤ ~1000 punti, ≤ 366 righe di tabella giornaliera per anno) e senza stato.
- Un periodo precedente prima dell'inizio dello storico è semplicemente vuoto (nessun confronto, mai uno zero inventato).
- Il selettore «Tutto» usa `/data/bounds` (primo giorno con una delle 12 metriche).
