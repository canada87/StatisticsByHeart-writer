# Changelog — StatisticsByHeart Writer

Cosa cambia a ogni versione, in breve. I dettagli e le motivazioni stanno negli ADR (`docs/adr/`). Le versioni con
**migrazione del database** sono segnalate: prima di aggiornare fare un `pg_dump` (comando nel README).

Ogni nuova versione aggiunge qui una voce, nello stesso commit che aumenta la versione.

## 0.9.0 — 2026-10-31 · ⚠️ migrazione `0005`
- **Esclusione manuale di misure errate** (peso, pressione, SpO₂, FC a riposo, HRV, sonno, allenamenti), per il caso
  del peso di un altro profilo importato da Google Fit. La misura non si cancella: sparisce da grafici, KPI, medie,
  Report (PDF e CSV), aggregati e calcoli derivati, e resta ripristinabile.
- Si esclude da un punto del grafico (clic, tocco o tastiera) o da una riga di «Mostra tabella», con motivo facoltativo,
  conferma e «Annulla». Nessun segno nei grafici: le esclusioni stanno in **Sync / Dati › Dati esclusi**, con «Ripristina».
- L'esclusione sopravvive alle sincronizzazioni e non va in errore se Health Connect cancella il record. ADR 0011.

## 0.8.1 — 2026-10-17
- Punti cardio più fedeli: FC max = 205,8 − 0,685 × età; la FC dà punti solo nei minuti attivi; riporto di 2 minuti;
  dettaglio diagnostico del calcolo.

## 0.8.0 — 2026-10-17 · ⚠️ migrazione `0004`
- Preferenze salvate sul server: si sceglie cosa mostra il Report (a schermo e nel PDF) e la scelta vale su ogni
  dispositivo.
- PDF del Report senza intestazione e piè di pagina del browser.
- Allarme «sync ferma» per Home Assistant: endpoint dedicato e token con *scope* ristretto, YAML pronto nel README.
  Stato dell'allarme visibile nella scheda Sync. Contratto API 1.2.0. ADR 0010.

## 0.7.0 — 2026-10-17
- Report esteso: grafici grandi a tutta larghezza (mensili se il periodo copre più mesi), tabelle mese su mese con i
  mesi parziali segnalati, FC diurna e notturna, Punti cardio, allenamenti veri per tipo, CSV mensile.
- Stampa: tabelle lunghe spezzate tra le righe, niente pagine quasi vuote; grafici mensili come media per giorno o
  per notte. ADR 0009.

## 0.6.1 — 2026-10-17
- Punti cardio per giorno (a 7G/30G) con linea di riferimento 150/settimana, indicativa e non un obiettivo.

## 0.6.0 — 2026-10-16
- **Punti cardio** (stile Google Fit / AHA), calcolati minuto per minuto da battiti e cadenza dei passi, senza doppi
  conteggi tra sorgenti. Anello settimanale verso 150 in Panoramica, grafico a barre e pannello regole in Cuore.
  Configurabili con `SBH_BIRTH_YEAR` / `SBH_HR_MAX`. ADR 0008.

## 0.5.3 — 2026-10-16
- Scheda **Spazio e limiti** in Sync / Dati (sola lettura): dimensione del DB e delle tabelle, crescita stimata,
  disco, limiti e retention. ADR 0007.

## 0.5.2 — 2026-10-16
- Allenamento vero solo se dura almeno 15 minuti; pannello delle regole nella pagina Attività.

## 0.5.1 — 2026-10-16
- Una camminata non è un allenamento vero; il motivo del verdetto è mostrato accanto.

## 0.5.0 — 2026-10-16 · ⚠️ migrazione `0003`
- **Allenamenti veri**: classificazione automatica (copertura FC, GPS, avviato dall'utente) e verdetto manuale
  modificabile. La FC diurna esclude gli allenamenti veri e i 30 minuti successivi; il Report conta solo quelli veri.
- Tracce GPS degli allenamenti ricevute dal Reader. Contratto API 1.1.0 (solo aggiunte). ADR 0006.

## 0.4.0 — 2026-10-16
- Frequenza cardiaca **diurna e notturna** (la notte è la sessione di sonno, altrimenti 23–07), notti ombreggiate nel
  grafico. ADR 0005.
- Frecce per spostare l'intervallo avanti e indietro (anche nell'URL); granularità «Ora» fino a 31 giorni; grafici
  navigabili da tastiera con lettura dei valori.

## 0.3.0 — 2026-10-15
- Pagine Cuore, Sonno, Attività, Corpo e **Report** (stampa/PDF dal browser, CSV), solo le 12 metriche scelte.
- Grafici di trend: granularità giorno/settimana/mese, media mobile 7 giorni, confronto con il periodo precedente,
  tabella, CSV. Intervallo fino a «Tutto». ADR 0004.

## 0.2.0 — 2026-10-15 · ⚠️ migrazione `0002`
- Prima dashboard: login, Panoramica, Sync / Dati (sync, inventario, riconciliazione con i totali ufficiali di
  Health Connect).
- Immagine pubblicata su GHCR da GitHub Actions; compose di produzione senza build e senza servizio di backup.

## 0.1.0 — 2026-10-14 · migrazione `0001`
- Writer core: schema PostgreSQL, ingest idempotente (record, cancellazioni, aggregati ufficiali, report di sync),
  aggregati giornalieri, token di ingest, login admin, contratto API v1, Docker. ADR 0001–0003.
