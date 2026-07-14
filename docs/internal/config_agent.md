# Assistente di configurazione — architettura e modello di sicurezza (#41)

> Documento **interno**. L'assistente è uno strumento **personale del proprietario** per
> configurare il bridge a linguaggio naturale, **non** una chat per utenti finali. Vedi la
> issue #41 per lo scopo e lo split in PR.

Questa pagina descrive lo **scheletro headless** introdotto dalla **PR-1** (`xtrader_bridge/config_agent.py`):
client Anthropic *tool-use* iniettabile, registry dei tool con classificazione dei permessi, e le
**guardie di sicurezza hard-block**. GUI (PR-3), persistenza cronologia (PR-2) e tool di
**scrittura** config gated (PR-4) arrivano nelle PR successive.

## Componenti (PR-1)

- **`AgentTool`** — un tool: `name` / `description` / `input_schema` (spec function-calling) +
  `permission` (`READ_ONLY` | `WRITE_CONFIG`) + `handler(input) -> str`.
- **`ToolRegistry`** — l'**unico** punto da cui un tool viene eseguito. Espone al modello solo le
  spec permesse (`tool_specs`), esegue le guardie e registra ogni chiamata in `audit_log`.
- **Tool sola-lettura**: `get_config_state` (config **redatta**), `get_health` (semafori
  `health_check`), `list_parsers` (PR-1) e `get_setup_status` (**PR-5**: checklist di prima
  configurazione — token/chat/parser/CSV/modalità come booleani `done`+label, **nessun segreto** —
  riusa `wizard.final_checklist`). Esercitano funzioni reali del progetto.
- **`RealAnthropicClient`** — client verso l'Anthropic Messages API con **lazy import** di
  `anthropic` (dipendenza opzionale, fail-safe come `keyring` in `token_store`). **Non** usato nei
  test: `ConfigAgent` accetta qualunque client con `create_message(system, messages, tools)`.
- **`ConfigAgent.run_turn`** — il loop tool-use: manda il messaggio, risolve le chiamate a tool
  (tutte guardate dal registry), ritorna quando il modello smette di chiamare tool o al **cap**
  (`MAX_TOOL_ITERATIONS`).

## Fonti di conoscenza (issue #41)

1. **Tools (azioni)** — funzioni interne: sempre esatte perché sono il codice vero.
2. **Documenti (comprensione)** — guide `docs/user/` (fasi successive).
3. **Stato live (contesto)** — i tool sola-lettura sopra: «sa dove siamo» dal programma vivo.

## Invarianti di sicurezza — hard block (BLOCCATE SEMPRE)

L'agente **non può MAI**, nemmeno su ordine esplicito:

- piazzare scommesse o comunicare con XTrader/Betfair;
- indebolire/aggirare il **filtro chat** (resta fail-closed);
- avviare il **listener LIVE** o la **modalità reale**, o scrivere il **CSV operativo**, senza la
  conferma frictionful esistente (`bridge_mode`);
- rivelare/esportare segreti (API key Anthropic, bot token, chat ID, certificati);
- usare il web o eseguire shell/codice arbitrario.

Meccanismi (fail-closed, testati in `tests/safety/test_config_agent_41.py`):

| Difesa | Dove |
|---|---|
| Denylist `FORBIDDEN_TOOLS` — nomi-capacità mai eseguibili | `ToolRegistry.dispatch` (punto 1) |
| Un tool con nome in denylist **non è nemmeno registrabile** | `ToolRegistry.register` |
| Tool sconosciuto → rifiuto | `dispatch` (punto 2) |
| Scrittura config **gated** (`allow_writes=False` in PR-1; i write-tool non sono nemmeno **offerti** al modello) | `dispatch` (punto 3) + `tool_specs` |
| **Redazione segreti** su OGNI contenuto che torna al modello — risultati **e messaggi di rifiuto** | `dispatch` via `event_log.redact_secrets` |
| **Audit redatto all'ingresso**: `audit_log` e il `logger` non conservano mai `tool_input`/nomi in chiaro | `ToolRegistry._audit` / `_safe_repr` |
| `get_config_state` maschera token/API key/chat ID | `_redact_config` |
| Loop tool-use protetto da **cap** anti-loop | `ConfigAgent.run_turn` / `MAX_TOOL_ITERATIONS` |
| Un handler che solleva **non** crasha l'agente | `dispatch` (best-effort) |

