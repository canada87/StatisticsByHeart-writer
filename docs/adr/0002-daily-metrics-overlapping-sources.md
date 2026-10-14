# ADR 0002 — Aggregati giornalieri e sorgenti sovrapposte

Stato: accettato · 2026-10-14

## Contesto

Fit, Feelfit e Withings scrivono tutte in Health Connect: gli stessi passi/sonno/peso/allenamenti possono
esistere più volte. Sommare tutti i record raddoppia i totali (PROJECT_GUIDE §5.2.4).

## Decisione

Due famiglie di valori in `daily_metric`, mai mescolate:

- **`hc_official`**: snapshot degli aggregati calcolati da Health Connect (`aggregate()`), inviati dal Reader.
  Applicano la priorità delle origini dati del sistema: è il valore «vero» da mostrare. Upsert per
  `(date, type)`, l'ultima `snapshot_at` vince, una snapshot più vecchia non sovrascrive.
- **`computed`**: calcolato dal writer dai record grezzi, **solo per i giorni toccati** da ogni ingest/cancellazione
  (e da un passaggio notturno di riconciliazione degli ultimi 3 giorni). Serve per dettagli e come ripiego.

Regole del calcolo `computed` (`app/services/daily.py`):

| Tipo di metrica | Regola |
|---|---|
| Cumulativi (`Steps`, `Distance`, calorie, …) | **Sottrazione di intervalli per priorità.** Le sorgenti sono ordinate (lista `SBH_SOURCE_PRIORITY`, poi per quantità di dati del giorno, poi per nome). Un record di una sorgente meno prioritaria conta solo per la quota del suo intervallo non già coperta dalle sorgenti più prioritarie (valore × frazione scoperta). Più sorgenti che coprono tempi *diversi* si sommano correttamente. |
| Sessioni (`SleepSession`, `ExerciseSession`, `MindfulnessSession`) | Una sessione sovrapposta per >50 % a sessioni già accettate di sorgenti più prioritarie è un duplicato e viene scartata. Sonno: «addormentato» = stadi tranne `awake`/`out_of_bed`/`awake_in_bed`; giorno = risveglio. |
| Istantanei (`Weight`, `RestingHeartRate`, …) | avg/min/max/count; stessa istantanea riportata da due app conta una volta (vince la sorgente prioritaria). `detail.last` = ultimo valore. |
| Serie (`HeartRate`, …) | avg/min/max/count su tutti i campioni; ripartizione per sorgente in `detail`. |

`detail` conserva sempre la ripartizione per sorgente (record grezzi / contati) per poter spiegare un totale.

## Alternative scartate

- **Prendere la sola sorgente con più dati:** perde i tratti coperti solo dall'altra (smartwatch tolto, telefono
  in tasca).
- **Spezzare i record a mezzanotte:** complessità non giustificata; l'ufficiale HC è il riferimento e un
  intervallo di 15 minuti a cavallo della mezzanotte sposta al massimo qualche decina di passi.
- **Dedupe in SQL:** logica troppo intricata; i volumi giornalieri (centinaia di record) rendono Python adeguato.

## Conseguenze

- Cambiare `SBH_SOURCE_PRIORITY` non ricalcola da solo lo storico: `python -m app.cli recompute --days N`.
- Il record resta in un solo giorno (inizio; sonno: fine): coerente con ciò che fa HC per le sessioni.
