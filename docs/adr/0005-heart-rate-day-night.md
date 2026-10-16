# ADR 0005 — Frequenza cardiaca diurna e notturna

Stato: accettato · 2026-10-16 · Nessuna migrazione di schema (calcolo al volo su `health_sample` e `health_record`)

## Contesto

L'utente vuole distinguere la FC di giorno da quella di notte nella pagina Cuore: la FC notturna è un indicatore di recupero
molto più stabile della media delle 24 ore, che mescola sonno e attività. Serve una definizione unica, spiegabile e
verificabile, valida anche per le notti in cui il sonno non è stato registrato.

## Decisioni

1. **Notte = campioni `HeartRate` dentro le `SleepSession` registrate e non cancellate** (`deleted_at IS NULL`, con `end_ts`).
   Un pisolino registrato come sessione di sonno conta come sonno. Le sessioni sovrapposte (telefono e orologio che
   registrano la stessa notte) sono **unite** in un solo intervallo, altrimenti un campione verrebbe contato due volte.
2. **Fallback: giorno senza nessuna sessione di sonno → fascia fissa 23:00–07:00 Europe/Rome** (sera prima → mattina),
   con aritmetica DST-aware (il 25 ottobre la notte dura 9 ore). Nella risposta ogni intervallo dice se è `sleep` o `fixed`.
3. **Diurna = tutto il resto.**
4. **A quale giorno appartiene una notte:** al giorno del **risveglio**, come il sonno (PROJECT_GUIDE §5.2.3 e
   `daily.sleep_for_day`). Una sessione appartiene al giorno `local_date` del suo record (fine della sessione); la notte
   di fallback del giorno D va da D−1 alle 23:00 a D alle 07:00. Il campione delle 23:30 del 14 ottobre, se in una notte,
   conta quindi per il 15. I campioni diurni si attribuiscono al giorno locale del campione.
5. **Calcolo al volo, nessuna precomputazione.** Un endpoint dedicato, additivo e solo-dashboard:
   `GET /api/v1/heart/daypart?from&to&bucket=day|week|month` → intervalli notturni (`nights`), punti per bucket
   (`day`, `night`, con i conteggi `day_n`/`night_n`) e il riepilogo del periodo e del periodo precedente. Il contratto
   Reader → Writer (`1.0.0`) e `/series` non cambiano.
6. **Come si calcola in SQL.** Gli intervalli (qualche centinaio all'anno) vengono passati come array ordinati e ogni
   campione trova il suo intervallo con `width_bucket()` (ricerca binaria): costo O(campioni · log notti), senza join tra
   500 000 campioni e gli intervalli. I campioni di record cancellati sono esclusi, come per le medie giornaliere.
7. **Medie.** Per bucket giorno/settimana/mese la media è ponderata per campioni. I **KPI** usano la media delle medie
   giornaliere (stessa regola dei KPI esistenti del Report) e il confronto con il periodo immediatamente precedente di
   uguale lunghezza.
8. **Vista.** Con bucket 15 min/ora le notti sono **fasce di sfondo** (area a bassa opacità, etichetta «Notte», voce di
   legenda e nota testuale, mai solo colore). Con bucket giorno/settimana/mese la serie singola è **sostituita** da due
   serie: FC diurna (continua) e FC notturna (tratteggiata, altro colore), ciascuna con etichetta; tabella, CSV
   (con i campioni) e riepilogo testuale seguono. In quella vista banda min–max, media mobile e confronto non vengono
   mostrati. Se l'endpoint non risponde, il grafico torna quello normale.

## Limiti noti

- Dipende dalla qualità del sonno registrato: una sessione troppo corta o spostata classifica come diurni dei campioni
  in realtà notturni (e viceversa). Se un'app registra sonno **di giorno** (pisolini) quei campioni diventano notturni.
- Il fallback 23:00–07:00 è un'approssimazione: chi va a letto più tardi o si sveglia prima vede dei campioni da sveglio
  classificati come notte. La fascia è una costante (`FIXED_START`/`FIXED_END` in `services/daypart.py`), non una
  preferenza dell'utente.
- Le medie sono sui **campioni**: se l'orologio campiona più fitto di notte o di giorno, il peso delle ore cambia.
- Fuso e DST: i confini delle sessioni sono istanti UTC e non risentono del fuso; solo il fallback usa Europe/Rome.
- La media notturna di un giorno richiede almeno un campione nella notte: i giorni senza campioni non fanno media.
- Prestazioni: nessuna misura su dati reali. Con ~500 000 campioni/anno la query è un'unica scansione per tipo e
  intervallo di tempo (indice `ix_health_sample_type_ts`); se in futuro servisse, la precomputazione in `daily_metric`
  sarebbe la strada, ma non è stata necessaria.