Ogni tentativo rifiutato è annotato in `ToolRegistry.audit_log` e notificato al `logger`
iniettabile (l'app reale ci aggancerà `event_log`).

## Segreti

- **API key Anthropic** e **bot token** vivono **solo nel keyring del SO** (`token_store`:
  `save_api_key`/`load_api_key`/`delete_api_key`, voce distinta dal token). **Mai** nel
  repository, in `config.json` in chiaro, o nella cronologia conversazione (che sarà redatta in
  PR-2). Nessun fallback plaintext.

## Rete e cronologia

- L'**unica** connessione in uscita prevista è la chiamata HTTPS ad Anthropic (il canale col
  modello). Nessun web/browser/fetch: quelle capacità sono nella denylist hard-block.
- Il **messaggio dell'utente** viene inviato al modello: è il canale sanzionato (l'assistente deve
  capire l'ordine per eseguirlo). Ciò che **non** deve mai persistere in chiaro sono l'**audit**
  (redatto qui, PR-1) e la **cronologia conversazione** (redazione in **PR-2**, con `log_privacy`/
  `redact_secrets`). Per le operazioni di **scrittura** (PR-4) il valore sensibile va passato al
  tool **senza** doverlo esporre nel testo persistito: il design del write-path lo definisce lì.

## Persistenza cronologia (PR-2)

`ConversationHistory` rende l'assistente «consapevole di dove siamo» tra un avvio e l'altro.

- **In RAM**: `messages` nel formato di `ConfigAgent` (la sessione ha il contesto pieno).
- **Su disco**: `config_store.config_dir()/assistant_history.json` (%APPDATA%/$XDG_CONFIG_HOME),
  scritto in modo **atomico** (`atomic_io.atomic_write_json`) e **sempre REDATTO**.
- **Redazione profonda** (`_deep_redact`): ogni foglia dei messaggi (testo utente/assistente,
  `tool_use.input`, `tool_result.content`, nomi) passa per `event_log.redact_secrets`; la
  struttura è preservata. Copre anche gli **scalari numerici** (un `chat_id` come `int` viene
  redatto, un numero legittimo resta) e le **chiavi** dei dict (un segreto usato come chiave non
  resta in chiaro). `save(extra_secrets=[...])` maschera i segreti di sessione (es. il `chat_id`)
  per **replace LOCALE** — **senza** toccare il registro globale di `event_log`, così un segreto
  già registrato dall'app non viene mai de-registrato per sbaglio (niente leak/race). **API key/
  bot token/chat non finiscono mai in chiaro nel file.**
