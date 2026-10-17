# ADR 0009 — Report esteso: medie del periodo, mese su mese, grafici grandi

Stato: accettato · 2026-10-17 · Nessuna migrazione (letture su `daily_metric`, `health_sample`, `health_record`)

## Contesto

Il Report (ADR 0004) riassumeva i 12 indicatori con medie, totali e confronto. L'utente lo usa soprattutto in PDF e
vuole: grafici più grandi, la FC divisa in diurna e notturna e i Punti cardio, una lettura mese su mese di tutto il
periodo, e che gli allenamenti contino solo se veri. Tutto sul periodo scelto nel selettore del Report.

## Decisioni

1. **Estensione additiva di `GET /api/v1/report`**, un solo endpoint. Le 12 metriche e tutte le loro statistiche restano
   identiche (l'elenco `metrics` non cambia). Nuovi campi:
   - `extra_metrics`: `hr_day`, `hr_night` e `heart_points`, con la stessa forma di una metrica (medie/totali, periodo
     precedente, variazione, sparkline). **FC diurna/notturna con la stessa definizione di `/heart/daypart`** (ADR
     0005/0006): notte = sessioni di sonno (altrimenti 23–07), diurna = il resto **senza allenamenti veri e i 30 minuti
     dopo**; la media del periodo è la media delle medie giornaliere, come per le altre metriche.
   - `points`: Punti cardio (ADR 0008) del periodo: totale, media a settimana (`totale / (giorni / 7)`), settimane
     intere (lunedì–domenica, concluse) e quante sopra l'obiettivo di 150, periodo precedente, avviso se manca la FCmax.
   - `workouts.by_type_detail`: allenamenti **veri** per tipo, numero e tempo, dal più lungo.
   - `monthly`: la tabella mese su mese (punto 2).
2. **Mese su mese, calcolato lato server** riusando le serie giornaliere che il Report calcola già (nessuna query in più
   per le 12 metriche): per le metriche «media» (FC, FC diurna, FC notturna, FC a riposo, HRV, SpO₂, sonno per notte,
   peso, pressione sistolica e diastolica) il valore del mese è la **media dei valori giornalieri**; per i totali (passi,
   distanza, calorie attive e totali, Punti cardio, **numero e tempo degli allenamenti veri**) è la **somma del mese**.
   Ogni riga dice quanti giorni del mese sono nel periodo (`days`) e se il mese è **parziale** (il periodo non copre tutto
   il mese: il primo, l'ultimo, il mese in corso). Un periodo di un solo mese dà una riga non parziale; la tabella non si
   mostra per una sola settimana dentro un mese (ripeterebbe il riepilogo). Due tabelle: medie giornaliere (≤10
   colonne) e totali del mese (≤7), perché 17 colonne non starebbero in una pagina A4 verticale.
3. **Solo allenamenti veri**, secondo le regole attuali e i verdetti manuali (ADR 0006): numero e tempo del periodo,
   per mese e per tipo. Il testo rimanda alle regole nella pagina Attività.
4. **CSV.** Il CSV giornaliero (`/report/daily`) ha le colonne nuove `hr_day`, `hr_night` (subito dopo `hr_max`) e
   `heart_points`; il **CSV mensile** è generato dal browser dalla stessa tabella (`mese`, `giorni_nel_periodo`,
   `parziale`, una colonna per chiave): nessun endpoint in più.
5. **Grafici grandi.** Sotto le tabelle, un grafico per riga a tutta larghezza (340 px a schermo, almeno 90 mm in stampa),
   solo per le metriche con dati: passi, FC diurna/notturna, FC a riposo, HRV, SpO₂, sonno, peso, pressione, Punti cardio.
   Se il periodo copre almeno **3 mesi** la granularità di partenza è **mensile** (il selettore resta); altrimenti quella
   automatica del grafico. In stampa ogni grafico ha `break-inside: avoid` (mai tagliato fra pagine). Il canvas ECharts è
   disegnato con la palette scura dell'HUD: in stampa si **inverte** (`filter: invert(1) hue-rotate(180deg)`) così il testo
   chiaro diventa scuro su carta bianca; il significato non dipende dal colore: FC diurna continua e notturna tratteggiata,
   linee dell'obiettivo con etichetta, riepilogo testuale e tabella alternativa per ogni grafico.
6. **Prestazioni.** Un periodo «Anno» o personalizzato fino a 3660 giorni usa le stesse query a giorno del Report di
   prima più una per la FC diurna/notturna (una sola scansione con ricerca binaria) e una per i Punti cardio; un test
   misura la risposta su 3660 giorni (< 30 s, in pratica pochi secondi) e verifica ~120 righe mensili.

## Correzioni prima del rilascio (0.7.0)

1. **Stampa: le tabelle lunghe si spezzano tra le righe.** Un `break-inside: avoid` sul pannello «Riepilogo del periodo»
   (più alto di una pagina) lo spingeva alla pagina 2 e lasciava la 1 quasi vuota. Ora i pannelli del riepilogo e del
   mese su mese hanno `break-inside: auto`, le intestazioni si ripetono a ogni pagina (`thead { display:
   table-header-group }`), le righe restano intere (`tr { break-inside: avoid }`); `avoid` resta solo sui singoli
   grafici e sui blocchi piccoli. Il titolo «Andamento nel periodo» non forza più un'interruzione di pagina. La
   verifica è fatta sul PDF reale, pagina per pagina (riempimento di ogni pagina).
2. **Grafici mensili = media al giorno, non totale.** Con granularità mensile la somma dei passi, della distanza, delle
   calorie o delle ore di sonno di un mese rende i mesi parziali dei «crolli» e il sonno un numero senza senso (792 h).
   `GET /metrics/{type}/series` accetta `per_day=true` (additivo): per i bucket **settimana e mese** il valore è la
   **media semplice dei valori giornalieri** dei giorni con dati (non pesata per numero di record), e ogni punto riporta
   `days` (i giorni con dato; per il sonno sono le notti). Il Report lo chiede per tutti i suoi grafici; l'asse dice
   «media al giorno», «kcal/giorno (media)», «h/notte (media)»; il riepilogo non scrive più «Totale»; la tabella e il CSV del
   grafico hanno la colonna «Giorni/Notti con dati». Le pagine del cruscotto non cambiano (restano totali).
3. **Tabella mese su mese:** il sonno è la **media a notte** (era una somma per errore) e c'è la colonna «Notti con
   dati»; gli altri totali (passi, distanza, calorie, Punti cardio, allenamenti) restano **totali del mese**, dichiarati
   come tali nell'intestazione e con i mesi parziali segnalati.
4. **Punti cardio per mese/anno:** sono somme per definizione; i periodi incompleti (primo mese parziale, mese in corso)
   si disegnano **tratteggiati e con asterisco** con una nota, così non sembrano un calo. (Per i punti la settimana resta
   somma: l'obiettivo è settimanale.)

## Limiti noti

- Le medie mensili sono medie di medie giornaliere: un giorno con pochi campioni pesa come uno con molti.
- Un mese parziale non è confrontabile con uno intero per i totali (passi, punti): è segnalato, non normalizzato.
- L'inversione colori in stampa è un'approssimazione: le tinte stampate non sono quelle dello schermo.
- I grafici sono canvas: in stampa hanno la risoluzione dello schermo (non vettoriale).
- Non ho potuto ispezionare visivamente ogni pagina del PDF (solo la stampa a pagina intera e le regole CSS di
  interruzione); il numero di pagine dipende dal periodo.
