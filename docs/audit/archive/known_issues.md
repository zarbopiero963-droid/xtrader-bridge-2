# Problemi noti — XTrader Signal Bridge

> Documento di baseline (PR-00). Consolida l'audit di Codex e l'audit
> indipendente eseguito (parser lanciato realmente su 4 casi).
> Ogni voce è mappata alla PR che la chiude in `roadmap.md`.

Legenda severità: 🔴 critico · 🟠 medio-alto/alto · 🟡 medio/basso.

---

## Tabella consolidata

| # | Area | Stato attuale | Severità | Chiusa da |
|---|---|---|---|---|
| 1 | Validazione segnale prima di scrivere CSV | Assente (scrive anche quota<1.0 / EventName vuoto) | 🔴 Critico | PR-01, PR-06, PR-10 |
| 2 | Sincronizzazione write/clear (race) | Assente, nessun lock | 🔴 Alto | PR-05, PR-16 |
| 3 | Parser P.Bet. (formato README) | Non funziona senza emoji | 🔴 Alto | PR-09 |
| 4 | Formato CSV README vs codice | Divergente (Stake/Timestamp) | 🔴 Alto | PR-01 |
| 5 | Timestamp anti-duplicato | Non implementato | 🔴 Alto | PR-01 (fuori CSV) + PR-15 |
| 6 | Lock file / scrittura atomica | Non implementato | 🟠 Medio-alto | PR-05 |
| 7 | `.gitignore` mancante | Mancante (rischio leak token/config) | 🟠 Medio-alto | **PR-00** |
| 8 | Filtro `chat_id` | Permissivo se vuoto | 🟠 Medio | PR-11, PR-12 |
| 9 | `TELEGRAM_OK` mai controllato | Confermato | 🟠 Medio | PR-03, PR-11 |
| 10 | Validazione input GUI | Incompleta + `int()` non protetto | 🟠 Medio | PR-13 |
| 11 | Errori silenziati (`except: pass`) | Confermato | 🟡 Medio | PR-11, PR-14 |
| 12 | Stake / MinPrice / MaxPrice | Non valorizzati | dipende da XTrader | PR-01, PR-13 |
| 13 | Test automatici | Assenti | 🟠 Alto | PR-02 + ogni PR |
| 14 | README markdown | Rotto + incoerente | 🟡 Basso | PR-01, PR-20 |
| 15 | Build EXE | Presente, non eseguita qui | 🟡 Basso | PR-18 |

---

## Problemi REALI (nel codice) vs problemi solo-README

### Reali (nel codice, verificati eseguendo le funzioni)

- **#1 Nessuna validazione**: `build_csv_row()` + `write_csv()` scrivono **sempre**
  una riga. Test reale: `Quota 0,5` → `Price='0.5'` (quota invalida <1.01) scritta
  comunque. Con il messaggio del README, `EventName` esce **vuoto** e la riga viene
  scritta lo stesso. Viola l'invariante di CLAUDE.md "nessuna scrittura se il segnale
  non è valido".
- **#2 Race write/clear**: `_process()` gira sul thread del bot (asyncio),
  `_do_clear()` su un `threading.Timer` separato. Nessun lock condiviso → se un
  segnale arriva mentre il timer scatta, le scritture possono interlacciarsi
  (CSV parziale) o il clear può cancellare un segnale appena scritto.
- **#3 Parser dipendente da emoji**: senza `🏆 🆚 ⚽ ⌚` i campi restano vuoti.
- **#6 Scrittura non atomica**: `open(path, 'w')` tronca il file; XTrader può leggerlo
  a metà scrittura.
- **#8 chat_id vuoto = ascolta tutto**: `if cid and str(msg.chat_id) != cid`.
- **#9 `TELEGRAM_OK`**: definito a riga 21/23, mai usato nel flusso (grep confermato).
- **#10 `int()` non protetto**: `int(self._e_delay.get()...)` in `_save_config` lancia
  `ValueError` su input non numerico, propagato in `_start`.
- **#11 Errori silenziati**: `except Exception: pass` su load/save config e stop.

### Solo-README (il codice non li implementa, il README li promette)

- **#4 CSV con `Stake` e `Timestamp`**: il README mostra colonne che il codice non
  genera. → Risolto in PR-01 ridefinendo il **contratto** (Stake gestito in XTrader,
  niente Timestamp come colonna CSV).
- **#5 "Timestamp univoco anti-duplicato"**: promesso nel README, assente nel codice.
  → La deduplica diventa interna (message_hash, PR-15), non una colonna CSV.
- **#5/lock "Lock file durante la scrittura"**: promesso nel README, assente.
  → Risolto come scrittura atomica in PR-05.

---

## Decisione contratto CSV (input del proprietario)

Per XTrader il CSV segue il formato dei **CSV di esempio reali** del team XTrader
(fonte di verità: `docs/xtrader_csv_contract.md`). Header reale a **14 colonne**:

```text
Provider,EventId,EventName,MarketId,MarketName,MarketType,SelectionId,SelectionName,Handicap,Price,MinPrice,MaxPrice,BetType,Points
```

- **`Stake`** NON è colonna CSV: è gestito in XTrader nell'azione "Piazza Scommessa su Segnali".
- **`Timestamp`** NON è colonna CSV: la deduplica (pianificata, PR-15) è interna al bridge.
- **`BetType`** in italiano: `PUNTA` (back) / `BANCA` (lay).
- **`Points`** vuoto di default; **`Handicap`** = `0`.
- Encoding `utf-8-sig` (BOM) + `quoting=QUOTE_ALL`.
- Validazione XTrader: `MarketId + SelectionId` (ID_ONLY) **oppure**
  `EventName + MarketType + SelectionName` (NAME_ONLY). Con i nomi, la lingua del CSV
  deve coincidere con quella impostata nella fonte Segnali di XTrader (italiano).

> Il contratto a 12 colonne / `BACK`/`LAY` / `Points="1"` indicato inizialmente è
> **superato** da questo, dopo aver ricevuto gli esempi reali XTrader.

Questa decisione supera l'esempio CSV attuale del README ed è formalizzata in PR-01.