- **Fail-safe** in `load`: file assente, JSON corrotto o forma inattesa → cronologia **vuota**
  (l'assistente riparte pulito, non crasha).
- **Redazione API key**: `event_log.redact_secrets` ora maschera anche il pattern `sk-ant-...`
  (euristica), così la chiave Anthropic è coperta **anche prima** della registrazione.

Flusso del chiamante (la GUI, PR-3):

```python
h = ConversationHistory.load()
turn = agent.run_turn(testo_utente, history=h.messages)
h.replace(turn.messages)
h.save(extra_secrets=[cfg.get("chat_id")])
```

Limite onesto: i literal di sessione < 8 caratteri (`_MIN_EXTRA_SECRET_LEN`) non sono mascherati
per-literal (guardia anti-frammento, per non redigere sottostringhe banali); i chat ID reali
Telegram (`-100…`) sono lunghi e coperti, e il bot token / `sk-ant-...` restano coperti dai pattern
di `redact_secrets` a prescindere.

## Tab GUI + ciclo di vita (PR-3)

- **`config_agent_controller.AgentController`** (logica, testata): macchina a stati
  `STOPPED`/`RUNNING`/`ERROR`. `enable()` richiede la API key (keyring) — assente → `ERROR`, l'agente
  resta spento; carica la cronologia persistente (redatta) e avvia il worker. `stop()`/`teardown()`
  fermano il worker con un **join a timeout** (best-effort limitato: se un turno reale è in volo il
  thread daemon esce appena la chiamata rientra). Ogni `enable()`/`stop()` avanza un **epoch** di
  sessione **legato** al worker: un turno che completa dopo lo Stop (o dopo un re-enable) è **stale**
  e viene **scartato** (niente save, niente risposta-fantasma, nessuna mutazione della nuova
  sessione — pattern identico al `_listener_epoch` del bot). `submit(text)` accoda un messaggio;
  **rifiutato** se non `RUNNING` (guardia). Ogni turno: `run_turn` → `history.replace` →
  `history.save(extra_secrets=[chat_id])` (best-effort su errore disco). Client Anthropic iniettabile.
- **Concorrenza (invariante #64):** l'aggiornamento dei **dati** (`replace`+`save`) è atomico sotto
  `_history_lock` rispetto all'epoch; l'`_emit` degli eventi (`turn`/`warning`) avviene **fuori dal
  lock** — una callback `on_event` tenuta sotto lock deadlockerebbe se l'handler attende un altro
  thread che chiama `stop()`/`enable()` (o vi rientra). Per non mostrare la risposta di una sessione
  già chiusa, ogni evento porta l'`epoch`: il **consumer** (GUI, thread singolo) lo confronta con
  `controller.current_epoch()` (`config_agent_gui.is_stale_event`) e **scarta** i `turn`/`warning`
  non correnti — rete di sicurezza consumer-side, race-free senza lock in emit.
- **`config_agent_controller.AgentWorker`** (testato): loop su `queue.Queue` con **sentinella** di
  stop; un turno che solleva **non** uccide il loop (errore restituito come turno). `run_pending()`
  esegue il loop in modo **sincrono** per i test (nessun thread reale). `stop()` fa il **join** del
  thread (cross-thread) e ritorna `True` se terminato — o se invocato **dallo stesso thread worker**
  (handler rientrante): lì non fa join di sé, la sentinella è già in coda e il loop uscirà al ritorno
  (auto-fermante, ritorna `True` così i call-site non lo leggono come «stop fallito»). Ritorna
  `False` **solo** su timeout cross-thread con thread ancora vivo (turno reale in volo): il
  riferimento non viene azzerato, per non creare un doppio worker.
- **`config_agent_gui`** (view sottile): helper puri testati (`state_label`/`state_color`/
  `input_enabled`/`messages_to_transcript`) + `AssistantPanel` (widget: campo API key mascherato,
  Abilita/Stop, indicatore stato, trascritto, input) — **verifica manuale**. Marshalla gli eventi del
  controller sul thread GUI con `after(0, …)`.
- **`app.py`**: aggiunge la tab **«🤖 Assistente»** (best-effort) e il **teardown** del pannello in
  `_on_close` (stop+join, coerente col bot thread e col single-instance lock).

**Sicurezza (PR-3):** `enable()` accende **solo la chat**; le azioni safety-critical restano
hard-block; la API key vive solo nel keyring; la cronologia su disco resta sempre redatta. *(La
scrittura config, prima disattivata in PR-3, è ora abilitata GATED in PR-4 — vedi sotto.)*

## Scrittura config GATED (PR-4)

Il controller costruisce ora l'agente con **`allow_writes=True`**: l'assistente può **proporre**
modifiche di configurazione, ma **solo** attraverso il tool `set_config_value`, **solo** su un
piccolo insieme di chiavi **non safety-critical**, e **la scrittura vera la fa l'utente** (non il
modello). Tutte le altre guardie restano attive (hard-block `FORBIDDEN_TOOLS`, redazione segreti,
cap anti-loop, cronologia redatta).

- **Allowlist** (`config_agent.WRITABLE_CONFIG_KEYS`): `theme` (dark/light), `app_language`
  (IT/EN/ES), `clear_delay`, `confirmation_timeout`, `max_signal_age` (interi, con **bound**
  validati). `max_signal_age` ha **min > 0**: l'assistente **non** può disattivare il filtro
  anti-segnale-stantio.
- **Denylist** (`config_agent.WRITE_FORBIDDEN_KEYS`, difesa in profondità): `bot_token`/keyring,
  `chat_id`/`source_chats`/`parser_by_chat`/`parser_list_by_chat`/`xtrader_notification_chat_id`
  (**filtro chat**), `bridge_mode`/`dry_run`/`csv_path`/`csv_language` (**modalità/CSV = contratto
  XTrader**), `queue_mode`/`max_active_signals`/`max_per_day` (**scommesse simultanee**),
  `auto_start_listener`, `debug_message_payload`, `active_parser` e altre → **rifiutate anche su
  ordine esplicito**, con audit.
- **Validazione stretta**: un valore fuori dominio/bound è **rifiutato** con messaggio, **mai**
  coerciuto in silenzio (a differenza di `config_store._migrate`, fail-closed sul *load*).
- **Gate di conferma SERVER-SIDE** (review #65 GPT-5.5/Fugu/Fable): il tool **non scrive mai**.
  Valida e chiama `on_proposal(key, new, old)` → il controller registra la modifica **pendente**
  (legata all'`epoch`) ed emette l'evento `pending`; la GUI mostra un banner «✅ Applica / ✖ Annulla».
  **Solo** `AgentController.apply_pending()`, invocato dal **pulsante dell'utente** (thread GUI),
  scrive. Così un `confirm` allucinato/indotto (prompt injection) **non** può applicare nulla: al
  massimo propone. La conferma è uno **stato server-side legato a chiave/valore/epoch**, non un
  booleano deciso dal modello.
- **Anti-TOCTOU e fail-safe** (Fable/Fugu #65): `apply_pending()` ri-legge la config sul thread GUI
  (come «💾 Salva Config»), opera su una **copia** e tocca **solo** la chiave proposta. Difese:
  - **niente fallback a `{}`**: se il load non dà un dict valido e non vuoto → **abortisce** (mai
    scrivere una config quasi vuota che azzererebbe chat_id/csv_path/bridge_mode/limiti); il pending
    resta per il retry;
  - **anti-clobber della chiave proposta**: si scrive solo se il valore attuale coincide ancora con
    quello su cui si basava la proposta (`old`); un cambio **concorrente** della stessa chiave (es.
    GUI «Salva») **non** viene sovrascritto — proposta stantia annullata con avviso;
  - il loader passato dall'app è la **config viva RAW** (`self._config`), **non** la vista redatta dei
    tool read-only → nessun `***` persistito sui segreti;
  - un saver che **solleva** è trattato come save fallito (nessun crash del thread GUI);
  - il banner di conferma è governato **consumer-side**: il controller emette `pending_cleared`
    fuori dal lock (invariante anti-deadlock #64) e la GUI, ricevendolo, **rilegge**
    `controller.pending()` e mostra/nasconde di conseguenza — se nel frattempo è subentrata una
    proposta più nuova la ri-mostra, altrimenti nasconde. Race-free rispetto all'ordine degli eventi
    (stessa filosofia di `is_stale_event`), senza tenere il lock attraverso l'emit.
  Tutte le scritture di `config.json` (assistente e GUI) avvengono sul thread Tk → **serializzate**.
  Il `bot_token` non è tra le chiavi scrivibili e resta nel keyring. Un save fallito riporta
  l'errore, mai un falso «Fatto». La proposta è scartata se l'`epoch` è cambiato (Stop/Enable) o al
  `stop()`.

Test hard: `tests/safety/test_config_agent_write_41.py` (denylist/allowlist/validazione, il tool
**non scrive né mette in pending** per chiavi vietate/valori invalidi, propone la forma canonica,
schema senza `confirm`, gate `allow_writes`) + controller (`proposta_non_scrive_finche_utente_non_applica`,
`apply_pending_senza_proposta`, `cancel_pending`, `stop_scarta_la_proposta`, `apply_pending_stale_epoch`,
`proposta_safety_critical_non_mette_in_pending`) + GUI (`pending_text`).

## Guida alla prima configurazione (PR-5)

L'assistente **guida** (non automatizza) il primo avvio. Il tool sola-lettura **`get_setup_status`**
gli dà lo stato di cosa manca per lo START. **Non espone segreti** (mai il valore di token/chat: solo
«configurato sì/no»), colmando il buco per cui `get_config_state` maschera il token a `***` e
l'assistente non sapeva se fosse impostato. Ritorna:

- **`requirements`** — i **4 requisiti operativi** dello START come booleani **nominati per chiave**
  (`bot_token`, `chat`, `parser_active`, `csv_usable`): derivati direttamente dalla config +
  `health_check.csv_writable`, **non** dall'ordine posizionale di una lista (review #66
  GLM/GPT/Fable/Fugu: niente accoppiamento agli indici);
- **`ready_to_start`** — `and` dei 4 requisiti. La **modalità NON** vi entra: lo START gira anche in
  **Simulazione** (default sicuro; il passaggio a Reale ha il suo gate frase a parte);
- **`mode_simulation`** — informativo (sei in Simulazione sì/no);
- **`language_chosen`** e una **`checklist`** leggibile (label canoniche di `wizard.final_checklist`,
  solo per il testo di guida: la fonte autoritativa di prontezza è `requirements`).

Con questo l'assistente può dire all'utente *cosa* manca e *dove* metterlo:
- per le impostazioni **non critiche** (tema, lingua app, `clear_delay`, `confirmation_timeout`,
  `max_signal_age`) **propone** lui il valore (l'utente conferma con «✅ Applica», PR-4);
- per i campi **critici** (token, chat, `csv_path`, parser attivo, modalità) — che restano in
  **denylist** e che l'assistente **non può scrivere** — indirizza l'utente ai campi della finestra o
  al pulsante **«🧙 Wizard prima configurazione»** (tab Strumenti), che verifica token/chat/CSV dal
  vivo. L'assistente **non apre finestre** né automatizza la GUI (invarianti): solo testo di guida.

Test hard: `tests/safety/test_config_agent_41.py` (`get_setup_status` su config vuota/parziale/
completa → checklist e `ready_to_start` corretti; **niente token/chat in chiaro** nell'output;
offerto come **read-only** anche senza `allow_writes`; nessuna scrittura).

### Smoke test manuale (Windows, no display in CI)

1. Apri l'app → tab **«🤖 Assistente»**: stato **⚪ OFFLINE**, input **disabilitato**.
2. Premi **Abilita** *senza* API key salvata → stato **🔴 ERRORE** con avviso «API key … mancante»;
   l'input resta disabilitato.
3. Incolla una API key nel campo mascherato → **💾 Salva chiave** → «✓ Chiave salvata nel keyring»;
   il campo si svuota. Premi **Abilita** → **🟢 ATTIVO**, input abilitato.
4. Scrivi un messaggio → **Invia**: compaiono «🧑 Tu: …» e la risposta «🤖 Assistente: …».
   *Atteso:* nessun token/chat in chiaro nel log; la conversazione è salvata redatta in
   `%APPDATA%/XTraderBridge/assistant_history.json`.
5. Chiudi la finestra (o **Stop**) → si richiede lo stop del worker (join a timeout): la finestra si
   chiude subito; un eventuale turno reale in volo termina da sé (thread daemon) ed è scartato.
   *Non verificato in CI:* rendering widget, chiamata reale ad Anthropic, keyring reale Windows.

> **Nota (future, nitpick CodeRabbit #64):** `run_turn` ripassa al modello l'INTERA cronologia a
> ogni turno → in sessioni molto lunghe il contesto cresce (latenza/costo/limite di finestra). Una
> **troncatura/riassunto** oltre una soglia è un miglioramento previsto per una fase successiva
> (fuori dallo scope di PR-3).

## Cosa NON c'è ancora (PR successive)
- **PR-4 (fatto)**: scrittura config GATED — **solo** chiavi non safety-critical (vedi sopra). Le
  chiavi pericolose (token/chat/csv/parser/modalità/limiti) restano **non scrivibili**
  dall'assistente; un eventuale write-path frictionful per alcune di esse è una scelta esplicita del
  proprietario per una fase successiva.
- **PR-5 (fatto)**: first-run — l'assistente **guida** il primo avvio via `get_setup_status` (vedi
  «Guida alla prima configurazione»). Non automatizza la GUI né scrive i campi critici.
- **PR-6**: guide utente `docs/user/`.
