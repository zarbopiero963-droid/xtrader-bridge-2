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
- **Tool sola-lettura** (PR-1): `get_config_state` (config **redatta**), `get_health`
  (semafori `health_check`), `list_parsers`. Esercitano funzioni reali del progetto.
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
- **Redazione profonda** (`_deep_redact`): ogni foglia-stringa dei messaggi (testo utente/
  assistente, `tool_use.input`, `tool_result.content`, nomi) passa per `event_log.redact_secrets`;
  la struttura è preservata. `save(extra_secrets=[...])` registra temporaneamente segreti di
  sessione (es. il `chat_id`) per mascherarli in modo robusto. **API key/bot token/chat non
  finiscono mai in chiaro nel file.**
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

Limite onesto: `register_secret` ignora i literal < 8 caratteri (guardia anti-frammento), quindi un
chat ID cortissimo non è mascherato per-literal; i chat ID reali Telegram (`-100…`) sono lunghi e
coperti (il bot token e `sk-ant-...` restano coperti dai pattern a prescindere).

## Cosa NON c'è ancora (PR successive)

- **PR-3**: tab GUI + Abilita/Stop + wiring stato live (design handoff).
- **PR-4**: tool di **scrittura** config gated (token/chat/csv/parser) con conferma sulle
  transizioni pericolose.
- **PR-5**: first-run — l'agente pilota il wizard esistente.
- **PR-6**: guide utente `docs/user/`.
