"""Assistente di configurazione in-app (#41) — scheletro headless, offline-testabile (PR-1).

Questo modulo è il **cervello** dell'assistente: un client Anthropic *tool-use* **iniettabile**,
un **registry di tool** con classificazione dei permessi, e le **guardie di sicurezza hard-block**
che impediscono all'agente azioni pericolose **anche su ordine esplicito**.

Resta **headless** (nessuna GUI, nessun thread) e **offline-testabile**: il client reale Anthropic
è un *lazy import* fail-safe (come ``token_store`` con ``keyring``) e **non** viene mai esercitato
nei test — i test iniettano un client finto. **PR-2** aggiunge la **persistenza cronologia**
(``ConversationHistory``, sempre redatta su disco). La GUI (PR-3) e i tool di **scrittura** config
gated (PR-4) arrivano nelle PR successive.

Invarianti di sicurezza (hard block — vedi ``FORBIDDEN_TOOLS`` e ``ToolRegistry.dispatch``):
l'agente non può MAI piazzare scommesse, parlare con XTrader/Betfair, indebolire il filtro chat,
avviare il listener LIVE o la modalità reale, scrivere il CSV operativo, rivelare/esportare
segreti, usare il web o eseguire shell/codice arbitrario. Ogni tentativo è **rifiutato e
registrato** nell'audit, e l'handler non viene mai chiamato. Inoltre **ogni** risultato di tool è
passato per ``event_log.redact_secrets`` prima di tornare al modello: API key/token/chat non
lasciano mai la macchina in chiaro.
"""

import json
import os

from . import (atomic_io, bridge_mode, config_store, csv_writer, custom_parser, dizionario,
               event_journal, event_log, health_check, journal_view, language_select, log_privacy,
               market_mapping_store, name_mapping_store, parser_builder, parser_manager, recognition,
               source_manager, value_maps, wizard)

# ── Classi di permesso dei tool ────────────────────────────────────────────────
READ_ONLY = "read_only"        # sola lettura: sempre permesso
WRITE_CONFIG = "write_config"  # scrittura config NON safety-critical: gated (PR-4)
FORBIDDEN = "forbidden"        # hard block: mai eseguibile, nemmeno su ordine

# ── Denylist hard-block (#41 «Invarianti di sicurezza — BLOCCATE SEMPRE») ───────
# Nomi-capacità che l'agente NON deve MAI eseguire. NON vengono esposti al modello; se il modello
# li richiede lo stesso (confuso o indotto), il dispatcher rifiuta a prescindere e lo registra.
FORBIDDEN_TOOLS = frozenset({
    # piazzamento / comunicazione col mondo scommesse
    "place_bet", "place_signal", "communicate_xtrader", "communicate_betfair",
    "write_operational_csv",
    # filtro chat (deve restare fail-closed)
    "weaken_chat_filter", "disable_chat_filter", "bypass_chat_filter",
    # avvio live / modalità reale senza la conferma frictionful esistente
    "start_live_listener", "start_listener", "set_real_mode", "enable_real_mode",
    # segreti
    "reveal_secret", "export_secret", "read_api_key", "read_bot_token", "dump_secrets",
    # web / codice arbitrario
    "web_fetch", "web_search", "browse", "http_request",
    "run_shell", "exec_code", "eval_code", "run_command",
})

# Cap di iterazioni tool-use per turno: evita loop infiniti se il modello continua a chiamare tool.
MAX_TOOL_ITERATIONS = 8

_REFUSAL_UNKNOWN = "Rifiutato: strumento sconosciuto «{name}» (non registrato)."
_REFUSAL_FORBIDDEN = (
    "Rifiutato: «{name}» è un'azione vietata dalle invarianti di sicurezza del bridge "
    "(piazzamento/live/segreti/web/shell). Non è eseguibile nemmeno su richiesta esplicita.")
_REFUSAL_WRITE_DISABLED = (
    "Rifiutato: «{name}» modifica la configurazione ma la scrittura è disattivata in questo "
    "contesto. Serve l'abilitazione esplicita (arriva in una fase successiva).")


class ToolError(Exception):
    """Errore non fatale nell'esecuzione di un tool sola-lettura: catturato dal dispatcher e
    restituito al modello come contenuto d'errore (mai propaga fuori dall'agente)."""


class AgentTool:
    """Un tool esposto (o valutato) dall'agente.

    - ``name``/``description``/``input_schema``: la *spec* passata al modello (function calling);
    - ``permission``: ``READ_ONLY`` / ``WRITE_CONFIG`` (i ``FORBIDDEN`` NON si registrano: sono la
      denylist ``FORBIDDEN_TOOLS``);
    - ``handler(input: dict) -> str``: la funzione reale del progetto; ritorna testo (il risultato
      che il modello vedrà, DOPO la redazione dei segreti)."""

    def __init__(self, name, description, input_schema, permission, handler):
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.permission = permission
        self.handler = handler

    def spec(self) -> dict:
        """La spec in formato Anthropic tool-use (name/description/input_schema)."""
        return {"name": self.name, "description": self.description,
                "input_schema": self.input_schema}


class ToolResult:
    """Esito di una ``dispatch``: ``content`` è ciò che torna al modello (già redatto);
    ``refused`` True se bloccato dalle guardie (handler NON chiamato)."""

    def __init__(self, name, content, *, refused=False, reason=""):
        # Il `name` è controllato dal modello e potrebbe contenere un segreto (#62): si redige anche
        # qui, così nessun campo serializzabile del risultato (né la futura cronologia PR-2) lo
        # espone. `redact_secrets` lascia intatti i nomi legittimi (solo i segreti REGISTRATI sono
        # mascherati). Il lookup del tool nel dispatch usa il `name` grezzo PRIMA di costruire il
        # risultato, quindi la redazione non tocca la logica.
        self.name = event_log.redact_secrets(str(name))
        self.content = content
        self.refused = refused
        self.reason = reason


class ToolRegistry:
    """Registro dei tool + **guardie di sicurezza**. È l'unico punto da cui un tool viene eseguito.

    Regole di ``dispatch`` (nell'ordine — fail-closed):
    1. nome nella denylist ``FORBIDDEN_TOOLS`` → **rifiuto** (hard block), handler mai chiamato;
    2. nome non registrato → **rifiuto** (sconosciuto);
    3. tool ``WRITE_CONFIG`` con ``allow_writes=False`` → **rifiuto** (scrittura disattivata);
    4. altrimenti esegue l'handler e **redige i segreti** dal risultato prima di restituirlo.

    Ogni chiamata (permessa o rifiutata) è annotata in ``audit_log`` e, se presente, notificata al
    ``logger`` iniettabile — così l'app reale può scrivere l'evento nel log senza I/O nei test."""

    def __init__(self, *, logger=None):
        self._tools = {}
        self.audit_log = []       # lista di dict {name, input, allowed, reason} — ispezionabile nei test
        self._logger = logger     # callable(str) opzionale per il log reale (event_log nell'app)

    def register(self, tool: AgentTool) -> None:
        if tool.permission not in (READ_ONLY, WRITE_CONFIG):
            raise ValueError(f"permesso non valido per {tool.name!r}: {tool.permission!r}")
        if tool.name in FORBIDDEN_TOOLS:
            # Difesa in profondità: un tool con nome in denylist NON può essere registrato.
            raise ValueError(f"{tool.name!r} è nella denylist FORBIDDEN_TOOLS: non registrabile")
        self._tools[tool.name] = tool

    def get(self, name):
        return self._tools.get(name)

    def tool_specs(self, *, include_writes=False) -> list:
        """Le spec da passare al modello. In PR-1 si espongono SOLO i tool sola-lettura
        (``include_writes=False``): i tool di scrittura esistono nel registro ma non vengono
        offerti finché la fase di scrittura gated (PR-4) non li abilita. Filtro difensivo
        aggiuntivo: un nome nella denylist ``FORBIDDEN_TOOLS`` non è MAI offerto al modello
        (belt-and-suspenders: `register` già lo impedisce, ma se qualcuno bypassasse il costruttore
        e iniettasse in `_tools`, qui resta comunque escluso)."""
        return [t.spec() for t in self._tools.values()
                if t.name not in FORBIDDEN_TOOLS
                and (t.permission == READ_ONLY or (include_writes and t.permission == WRITE_CONFIG))]

    @staticmethod
    def _safe_repr(obj) -> str:
        """Rappresentazione **redatta** di un input per l'audit: nessun segreto registrato
        (token/API key) resta in chiaro. Difesa in profondità (#41): l'audit — e la cronologia
        (PR-2) — non devono MAI conservare segreti, nemmeno se il modello passa un valore sensibile
        come parametro di tool (rilievo GPT-5.5/Fable/Fugu/GLM su #62)."""
        try:
            return event_log.redact_secrets(json.dumps(obj, ensure_ascii=False, default=str))
        except (TypeError, ValueError):
            return "<non serializzabile>"

    def _audit(self, name, tool_input, allowed, reason):
        # TUTTI i campi persistiti REDATTI (non solo `input`): il `name` è controllato dal modello e
        # `reason` può includere il messaggio di un'eccezione → nessun segreto resta nell'audit (#62).
        self.audit_log.append({"name": event_log.redact_secrets(str(name)),
                               "input": self._safe_repr(tool_input),
                               "allowed": allowed,
                               "reason": event_log.redact_secrets(str(reason))})
        if self._logger is not None:
            verb = "eseguito" if allowed else "RIFIUTATO"
            try:
                self._logger(event_log.redact_secrets(
                    f"[assistente] tool {verb}: {name} ({reason})"))
            except Exception:   # noqa: BLE001 — il logging non deve mai far fallire il dispatch
                pass

    def dispatch(self, name, tool_input, *, allow_writes=False) -> ToolResult:
        """Esegue (o rifiuta) un tool. Vedi le regole nella docstring della classe."""
        tool_input = tool_input if isinstance(tool_input, dict) else {}
        # I messaggi di rifiuto interpolano il `name` (che il modello controlla): passano comunque
        # per `redact_secrets`, così nessun segreto torna al modello nemmeno via un nome-tool
        # malevolo (rilievo GLM su #62).
        # 1. hard block: denylist — a prescindere da registrazione e da allow_writes.
        if name in FORBIDDEN_TOOLS:
            reason = "forbidden"
            self._audit(name, tool_input, False, reason)
            return ToolResult(name, event_log.redact_secrets(_REFUSAL_FORBIDDEN.format(name=name)),
                              refused=True, reason=reason)
        tool = self._tools.get(name)
        # 2. sconosciuto.
        if tool is None:
            reason = "unknown"
            self._audit(name, tool_input, False, reason)
            return ToolResult(name, event_log.redact_secrets(_REFUSAL_UNKNOWN.format(name=name)),
                              refused=True, reason=reason)
        # 3. scrittura non abilitata.
        if tool.permission == WRITE_CONFIG and not allow_writes:
            reason = "write_disabled"
            self._audit(name, tool_input, False, reason)
            return ToolResult(name, event_log.redact_secrets(_REFUSAL_WRITE_DISABLED.format(name=name)),
                              refused=True, reason=reason)
        # 4. esecuzione + redazione segreti sul risultato.
        try:
            raw = tool.handler(tool_input)
        except ToolError as exc:
            self._audit(name, tool_input, True, f"error:{exc}")
            return ToolResult(name, event_log.redact_secrets(f"Errore nel tool: {exc}"))
        except Exception as exc:   # noqa: BLE001 — nessun tool deve poter far crashare l'agente
            self._audit(name, tool_input, True, f"exception:{type(exc).__name__}")
            return ToolResult(name, event_log.redact_secrets(
                f"Errore interno nel tool «{name}»: {type(exc).__name__}"))
        safe = event_log.redact_secrets(str(raw))
        self._audit(name, tool_input, True, "ok")
        return ToolResult(name, safe)


# ── Tool sola-lettura reali (le «fonti di conoscenza» — stato live) ─────────────

def _redact_config(cfg: dict) -> dict:
    """Vista **redatta** della config: chat ID mascherati, valori sensibili rimossi. Il token e la
    API key vivono nel keyring (non in config), ma per difesa in profondità si rimuove qualunque
    chiave dal nome sospetto e si passa comunque il tutto per ``redact_secrets`` a valle."""
    out = {}
    _sensitive = ("token", "api_key", "apikey", "password", "secret")
    for key, val in (cfg or {}).items():
        low = str(key).lower()
        if any(s in low for s in _sensitive):
            out[key] = "***"
            continue
        if key in ("chat_id", "xtrader_notification_chat_id"):
            out[key] = log_privacy.redact_chat_id(val)
            continue
        if key == "source_chats" and isinstance(val, list):
            out[key] = [
                {**{k: v for k, v in ch.items() if k != "chat_id"},
                 "chat_id": log_privacy.redact_chat_id(ch.get("chat_id"))}
                if isinstance(ch, dict) else ch
                for ch in val]
            continue
        if key in ("parser_by_chat", "parser_list_by_chat") and isinstance(val, dict):
            # P2-6 audit #76: anche i chat ID usati come CHIAVI di questi dict
            # ({chat_id: parser} / {chat_id: [parser, ...]}) sono sensibili quanto
            # `chat_id`/`source_chats`: senza redazione partirebbero in CHIARO verso l'API
            # Anthropic e verrebbero persistiti in `assistant_history.json` (il redattore a
            # valle copre solo il bot token). I VALORI (nomi parser) non sono sensibili e
            # restano leggibili; una chiave vuota/None degrada a "" (mai il valore grezzo).
            out[key] = {(log_privacy.redact_chat_id(k) or ""): v for k, v in val.items()}
            continue
        out[key] = val
    return out


def build_read_only_tools(*, config_loader=None, parsers_dir=None) -> list:
    """Costruisce i tool **sola-lettura** dell'agente (stato live/contesto). ``config_loader`` e
    ``parsers_dir`` sono iniettabili per i test; se assenti si usa lo stato reale dell'app."""
    load_cfg = config_loader or config_store.load_config

    def _get_config_state(_inp):
        cfg = load_cfg()
        return json.dumps(_redact_config(cfg), ensure_ascii=False, indent=2, sort_keys=True)

    def _get_health(_inp):
        cfg = load_cfg()
        items = health_check.evaluate(
            parser_active=bool(cfg.get("active_parser")),
            mode=str(cfg.get("bridge_mode", "") or cfg.get("mode", "")))
        return json.dumps([{"key": it.key, "label": it.label, "state": it.state,
                            "detail": it.detail} for it in items], ensure_ascii=False, indent=2)

    def _list_parsers(_inp):
        files = custom_parser.list_parser_files(parsers_dir)
        names = [os.path.splitext(os.path.basename(f))[0] for f in files]
        return json.dumps({"parsers": names, "active": load_cfg().get("active_parser", "")},
                          ensure_ascii=False)

    def _get_setup_status(_inp):
        # Checklist di PRIMA CONFIGURAZIONE (#41 PR-5): «cosa manca per lo START». Espone SOLO
        # booleani + label statiche, MAI il valore di token/chat (nessun segreto; il dispatcher
        # redige comunque a valle). Serve all'assistente per GUIDARE il primo avvio: i campi critici
        # NON sono modificabili da lui (denylist) → li indirizza all'utente / al pulsante «Wizard».
        cfg = load_cfg() or {}
        # Requisiti nominati (per CHIAVE, non per indice — review #66 GLM/GPT/Fable: niente
        # accoppiamento all'ordine posizionale di `wizard.final_checklist`). Stessi criteri del gate
        # reale di START/`health_check`: parser = `active_parser` non vuoto; CSV = sonda non invasiva.
        token_set = bool(str(cfg.get("bot_token", "") or "").strip())
        chat_set = bool(str(cfg.get("chat_id", "") or "").strip() or cfg.get("source_chats"))
        parser_active = bool(str(cfg.get("active_parser", "") or "").strip())
        csv_state, _csv_reason = health_check.csv_writable(cfg.get("csv_path", ""))
        csv_usable = csv_state != health_check.RED
        in_simulation = bridge_mode.mode_from_cfg(cfg) == bridge_mode.SIMULAZIONE
        requirements = {
            "bot_token": token_set,
            "chat": chat_set,
            "parser_active": parser_active,
            "csv_usable": csv_usable,
        }
        # Pronto allo START = i 4 requisiti OPERATIVI. La MODALITÀ è **informativa** (lo START gira
        # anche in Simulazione, che è il default sicuro; passare a Reale ha il suo gate frase a
        # parte) → NON entra in `ready_to_start` (chiarimento contratto, GPT #66).
        ready = token_set and chat_set and parser_active and csv_usable
        lang = language_select.normalize_app_language(cfg.get("app_language"))
        # Checklist human-readable (label canoniche del wizard) SOLO per il testo di guida: il valore
        # autoritativo di prontezza è `requirements`/`ready_to_start` qui sopra, non l'ordine di questa lista.
        checklist = [{"done": bool(done), "item": label}
                     for done, label in wizard.final_checklist(cfg, parser_active=parser_active)]
        return json.dumps({
            "language_chosen": lang or None,
            "ready_to_start": ready,
            "requirements": requirements,
            "mode_simulation": in_simulation,     # informativo, NON un requisito di START
            "checklist": checklist,
            "note": ("I campi CRITICI (token, chat, percorso CSV, parser attivo, modalità) NON sono "
                     "modificabili dall'assistente: guida l'utente a compilarli nei campi della "
                     "finestra o ad aprire «🧙 Wizard prima configurazione» nella tab Strumenti. Le "
                     "impostazioni non critiche (tema, lingua app, clear_delay, confirmation_timeout, "
                     "max_signal_age) puoi proporle con set_config_value."),
        }, ensure_ascii=False, indent=2)

    return [
        AgentTool(
            "get_config_state",
            "Ritorna la configurazione corrente del bridge in forma REDATTA "
            "(token/API key/chat ID mai in chiaro). Sola lettura.",
            {"type": "object", "properties": {}, "additionalProperties": False},
            READ_ONLY, _get_config_state),
        AgentTool(
            "get_health",
            "Ritorna i semafori dell'health check (Telegram, parser, CSV, modalità…). Sola lettura.",
            {"type": "object", "properties": {}, "additionalProperties": False},
            READ_ONLY, _get_health),
        AgentTool(
            "list_parsers",
            "Elenca i Parser Personalizzati salvati e quello attivo. Sola lettura.",
            {"type": "object", "properties": {}, "additionalProperties": False},
            READ_ONLY, _list_parsers),
        AgentTool(
            "get_setup_status",
            "Stato di PRIMA CONFIGURAZIONE: i 4 REQUISITI dello START (token, chat, parser attivo, "
            "CSV utilizzabile) come booleani nominati in `requirements`, più `ready_to_start`, "
            "`mode_simulation` (informativo, NON un requisito: lo START gira anche in Simulazione), "
            "`language_chosen` e una `checklist` leggibile. NON espone segreti (solo «configurato "
            "sì/no», mai i valori). Usalo per guidare il primo avvio: proponi le impostazioni non "
            "critiche e indirizza l'utente ai campi/al Wizard per quelle critiche. Sola lettura.",
            {"type": "object", "properties": {}, "additionalProperties": False},
            READ_ONLY, _get_setup_status),
    ]


# ── Base di conoscenza: guide del progetto (sola lettura, #41 PR-7 Blocco A) ─────
# ALLOWLIST esplicita di file-documentazione leggibili dall'assistente per spiegare il bridge. È una
# allowlist (come le chiavi scrivibili): l'assistente NON può leggere path arbitrari → mai
# config.json, sorgenti o segreti. I path sono relativi alla RADICE del progetto e sono fissi qui
# (il modello passa solo un `name`, non un path → niente path-traversal).
GUIDES = {
    "panoramica":            ("README.md",
                              "Panoramica del bridge: cos'è, come funziona, guida rapida, sicurezza, formato CSV."),
    "guida_utente":          ("docs/user/README.md",
                              "Indice delle guide utente + principi di sicurezza."),
    "primi_passi":           ("docs/user/getting_started.md",
                              "Dalla prima apertura al primo AVVIA: lingua, token/chat/CSV, Wizard, START/STOP, modalità."),
    "assistente":            ("docs/user/assistente.md",
                              "Guida all'assistente 🤖: cosa può/non può fare, proposta→Applica, prima configurazione."),
    "parser_personalizzato": ("docs/custom_parser.md",
                              "Il Parser Personalizzato: regole, delimitatori, colonne, condizioni; come crearlo."),
    "contratto_csv":         ("docs/xtrader_csv_contract.md",
                              "Il contratto CSV per XTrader: colonne, formato, separatore decimale, compatibilità."),
    "interfaccia":           ("docs/design/design_handoff.md",
                              "Descrizione di ogni schermata/tab/pulsante/campo/stato della GUI."),
    "diario_eventi":         ("docs/event_journal.md",
                              "Il diario eventi (journal): cosa registra e come consultarlo."),
}

# Tetto sul contenuto restituito, per non gonfiare il contesto: una guida grande è troncata con nota
# (l'assistente può leggerne un'altra o chiedere una sezione specifica).
MAX_GUIDE_CHARS = 12000


def _guides_base_dir(base_dir=None) -> str:
    """Radice da cui leggere le guide (default: radice del progetto = parent del package)."""
    if base_dir is not None:
        return base_dir
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build_guide_tools(*, base_dir=None) -> list:
    """Tool SOLA-LETTURA di conoscenza (#41 PR-7 Blocco A): `list_guides`/`read_guide`. `base_dir`
    iniettabile per i test. Legge SOLO i file nell'allowlist `GUIDES`."""
    root = _guides_base_dir(base_dir)

    def _list_guides(_inp):
        return json.dumps(
            {"guides": [{"name": n, "about": desc} for n, (_p, desc) in sorted(GUIDES.items())]},
            ensure_ascii=False, indent=2)

    def _read_guide(inp):
        name = str(inp.get("name", "")).strip()
        entry = GUIDES.get(name)
        if entry is None:                       # solo i nomi in allowlist: niente path arbitrari
            return (f"Guida «{name}» non trovata. Disponibili: {', '.join(sorted(GUIDES))}. "
                    "Usa 'list_guides' per l'elenco con le descrizioni.")
        rel_path, _desc = entry
        try:
            with open(os.path.join(root, rel_path), encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, ValueError):           # fail-safe: docs non incluse (es. EXE) → nessun crash
            return (f"Guida «{name}» non disponibile in questa installazione (documentazione non "
                    "inclusa nel pacchetto).")
        if len(text) > MAX_GUIDE_CHARS:
            text = text[:MAX_GUIDE_CHARS] + "\n\n[…troncata: chiedi una sezione specifica o un'altra guida]"
        return text

    return [
        AgentTool(
            "list_guides",
            "Elenca le GUIDE del progetto che puoi leggere per spiegare il bridge (nome + argomento). "
            "Sola lettura.",
            {"type": "object", "properties": {}, "additionalProperties": False},
            READ_ONLY, _list_guides),
        AgentTool(
            "read_guide",
            "Ritorna il contenuto di UNA guida del progetto (per `name`, da 'list_guides') per "
            "spiegare pulsanti/campi/concetti e COME si fanno le azioni. Legge SOLO le guide in "
            "elenco, nessun altro file. Sola lettura.",
            {"type": "object",
             "properties": {"name": {"type": "string",
                                     "description": "nome della guida (da 'list_guides')"}},
             "required": ["name"], "additionalProperties": False},
            READ_ONLY, _read_guide),
    ]


# ── 🧪 Prova messaggio: tester SOLA-LETTURA (#41 PR-8 Blocco B) ──────────────────
# L'assistente prova un messaggio col parser ATTIVO e mostra il verdetto + l'anteprima della riga
# CSV, SENZA scrivere nulla. Riusa la STESSA pipeline read-only del tester GUI/wizard
# (`ParserBuilder.batch_report` → `build_validated_rows`, identica al runtime ma senza scrittura).
# Il wiring (mapping profiles + lingua sorgente + provider) è preso da config come fa il runtime; il
# `id_resolver` (dizionario Betfair) NON è passato → anteprima CONSERVATIVA (fail-closed: un parser
# ID_ONLY può apparire «non pronto» ma mai il contrario), esattamente come il wizard.

# Limite di lunghezza dell'input (fail-safe anti-paste gigante prima ancora di `split_messages`).
MAX_TESTER_CHARS = 8000


def build_message_preview(cfg, message, *, chat="", parsers_dir=None) -> dict:
    """Prova `message` col parser attivo per `chat` e ritorna un dict JSON-friendly (SOLA LETTURA).

    Replica il wiring runtime/GUI (`signal_router._resolve_one` / `custom_parser_gui`): parser
    attivo per la chat + profili di mapping nomi/mercati + lingua sorgente + provider, tutti da
    config. **Non** passa `id_resolver` (dizionario Betfair) → anteprima CONSERVATIVA come il wizard.
    Non scrive né tocca alcun file. `parsers_dir` iniettabile per i test."""
    cfg = cfg if isinstance(cfg, dict) else {}
    text = str(message or "").strip()
    csv_language = csv_writer.normalize_csv_language(cfg.get("csv_language"))
    ctx = {
        "csv_header": list(csv_writer.CSV_HEADER),
        "csv_language": csv_language,
        "decimal_separator": csv_writer.decimal_separator(csv_language),
        "message_separator": parser_builder.MESSAGE_SEPARATOR,
    }
    if not text:
        return {"error": "empty", "message": "Nessun messaggio: incolla un segnale del canale.",
                "csv_context": ctx}
    if len(text) > MAX_TESTER_CHARS:
        return {"error": "too_long",
                "message": f"Messaggio troppo lungo ({len(text)} caratteri, max {MAX_TESTER_CHARS}). "
                           "Incolla un solo segnale (o pochi, separati da una riga «---»).",
                "csv_context": ctx}
    chat_id = str(chat or "").strip() or str(cfg.get("chat_id", "") or "")
    defn = parser_manager.load_active(cfg, chat_id, parsers_dir)
    if defn is None:
        return {
            "error": "no_active_parser",
            "message": ("Nessun Parser Personalizzato ATTIVO per questa chat: non posso provare il "
                        "messaggio. Attiva/crea un parser (tab «🧩 Parser Personalizzato»); posso "
                        "spiegarti come con 'read_guide' (guida «parser_personalizzato»)."),
            "csv_context": ctx,
        }
    try:
        builder = parser_builder.ParserBuilder(defn)
        # Profili di mapping dal BUILDER (che li normalizza via `getattr` → robusto anche su una def
        # LEGACY priva del campo, CodeRabbit #70) + lingua sorgente + provider dalla config, come il
        # runtime (parità preview↔live). `entries_for_profiles` ignora da sé i profili assenti.
        name_profiles = (name_mapping_store.entries_for_profiles(cfg, builder.name_mapping_profiles)
                         if builder.name_mapping_profiles else None)
        market_profiles = (market_mapping_store.entries_for_profiles(cfg, builder.market_mapping_profiles)
                           if builder.market_mapping_profiles else None)
        source_language = recognition.effective_source_language(cfg, defn)
        provider = source_manager.provider_for_chat(cfg, chat_id, default=str(cfg.get("provider", "") or ""))
        # P2-7 audit #76 (parità preview↔runtime): la modalità EFFETTIVA è quella del parser o,
        # per un parser LEGACY con `mode==""`, quella GLOBALE — stessa risoluzione VERBATIM del
        # runtime (`signal_router._resolve_one`) e della GUI («Prova messaggio», `or _global_mode`).
        # Senza `mode=`, il builder normalizzava "" a NAME_ONLY e l'assistente poteva dire
        # «Pronto» per un messaggio che il live in ID_ONLY scarta (o viceversa).
        mode = recognition.normalize_mode(
            getattr(defn, "mode", "") or cfg.get("recognition_mode", recognition.DEFAULT_MODE))
        reports, skipped = builder.batch_report(
            text, provider=provider, mode=mode, name_mapping_profiles=name_profiles,
            market_mapping_profiles=market_profiles, source_language=source_language)
        out_reports = []
        for rep in reports:
            rows = []
            for pr in rep.rows:
                # Riga COME uscirebbe nel file: valori localizzati per la lingua CSV (IT/ES virgola,
                # EN punto), colonne vuote incluse così l'utente vede il contratto completo.
                shown = csv_writer.localize_row(pr.row, csv_language)
                rows.append({
                    "kind": pr.kind, "placeable": bool(pr.placeable), "status": pr.status,
                    "missing_required": list(pr.missing_required),
                    "columns": {col: shown.get(col, "") for col in csv_writer.CSV_HEADER},
                    "warnings": list(pr.warnings),
                })
            out_reports.append({
                "first_line": rep.first_line, "recognized": bool(rep.ok),
                "verdict": rep.verdict, "rows": rows,
            })
    except Exception as exc:   # noqa: BLE001 — tester SOLA-LETTURA: un parser attivo malformato o
        # un input patologico non deve MAI far crashare l'assistente; l'errore diventa un messaggio
        # guida (garanzia «mai crash» del Blocco B; Fugu #70). Nessuna scrittura è mai avvenuta.
        return {"error": "internal", "parser": getattr(defn, "name", ""),
                "message": (f"Impossibile provare il messaggio ({type(exc).__name__}): il parser "
                            "attivo potrebbe essere malformato. Controllalo nella tab «🧩 Parser "
                            "Personalizzato»."),
                "csv_context": ctx}
    return {
        "parser": defn.name,
        "provider": provider,
        "reports": out_reports,
        "skipped_messages": skipped,
        "csv_context": ctx,
        "note": ("Anteprima CONSERVATIVA e SENZA scrivere nulla: il dizionario Betfair non è "
                 "consultato qui, quindi un parser che risolve gli ID dal dizionario può apparire "
                 "«non pronto» anche se a runtime, col dizionario, verrebbe scritto."),
    }


def build_tester_tools(*, config_loader=None, parsers_dir=None) -> list:
    """Tool SOLA-LETTURA `test_message` (#41 PR-8 Blocco B). `config_loader`/`parsers_dir`
    iniettabili per i test. Non scrive né tocca alcun file."""
    load_cfg = config_loader or config_store.load_config

    def _test_message(inp):
        cfg = load_cfg() or {}
        data = build_message_preview(cfg, inp.get("message", ""),
                                     chat=str(inp.get("chat_id", "") or ""), parsers_dir=parsers_dir)
        return json.dumps(data, ensure_ascii=False, indent=2)

    return [
        AgentTool(
            "test_message",
            "PROVA un messaggio del canale col parser ATTIVO e mostra se è riconosciuto, il MOTIVO "
            "del verdetto e l'anteprima della riga CSV che uscirebbe (colonne e valori) — SENZA "
            "scrivere nulla. Usalo per «questo messaggio è ok?», «cosa uscirebbe nel CSV?», per "
            "spiegare colonne/delimitatori, o come tester mentre l'utente sistema il parser. "
            "Anteprima conservativa (niente dizionario Betfair). Sola lettura.",
            {"type": "object",
             "properties": {
                 "message": {"type": "string",
                             "description": "il testo del messaggio da provare (uno o più, separati "
                                            "da una riga «---»)"},
                 "chat_id": {"type": "string",
                             "description": "opzionale: chat sorgente per cui risolvere il parser "
                                            "attivo (default: la chat configurata)"}},
             "required": ["message"], "additionalProperties": False},
            READ_ONLY, _test_message),
    ]


# ── 📖 Consulta dizionario: lookup SOLA-LETTURA (#41 PR-9 Blocco C) ──────────────
# L'assistente cerca squadre/mercati/mapping e spiega COME sono mappati, in sola lettura:
#  - il DIZIONARIO XTrader (`data/dizionario_xtrader.csv`): alias Telegram → valori XTrader
#    (MarketType/MarketName/SelectionName/BetType/Handicap) — via API PUBBLICHE `dizionario.*`;
#  - i PROFILI di mapping dell'utente: nomi squadre (`name_mapping_store`) e mercati
#    (`market_mapping_store`);
#  - le VALUE-MAP (`value_maps`, es. bettype BACK→PUNTA).
# Nessuna scrittura, nessun segreto (dati di dominio). Fail-safe se il dizionario non è incluso
# (es. EXE senza `data/`): la sezione dizionario è marcata «non disponibile», i profili utente no.

MAX_DICT_MATCHES = 40   # tetto per categoria: non gonfiare il contesto su ricerche larghe


def _dictionary_entries() -> "list | None":
    """Righe PIATTE del dizionario XTrader via API pubbliche (`market_catalog` + `selections_for_market`).
    Ritorna `None` se il dizionario non è disponibile (es. EXE senza `data/`) → fail-safe."""
    try:
        out = []
        for m in dizionario.market_catalog():
            sels = dizionario.selections_for_market(m["MarketType"]) or [{
                "SelectionName": "", "MarketAliasTelegram": "", "SelectionAliasTelegram": "",
                "BetType": "", "Handicap": ""}]
            for s in sels:
                out.append({
                    "market_type": m["MarketType"], "market_name": m["MarketName"],
                    "selection_name": s.get("SelectionName", ""),
                    "market_alias_telegram": s.get("MarketAliasTelegram", ""),
                    "selection_alias_telegram": s.get("SelectionAliasTelegram", ""),
                    "bettype": s.get("BetType", ""), "handicap": s.get("Handicap", ""),
                    "dynamic": bool(s.get("dynamic")),
                })
        return out
    except Exception:   # noqa: BLE001 — dizionario non incluso/illeggibile: fail-safe (None), mai crash
        return None


def build_dictionary_overview(cfg) -> dict:
    """Panoramica SOLA-LETTURA di cosa «conosce» il bridge: mercati del dizionario XTrader, profili di
    mapping nomi/mercati dell'utente (con conteggi) e value-map disponibili."""
    cfg = cfg if isinstance(cfg, dict) else {}
    entries = _dictionary_entries()
    if entries is None:
        markets, dict_available = [], False
    else:
        seen, markets = set(), []
        for e in entries:
            if e["market_type"] in seen:
                continue
            seen.add(e["market_type"])
            markets.append({"market_type": e["market_type"], "market_name": e["market_name"]})
        dict_available = True
    name_profiles = [{"profile": n, "entries": len(name_mapping_store.get_entries(cfg, n))}
                     for n in name_mapping_store.profile_names(cfg)]
    market_profiles = [{"profile": n, "entries": len(market_mapping_store.get_entries(cfg, n))}
                       for n in market_mapping_store.profile_names(cfg)]
    return {
        "dizionario_available": dict_available,
        "dizionario_markets": markets,
        "name_mapping_profiles": name_profiles,
        "market_mapping_profiles": market_profiles,
        "value_maps": value_maps.available_value_maps(),
    }


def _match(query_norm, *fields) -> bool:
    """True se `query_norm` (già normalizzato) è sottostringa di uno dei `fields` normalizzati."""
    return any(query_norm in dizionario.normalize(f) for f in fields if f)


def build_dictionary_lookup(cfg, query) -> dict:
    """Cerca `query` (case/space-insensitive) tra dizionario XTrader, profili nomi/mercati e value-map,
    e ritorna COME ogni corrispondenza è mappata (SOLA LETTURA). Risultati capati per categoria."""
    cfg = cfg if isinstance(cfg, dict) else {}
    q = dizionario.normalize(query)
    if not q:
        return {"error": "empty",
                "message": "Cosa cerco nel dizionario? Dammi una squadra, un mercato o un alias."}
    truncated = {}

    entries = _dictionary_entries()
    dict_matches = []
    if entries is not None:
        for e in entries:
            if _match(q, e["market_type"], e["market_name"], e["selection_name"],
                      e["market_alias_telegram"], e["selection_alias_telegram"]):
                dict_matches.append(e)
    # Chiave SEMPRE presente (anche quando il dizionario è assente → False): schema di output
    # coerente per il consumatore LLM (Fable #71), niente ramo che la ometteva.
    truncated["dizionario"] = len(dict_matches) > MAX_DICT_MATCHES
    dict_matches = dict_matches[:MAX_DICT_MATCHES]

    team_matches = []
    for prof in name_mapping_store.profile_names(cfg):
        for en in name_mapping_store.get_entries(cfg, prof):
            if _match(q, en.get("provider", ""), en.get("country", ""), en.get("betfair", "")):
                team_matches.append({
                    "profile": prof, "from": en.get("provider", "") or en.get("country", ""),
                    "to_betfair": en.get("betfair", ""), "sport": en.get("sport", ""),
                    "entity_type": en.get("entity_type", ""), "language": en.get("language", "")})
    truncated["name_mapping"] = len(team_matches) > MAX_DICT_MATCHES
    team_matches = team_matches[:MAX_DICT_MATCHES]

    market_matches = []
    for prof in market_mapping_store.profile_names(cfg):
        for en in market_mapping_store.get_entries(cfg, prof):
            if _match(q, en.get("phrase", ""), en.get("market_name", ""),
                      en.get("selection_name", ""), en.get("market_type", "")):
                market_matches.append({
                    "profile": prof, "phrase": en.get("phrase", ""),
                    "market_type": en.get("market_type", ""), "market_name": en.get("market_name", ""),
                    "selection_name": en.get("selection_name", ""), "language": en.get("language", "")})
    truncated["market_mapping"] = len(market_matches) > MAX_DICT_MATCHES
    market_matches = market_matches[:MAX_DICT_MATCHES]

    value_map_matches = []
    reg = value_maps.registry()
    for name in sorted(reg):
        for alias, val in reg[name].items():
            if _match(q, name, alias, val):
                value_map_matches.append({"value_map": name, "alias": alias, "value": val})
    truncated["value_maps"] = len(value_map_matches) > MAX_DICT_MATCHES
    value_map_matches = value_map_matches[:MAX_DICT_MATCHES]

    return {
        "query": query,
        "dizionario_available": entries is not None,
        "dizionario_matches": dict_matches,
        "team_matches": team_matches,
        "market_mapping_matches": market_matches,
        "value_map_matches": value_map_matches,
        "truncated": truncated,
    }


def build_dictionary_tools(*, config_loader=None) -> list:
    """Tool SOLA-LETTURA `lookup_dictionary` (#41 PR-9 Blocco C). `config_loader` iniettabile."""
    load_cfg = config_loader or config_store.load_config

    def _lookup_dictionary(inp):
        cfg = load_cfg() or {}
        query = str(inp.get("query", "") or "").strip()
        data = (build_dictionary_lookup(cfg, query) if query
                else build_dictionary_overview(cfg))
        return json.dumps(data, ensure_ascii=False, indent=2)

    return [
        AgentTool(
            "lookup_dictionary",
            "CONSULTA il dizionario XTrader e i profili di mapping dell'utente (squadre, mercati, "
            "value-map) e spiega COME un termine è mappato: alias Telegram → valori XTrader "
            "(MarketType/MarketName/SelectionName/BetType/Handicap) e squadra → nome Betfair. Con un "
            "`query` cerca quel termine; senza, dà la PANORAMICA (mercati noti, profili, value-map). "
            "Sola lettura.",
            {"type": "object",
             "properties": {
                 "query": {"type": "string",
                           "description": "termine da cercare (squadra, mercato, selezione o alias); "
                                          "vuoto = panoramica"}},
             "additionalProperties": False},
            READ_ONLY, _lookup_dictionary),
    ]


# ── 🚦 Salute + 🩺 Diagnosi: tool SOLA-LETTURA (#41 PR-10 Blocco D) ──────────────
# Due tool sola-lettura:
#  - `explain_health`: i 7 semafori (telegram/message/parser/signal/csv/confirmation/mode) + una
#    riga di CONSIGLIO per gli stati non-verdi. Se l'app inietta `health_provider` (callable → gli
#    stessi `HealthItem` del pannello 🚦 Salute), riflette lo stato LIVE che l'utente vede; senza
#    provider (headless/test) ripiega su una valutazione da config + sonda CSV non invasiva.
#  - `why_discarded`: legge il DIARIO EVENTI (già redatto) e riassume il ciclo di vita degli ultimi
#    segnali (ricevuto→parsato→validato→scritto, rifiuti, recovery, riconnessioni) per spiegare
#    perché un segnale può non essere arrivato al CSV. Fail-safe se il diario è assente.

MAX_JOURNAL_EVENTS = 30   # ultimi N eventi restituiti/riassunti (append-only, cresce nel tempo)

# Consiglio breve per ogni semaforo quando NON è verde (cosa fare). Testo neutro, nessun segreto.
_HEALTH_ADVICE = {
    "telegram":     "Se OFFLINE premi ▶ AVVIA; se «riconnessione» attendi il backoff (rete/proxy).",
    "message":      "Invia un messaggio di prova nella chat sorgente e verifica che arrivi.",
    "parser":       "Attiva/crea un Parser Personalizzato (scheda 🧩): senza, lo START è bloccato.",
    "signal":       "Se c'è un «ultimo errore», leggilo: dice perché il segnale non è passato "
                    "(usa anche 'why_discarded').",
    "csv":          "Controlla il percorso CSV (la cartella deve esistere ed essere scrivibile).",
    "confirmation": "Per le conferme XTrader configura la chat notifiche (facoltativa).",
    "mode":         "GIALLO = Collaudo, ROSSO = Modalità REALE attiva: verifica di volerlo.",
}


def _health_items_to_dicts(items) -> list:
    """Serializza una lista di `HealthItem` (o dict equivalenti) in dict JSON-friendly, aggiungendo
    `advice` per gli stati non-verdi. Tollera sia oggetti `HealthItem` sia dict (provider iniettato)."""
    out = []
    for it in items or []:
        key = getattr(it, "key", None) if not isinstance(it, dict) else it.get("key", "")
        label = getattr(it, "label", None) if not isinstance(it, dict) else it.get("label", "")
        state = getattr(it, "state", None) if not isinstance(it, dict) else it.get("state", "")
        detail = getattr(it, "detail", None) if not isinstance(it, dict) else it.get("detail", "")
        advice = _HEALTH_ADVICE.get(key, "") if state and state != health_check.GREEN else ""
        out.append({"key": key or "", "label": label or "", "state": state or "",
                    "detail": detail or "", "advice": advice})
    return out


def build_health_report(cfg, *, health_provider=None) -> dict:
    """I 7 semafori + consiglio per gli stati non-verdi (SOLA LETTURA). Con `health_provider` (dato
    dall'app) riflette lo stato LIVE del pannello 🚦; senza, valuta da config + sonda CSV non invasiva
    (headless/test): fedeltà parziale (telegram/segnale/conferme non sono noti senza app viva)."""
    cfg = cfg if isinstance(cfg, dict) else {}
    live = False
    items = None
    if health_provider is not None:
        try:
            got = health_provider()
            # `live` è True SOLO se il provider ha dato semafori VALIDI e non vuoti (GLM #72): un
            # provider che ritorna None/[] è degenere → si ripiega su config con `live=False`, mai
            # `live=True` su dati di fallback (etichetta coerente per il consumatore).
            if got:
                items, live = got, True
        except Exception:   # noqa: BLE001 — provider dell'app difettoso: mai crash, ripiega su config
            items = None
    if not items:
        csv_state, csv_detail = health_check.csv_writable(cfg.get("csv_path", ""))
        # `mode` via `bridge_mode.mode_from_cfg` — la STESSA fonte del pannello 🚦 Salute
        # (`app._live_health_items`) e di `get_setup_status`: nel fallback la Modalità non deve
        # divergere né mascherare il REALE (Fugu #72).
        items = health_check.evaluate(
            parser_active=bool(cfg.get("active_parser")),
            csv_state=csv_state, csv_detail=csv_detail,
            confirmations_enabled=bool(str(cfg.get("xtrader_notification_chat_id", "") or "").strip()),
            mode=bridge_mode.mode_from_cfg(cfg))
    return {"live": live, "semafori": _health_items_to_dicts(items)}


def _journal_summary(events) -> dict:
    """Riassunto del ciclo di vita dagli eventi del diario (già in ordine d'inserimento): conteggi per
    tipo + esito dell'ULTIMO segnale ricevuto (è arrivato al CSV? rifiutato?)."""
    counts = {}
    for e in events:
        t = str((e or {}).get("type", "") or "")
        counts[t] = counts.get(t, 0) + 1
    last_signal_reached_csv = None
    last_received_idx = None
    for i, e in enumerate(events):
        if (e or {}).get("type") == "SIGNAL_RECEIVED":
            last_received_idx = i
    if last_received_idx is not None:
        # è stato scritto un CSV DOPO l'ultimo segnale ricevuto?
        after = events[last_received_idx + 1:]
        last_signal_reached_csv = any((e or {}).get("type") == "CSV_WRITTEN" for e in after)
    return {
        "counts": counts,
        "last_signal_received": last_received_idx is not None,
        "last_signal_reached_csv": last_signal_reached_csv,
        "any_rejected": counts.get("XTRADER_REJECTED", 0) > 0,
        "crash_recovery_clears": counts.get("CRASH_RECOVERY_CSV_CLEARED", 0),
        "reconnects": counts.get("RECONNECT", 0),
    }


def build_journal_report(*, journal_path=None, limit=MAX_JOURNAL_EVENTS) -> dict:
    """Legge il DIARIO EVENTI (già redatto) e ne riassume il ciclo di vita recente (SOLA LETTURA).
    `journal_path` iniettabile (default: `journal_view.default_path()`). Fail-safe: diario assente/
    illeggibile → lista vuota + `journal_available=False`, mai crash."""
    try:
        path = journal_path or journal_view.default_path()
    except Exception:   # noqa: BLE001 — risoluzione path (config_dir) difettosa: fail-safe
        path = None
    events = event_journal.read_events(path) if path else []
    recent = events[-int(limit):] if limit and len(events) > int(limit) else events
    return {
        "journal_available": bool(events),
        "shown": len(recent),
        "total": len(events),
        "events": recent,
        "summary": _journal_summary(events),
        "note": ("Il diario registra le TAPPE (ricevuto/parsato/validato/scritto/rifiuti/recovery), "
                 "non il motivo esatto dello scarto. Per il motivo specifico (duplicato, troppo "
                 "vecchio, parser, CSV) guarda anche l'«ultimo errore» in 'explain_health'."),
    }


def build_diagnostic_tools(*, config_loader=None, health_provider=None, journal_path=None) -> list:
    """Tool SOLA-LETTURA di diagnosi (#41 PR-10 Blocco D): `explain_health` + `why_discarded`.
    `health_provider`/`journal_path` iniettati dall'app (o dai test)."""
    load_cfg = config_loader or config_store.load_config

    def _explain_health(_inp):
        return json.dumps(build_health_report(load_cfg() or {}, health_provider=health_provider),
                          ensure_ascii=False, indent=2)

    def _why_discarded(inp):
        try:
            limit = int(inp.get("limit", MAX_JOURNAL_EVENTS))
        except (TypeError, ValueError):
            limit = MAX_JOURNAL_EVENTS
        limit = max(1, min(limit, MAX_JOURNAL_EVENTS))
        return json.dumps(build_journal_report(journal_path=journal_path, limit=limit),
                          ensure_ascii=False, indent=2)

    return [
        AgentTool(
            "explain_health",
            "Legge i 7 SEMAFORI di salute del bridge (Telegram, messaggio, parser, segnale, CSV, "
            "conferme, modalità) e per ognuno dà stato + dettaglio + un CONSIGLIO su cosa fare se non "
            "è verde. Usalo per «come sta il bridge?», «cosa manca per funzionare?», «perché è rosso?». "
            "Sola lettura.",
            {"type": "object", "properties": {}, "additionalProperties": False},
            READ_ONLY, _explain_health),
        AgentTool(
            "why_discarded",
            "Legge il DIARIO EVENTI e riassume il ciclo di vita degli ultimi segnali (ricevuto → "
            "parsato → validato → scritto, più rifiuti/recovery/riconnessioni) per spiegare perché un "
            "segnale può NON essere arrivato al CSV. Per il motivo esatto (duplicato/troppo vecchio/"
            "parser/CSV) combinalo con l'«ultimo errore» di 'explain_health'. Sola lettura.",
            {"type": "object",
             "properties": {
                 "limit": {"type": "integer",
                           "description": f"quanti eventi recenti mostrare (max {MAX_JOURNAL_EVENTS})"}},
             "additionalProperties": False},
            READ_ONLY, _why_discarded),
    ]


# ── Scrittura config GATED (#41 PR-4) ───────────────────────────────────────────
# L'assistente può scrivere SOLO un piccolo insieme di chiavi NON safety-critical, ognuna con
# validazione/bound espliciti. Le chiavi safety-critical (segreti, filtro chat, modalità/CSV,
# limiti scommesse, parser) sono RIFIUTATE anche su ordine esplicito. Doppia difesa:
# (1) allowlist `WRITABLE_CONFIG_KEYS`: tutto ciò che non è qui è rifiutato;
# (2) denylist `WRITE_FORBIDDEN_KEYS`: rifiuto CHIARO + audit per le chiavi pericolose.
# La scrittura resta comunque gated dal permesso WRITE_CONFIG (offerta solo con `allow_writes=True`).

# Chiavi enum (valori ammessi in forma canonica; match input case-insensitive).
_WRITE_ENUM = {
    "theme": ("dark", "light"),
    "app_language": ("IT", "EN", "ES"),
}
# Chiavi intere con intervallo [min, max] INCLUSIVO. `max_signal_age` ha min > 0 di proposito:
# l'assistente NON può DISATTIVARE il filtro anti-segnale-stantio (0 = off) — invariante di sicurezza.
_WRITE_INT_BOUNDS = {
    "clear_delay":          (5, 3600),
    "confirmation_timeout": (5, 3600),
    "max_signal_age":       (10, 3600),
}
WRITABLE_CONFIG_KEYS = frozenset(_WRITE_ENUM) | frozenset(_WRITE_INT_BOUNDS)

# Denylist esplicita (difesa in profondità): chiavi SAFETY-CRITICAL mai scrivibili dall'assistente,
# nemmeno su ordine esplicito. Già escluse dall'allowlist; qui danno un rifiuto dedicato e tracciano
# l'intento. Coprono segreti, filtro chat, modalità/CSV (contratto XTrader), limiti scommesse, parser.
WRITE_FORBIDDEN_KEYS = frozenset({
    "bot_token", "bot_token_storage",
    "chat_id", "source_chats", "parser_by_chat", "parser_list_by_chat",
    "xtrader_notification_chat_id",
    "bridge_mode", "dry_run", "csv_path", "csv_language",
    "queue_mode", "max_active_signals", "max_per_day",
    "auto_start_listener", "debug_message_payload",
    "active_parser", "provider", "recognition_mode", "source_language",
    "confirmation_keywords", "rejection_keywords",
})


def _validate_writable(key, value):
    """Valida un valore per una chiave scrivibile. Ritorna ``(ok, normalized, err)``.

    NON coerce silenziosamente un valore fuori dominio (a differenza di `config_store._migrate`, che
    è fail-closed sul CARICAMENTO): qui l'assistente deve poter DIRE all'utente cosa non va, quindi
    un valore non valido è RIFIUTATO con un messaggio, non riscritto a un default."""
    if key in _WRITE_ENUM:
        allowed = _WRITE_ENUM[key]
        s = str(value).strip()
        for a in allowed:
            if s.lower() == a.lower():
                return True, a, ""     # forma canonica
        return False, None, f"valori ammessi: {', '.join(allowed)}"
    lo, hi = _WRITE_INT_BOUNDS[key]
    # Intero STRETTO: no bool (sottoclasse di int), no float non intero, no stringa non numerica.
    if isinstance(value, bool):
        return False, None, f"serve un intero tra {lo} e {hi}"
    if isinstance(value, int):
        n = value
    elif isinstance(value, float) and value.is_integer():
        n = int(value)
    else:
        try:
            n = int(str(value).strip())
        except (TypeError, ValueError):
            return False, None, f"serve un intero tra {lo} e {hi}"
    if n < lo or n > hi:
        return False, None, f"fuori intervallo: ammesso {lo}–{hi}"
    return True, n, ""


def _save_outcome(result):
    """Estrae ``(ok, status)`` da un esito di `config_store.save_config` (un `SaveResult`), robusto
    anche a un saver iniettato più semplice (tupla `(cfg, ok)` o bool)."""
    ok = getattr(result, "ok", None)
    status = getattr(result, "status", "")
    if ok is None:
        if isinstance(result, tuple) and len(result) >= 2:
            ok = bool(result[1])
        else:
            ok = bool(result)
    return bool(ok), status


def build_write_tools(*, config_loader=None, on_proposal=None) -> list:
    """Costruisce i tool di **scrittura** config GATED (#41 PR-4). `config_loader` iniettabile (per
    leggere il valore attuale e validare); `on_proposal(key, new, old)` è chiamato quando una
    modifica valida è PROPOSTA.

    **Gate di conferma server-side (review #65 GPT-5.5/Fugu/Fable).** Il tool **non scrive mai**: si
    limita a **validare** e a **proporre** il cambiamento. La scrittura vera è eseguita SOLO
    dall'utente tramite la UI (pulsante «Applica» → `AgentController.apply_pending`), non da un
    booleano deciso dal modello. Così un `confirm` allucinato o indotto (prompt injection) non può
    applicare nulla: al massimo mette in coda una PROPOSTA che l'utente vede e conferma a mano."""
    load_cfg = config_loader or config_store.load_config

    def _set_config_value(inp):
        key = str(inp.get("key", "")).strip()
        # 1. denylist esplicita: chiavi safety-critical → rifiuto dedicato (anche su ordine esplicito).
        if key in WRITE_FORBIDDEN_KEYS:
            return (f"Rifiutato: «{key}» è una chiave SAFETY-CRITICAL (segreti / filtro chat / "
                    "modalità / CSV / limiti scommesse / parser): l'assistente non può modificarla, "
                    "nemmeno su richiesta esplicita.")
        # 2. allowlist: tutto ciò che non è scrivibile → rifiuto.
        if key not in WRITABLE_CONFIG_KEYS:
            return (f"Rifiutato: «{key}» non è modificabile dall'assistente. Chiavi consentite: "
                    f"{', '.join(sorted(WRITABLE_CONFIG_KEYS))}.")
        # 3. validazione stretta (nessuna coercizione silenziosa).
        ok, normalized, err = _validate_writable(key, inp.get("value"))
        if not ok:
            return f"Valore non valido per «{key}»: {err}."
        cfg = load_cfg() or {}
        old = cfg.get(key)
        if normalized == old:
            return f"Nessuna modifica: «{key}» è già «{normalized}»."
        # 4. PROPOSTA (nessuna scrittura): registra la modifica pendente e chiedi conferma UMANA.
        #    L'applicazione avviene SOLO dal pulsante «Applica» dell'utente (server-side gate).
        if on_proposal is not None:
            on_proposal(key, normalized, old)
        return (f"PROPOSTA: cambiare «{key}» da «{old}» a «{normalized}». Chiedi all'utente di "
                "confermare con il pulsante «✅ Applica» nella tab (o «✖ Annulla»); non posso "
                "applicarla io.")

    return [
        AgentTool(
            "set_config_value",
            "Propone di impostare UNA chiave di configurazione NON safety-critical del bridge. "
            "Chiavi ammesse: theme (dark/light), app_language (IT/EN/ES), clear_delay, "
            "confirmation_timeout, max_signal_age (secondi, interi). NON può toccare token, filtro "
            "chat, modalità/CSV, limiti scommesse o parser: sono rifiutati. Il tool NON applica la "
            "modifica: la mette in attesa e l'utente la conferma con un pulsante nella tab. Spiega "
            "all'utente cosa cambierà e invitalo a premere «✅ Applica».",
            {"type": "object",
             "properties": {
                 "key": {"type": "string", "description": "nome della chiave di config da impostare"},
                 "value": {"description": "nuovo valore (stringa o intero secondo la chiave)"}},
             "required": ["key", "value"],
             "additionalProperties": False},
            WRITE_CONFIG, _set_config_value),
    ]


def build_default_registry(*, config_loader=None, parsers_dir=None, on_proposal=None,
                           base_dir=None, health_provider=None, journal_path=None,
                           logger=None) -> ToolRegistry:
    """Registry pronto con i tool sola-lettura (PR-1), conoscenza (PR-7 A), tester (PR-8 B),
    dizionario (PR-9 C), diagnosi salute/diario (PR-10 D) **e** scrittura gated (PR-4). I tool di
    scrittura sono registrati ma **offerti al modello solo con `allow_writes=True`** (li filtra
    `tool_specs`); il gate `dispatch(allow_writes=...)` resta l'ultima difesa; e la scrittura vera è
    gated dalla UI (`on_proposal` → conferma umana), mai dal modello. `base_dir`/`health_provider`/
    `journal_path` sono iniettabili (test / stato live dell'app)."""
    reg = ToolRegistry(logger=logger)
    for tool in build_read_only_tools(config_loader=config_loader, parsers_dir=parsers_dir):
        reg.register(tool)
    for tool in build_guide_tools(base_dir=base_dir):
        reg.register(tool)
    for tool in build_tester_tools(config_loader=config_loader, parsers_dir=parsers_dir):
        reg.register(tool)
    for tool in build_dictionary_tools(config_loader=config_loader):
        reg.register(tool)
    for tool in build_diagnostic_tools(config_loader=config_loader,
                                       health_provider=health_provider, journal_path=journal_path):
        reg.register(tool)
    for tool in build_write_tools(config_loader=config_loader, on_proposal=on_proposal):
        reg.register(tool)
    return reg


# ── Client Anthropic (iniettabile) + impl reale lazy-import fail-safe ───────────

# Base del system prompt SENZA la clausola di lingua (aggiunta da `build_system_prompt`).
_SYSTEM_PROMPT_BASE = (
    "Sei l'assistente di configurazione di XTrader Signal Bridge. Aiuti il proprietario a "
    "configurare e CAPIRE il bridge tramite gli strumenti disponibili, non prendendo iniziative "
    "safety-critical. Non piazzi scommesse, non parli con XTrader/Betfair, non avvii il listener "
    "live o la modalità reale, non riveli segreti, non usi il web né esegui codice: queste azioni "
    "sono bloccate dal bridge a prescindere. Puoi PROPORRE modifiche SOLO ad alcune impostazioni "
    "non critiche (tema, lingua app, clear_delay, confirmation_timeout, max_signal_age) con "
    "'set_config_value': il tool NON applica nulla, mette la modifica in attesa; spiega all'utente "
    "cosa cambierà e invitalo a premere il pulsante «✅ Applica» nella tab per confermare. Per la "
    "PRIMA CONFIGURAZIONE usa 'get_setup_status' per vedere cosa manca allo START e guidare l'utente "
    "passo passo: proponi tu le impostazioni non critiche, ma per i campi CRITICI (token del bot, "
    "chat sorgente, percorso CSV, parser attivo, modalità) NON puoi scriverli — spiega all'utente "
    "come compilarli nei campi della finestra o di aprire «🧙 Wizard prima configurazione» nella tab "
    "Strumenti (che verifica token/chat/CSV dal vivo). "
    # PR-7 Blocco A — conoscenza: puoi leggere la documentazione reale del progetto per spiegare tutto.
    "Puoi CONSULTARE la documentazione del bridge con 'list_guides' (elenco guide) e 'read_guide' "
    "(contenuto di una guida) per spiegare QUALUNQUE pulsante, campo, impostazione o concetto "
    "(parser, dizionario, contratto CSV di XTrader, modalità, sicurezza) e per spiegare COME si "
    "eseguono le azioni che TU non puoi fare (avviare il listener live, passare a modalità reale, "
    "impostare token/chat/CSV/parser/limiti): guidi l'utente a farle passo passo, spiegando anche le "
    "conseguenze, ma NON le esegui tu. Basa le spiegazioni sulle guide reali, non inventare. "
    "REGOLA SUI SEGRETI: non chiedere MAI all'utente di incollare token/API key/chat ID nella chat e "
    "non mostrarli — indica soltanto DOVE inserirli nella finestra. "
    # PR-8 Blocco B — prova messaggio: puoi provare un segnale col parser attivo, senza scrivere.
    "Quando l'utente incolla un messaggio del canale (o chiede «questo va bene?», «cosa uscirebbe nel "
    "CSV?»), usa 'test_message': ti dice se è riconosciuto, il MOTIVO del verdetto e l'anteprima "
    "della riga CSV (colonne e valori) — SENZA scrivere nulla. Spiega all'utente il verdetto, le "
    "colonne e il separatore decimale, e se non è pronto cosa manca; puoi fargli da tester mentre "
    "sistema il parser. L'anteprima è conservativa (senza dizionario Betfair). "
    # PR-9 Blocco C — consulta dizionario: cerca squadre/mercati/mapping e spiega come sono mappati.
    "Per «come è mappata questa squadra/mercato?», «che mercati conosce il bridge?», «cosa significa "
    "questo alias?» usa 'lookup_dictionary': con un termine cerca nel dizionario XTrader e nei profili "
    "di mapping dell'utente (alias Telegram → valori XTrader, squadra → nome Betfair, value-map); "
    "senza termine dà la panoramica. Sola lettura. "
    # PR-10 Blocco D — diagnosi: spiega la salute e perché un segnale è stato scartato.
    "Per «come sta il bridge?», «cosa manca?», «perché è rosso?» usa 'explain_health': i 7 semafori "
    "con stato e un consiglio su cosa fare per quelli non verdi. Per «perché è stato scartato?» / "
    "«perché non è arrivato al CSV?» usa 'why_discarded' (diario eventi: ciclo di vita degli ultimi "
    "segnali) e combinalo con l'«ultimo errore» di 'explain_health' per spiegare il motivo esatto "
    "(duplicato, troppo vecchio, parser non riconosciuto, CSV non scrivibile). Sola lettura. "
)

# Clausola di lingua per la risposta, in base ad app_language (IT/EN/ES); default IT.
_LANG_REPLY_CLAUSE = {
    "IT": "Rispondi in italiano, conciso.",
    "EN": "Reply in English, concise.",
    "ES": "Responde en español, conciso.",
}


def build_system_prompt(app_language="") -> str:
    """System prompt dell'assistente con la clausola di lingua giusta (#41 PR-7 Blocco A). La lingua
    è quella dell'app (`app_language` IT/EN/ES); un valore mancante/sconosciuto → italiano (default
    sicuro). Così l'assistente risponde nella lingua che l'utente ha scelto all'avvio."""
    lang = language_select.normalize_app_language(app_language)     # "IT"/"EN"/"ES" oppure ""
    return _SYSTEM_PROMPT_BASE + _LANG_REPLY_CLAUSE.get(lang, _LANG_REPLY_CLAUSE["IT"])


# Default retro-compatibile (italiano): usato da `ConfigAgent` se il chiamante non passa `system`.
SYSTEM_PROMPT = build_system_prompt("IT")


# P3-24 #76: tetto per singola richiesta HTTP al modello (secondi). Generoso per un
# turno tool-use reale (tipico ~5-20s), ma finito: senza, il default SDK ~10 min
# pinna il worker su una connessione morta.
_API_TIMEOUT_S = 60.0


class RealAnthropicClient:
    """Client reale verso l'Anthropic Messages API (tool use). **Lazy import** di ``anthropic``
    (dipendenza opzionale, come ``keyring`` in ``token_store``): l'assenza della libreria NON
    rompe l'import del modulo — solo l'uso reale solleva un errore chiaro. **Non** esercitato nei
    test (che iniettano un client finto)."""

    def __init__(self, api_key, *, model="claude-opus-4-8", max_tokens=1024):
        self._api_key = api_key
        self._model = model
        self._max_tokens = max_tokens
        self._client = None

    def _ensure(self):
        if self._client is None:
            try:
                import anthropic
            except Exception as exc:   # noqa: BLE001
                raise RuntimeError(
                    "La libreria 'anthropic' non è installata: impossibile contattare il modello. "
                    "Installa 'anthropic' per usare l'assistente.") from exc
            if not self._api_key:
                raise RuntimeError("API key Anthropic assente: impostala prima di usare l'assistente.")
            # P3-24 #76: timeout ESPLICITO — il default dell'SDK (~10 min) terrebbe il
            # worker appeso a una chiamata morta: il join(timeout=5) del teardown
            # fallirebbe e l'assistente resterebbe non riavviabile per minuti (GUI
            # senza risposte). Con 60s la chiamata appesa muore presto, il worker
            # rientra e stop()/enable() tornano a funzionare.
            self._client = anthropic.Anthropic(api_key=self._api_key,
                                               timeout=_API_TIMEOUT_S)
        return self._client

    def create_message(self, *, system, messages, tools) -> dict:
        """Chiama il modello e **normalizza** la risposta nel formato interno
        ``{"stop_reason": str, "content": [block, ...]}`` usato da ``ConfigAgent`` (così l'agente
        non dipende dalla forma esatta dell'SDK)."""
        client = self._ensure()
        resp = client.messages.create(
            model=self._model, max_tokens=self._max_tokens,
            system=system, messages=messages, tools=tools or [])
        blocks = []
        for b in getattr(resp, "content", []) or []:
            btype = getattr(b, "type", None)
            if btype == "text":
                blocks.append({"type": "text", "text": getattr(b, "text", "")})
            elif btype == "tool_use":
                blocks.append({"type": "tool_use", "id": getattr(b, "id", ""),
                               "name": getattr(b, "name", ""), "input": getattr(b, "input", {})})
        return {"stop_reason": getattr(resp, "stop_reason", "end_turn"), "content": blocks}


class AgentTurn:
    """Esito di un turno: ``text`` la risposta finale del modello, ``messages`` la conversazione
    aggiornata (da ripassare al turno dopo), ``tool_results`` gli esiti dei tool eseguiti/rifiutati,
    ``capped`` True se si è raggiunto il tetto di iterazioni tool-use."""

    def __init__(self, text, messages, tool_results, *, capped=False):
        self.text = text
        self.messages = messages
        self.tool_results = tool_results
        self.capped = capped


# P3-25 #76: tetti della cronologia rispedita al modello (e, via `replace()` del
# chiamante, persistita su disco). Ordini di grandezza: 60 messaggi ≈ 20-30 turni
# reali; 200KB ≈ ben sotto la context window ma abbastanza per il contesto utile.
_MAX_HISTORY_MESSAGES = 60
_MAX_HISTORY_BYTES = 200_000


def _cap_history(history) -> list:
    """Coda della cronologia entro i tetti (messaggi E byte), tagliata SOLO su un
    confine SICURO: il primo messaggio del risultato è sempre un turno `user` con
    contenuto TESTUALE. Tagliare altrove spezzerebbe le coppie tool_use/tool_result
    (l'API rifiuta un `tool_result` orfano o un `tool_use` senza risposta) o farebbe
    iniziare la conversazione da un blocco `assistant`. Lista vuota se nulla è
    utilizzabile (l'assistente riparte dal solo messaggio corrente: fail-safe)."""
    msgs = [m for m in (history or []) if isinstance(m, dict)]
    if len(msgs) > _MAX_HISTORY_MESSAGES:
        msgs = msgs[-_MAX_HISTORY_MESSAGES:]
    # Budget byte dal fondo (i turni recenti valgono di più di quelli antichi).
    total, kept = 0, []
    for m in reversed(msgs):
        try:
            total += len(json.dumps(m, ensure_ascii=False).encode("utf-8"))
        except (TypeError, ValueError):
            continue                       # messaggio non serializzabile: scartato
        if kept and total > _MAX_HISTORY_BYTES:
            break
        kept.append(m)
    kept.reverse()
    # Confine sicuro: scarta la testa finché non inizia con un turno utente testuale.
    while kept and not (kept[0].get("role") == "user"
                        and isinstance(kept[0].get("content"), str)):
        kept.pop(0)
    return kept


class ConfigAgent:
    """Loop tool-use dell'assistente. ``client`` è qualunque oggetto con
    ``create_message(system, messages, tools) -> {"stop_reason", "content"}`` (reale o finto).
    ``allow_writes`` resta ``False`` in PR-1 (i tool di scrittura non sono nemmeno esposti)."""

    def __init__(self, registry: ToolRegistry, client, *, system=SYSTEM_PROMPT, allow_writes=False):
        self.registry = registry
        self.client = client
        self.system = system
        self.allow_writes = allow_writes

    def run_turn(self, user_text, history=None) -> AgentTurn:
        """Esegue UN turno completo: manda il messaggio utente, risolve le eventuali chiamate a
        tool (guardate), e ritorna quando il modello smette di chiamare tool (o al cap).

        P3-25 #76: la cronologia in ingresso è CAPATA (`_cap_history`) — senza cap
        veniva rispedita INTEGRALE al modello a ogni turno: costi crescenti e, oltre
        la context window, un 400/413 permanente che uccideva l'assistente. Il cap si
        propaga anche al file su disco: il chiamante fa `history.replace(turn.messages)`
        e `turn.messages` parte dalla cronologia già capata."""
        messages = _cap_history(history)
        messages.append({"role": "user", "content": str(user_text)})
        tool_results_all = []
        for _ in range(MAX_TOOL_ITERATIONS):
            resp = self.client.create_message(
                system=self.system, messages=messages,
                tools=self.registry.tool_specs(include_writes=self.allow_writes))
            content = resp.get("content", []) if isinstance(resp, dict) else []
            messages.append({"role": "assistant", "content": content})
            tool_uses = [b for b in content if b.get("type") == "tool_use"]
            if resp.get("stop_reason") != "tool_use" or not tool_uses:
                text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
                return AgentTurn(text, messages, tool_results_all)
            # Risolve OGNI tool_use del turno tramite le guardie del registry.
            results_blocks = []
            for tu in tool_uses:
                res = self.registry.dispatch(tu.get("name", ""), tu.get("input", {}),
                                             allow_writes=self.allow_writes)
                tool_results_all.append(res)
                results_blocks.append({"type": "tool_result", "tool_use_id": tu.get("id", ""),
                                       "content": res.content})
            messages.append({"role": "user", "content": results_blocks})
        # Cap raggiunto: il modello continua a chiamare tool → si ferma per sicurezza.
        return AgentTurn("", messages, tool_results_all, capped=True)


# ── Persistenza cronologia conversazione (#41 PR-2) ─────────────────────────────
# La cronologia rende l'assistente «consapevole di dove siamo» tra un avvio e l'altro. Vive nella
# cartella dati utente (`config_store.config_dir()` → %APPDATA%/$XDG_CONFIG_HOME) ed è scritta in
# modo ATOMICO e SEMPRE REDATTA: API key/bot token/chat non finiscono mai in chiaro nel file.
HISTORY_FILENAME = "assistant_history.json"
HISTORY_SCHEMA_VERSION = 1


def history_path(config_dir=None) -> str:
    """Path del file cronologia (default: nella cartella dati dell'app)."""
    base = config_dir if config_dir is not None else config_store.config_dir()
    return os.path.join(base, HISTORY_FILENAME)


# Marker di redazione e guardia anti-frammento per i literal di sessione (es. chat_id).
_EXTRA_REDACTED = "[REDACTED_TOKEN]"
_MIN_EXTRA_SECRET_LEN = 8


def _redact_str(s: str, extra_literals=()) -> str:
    """Redige una stringa: prima i segreti noti a `event_log` (bot token/sk-ant/registrati), poi i
    literal di sessione passati esplicitamente (es. chat_id). I literal usano le STESSE primitive
    robuste di `event_log` — forme derivate (`_secret_forms`: grezzo + URL-encoded) e match
    **CRLF-tollerante** (`_crlf_tolerant_re`) — ma applicate in **locale**, SENZA registrare nulla
    nel registro globale (evita la de-registrazione accidentale, Fable/Fugu #63)."""
    return event_log.redact_extra(s, extra_literals)


def _deep_redact(obj, extra_literals=()):
    """Redige RICORSIVAMENTE i messaggi preservando la struttura: testo utente/assistente,
    `tool_use.input`, `tool_result.content`, nomi. Copre anche:
    - le **chiavi** dei dict (GLM/GPT #63: un segreto usato come chiave non resta in chiaro; le
      chiavi strutturali legittime non sono toccate da `redact_secrets`). Se due chiavi distinte
      redigono allo STESSO marker, l'entry NON viene persa: si disambigua con un suffisso
      (evita la collisione silenziosa segnalata da Fable/GPT #63);
    - gli **scalari numerici** (Fugu #63: un `chat_id`/segreto passato come `int`/`float` in un
      `tool_use.input` verrebbe altrimenti serializzato in chiaro) — se la forma-stringa contiene
      un segreto si restituisce il marker, altrimenti il numero originale (tipo preservato)."""
    if isinstance(obj, str):
        return _redact_str(obj, extra_literals)
    if isinstance(obj, bool):
        return obj   # `bool` è sottoclasse di `int`: va escluso PRIMA del ramo numerico
    if isinstance(obj, (int, float)):
        red = _redact_str(str(obj), extra_literals)
        return red if red != str(obj) else obj
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            rk = _deep_redact(k, extra_literals)
            rk = rk if isinstance(rk, str) else str(rk)
            # Le chiavi-SORGENTE sono uniche: se `rk` è già in `out`, DUE chiavi distinte hanno
            # prodotto lo stesso marker → disambigua SEMPRE (Fable #63: la condizione `rk != k`
            # lasciava sovrascrivere una chiave-segreta redatta da una chiave strutturale già
            # uguale al marker, con perdita silenziosa dell'entry).
            if rk in out:
                n = 2
                while f"{rk}#{n}" in out:
                    n += 1
                rk = f"{rk}#{n}"
            out[rk] = _deep_redact(v, extra_literals)
        return out
    if isinstance(obj, list):
        return [_deep_redact(x, extra_literals) for x in obj]
    return obj


class ConversationHistory:
    """Cronologia persistente della conversazione con l'assistente (#41 PR-2).

    In RAM tiene i `messages` nel formato di `ConfigAgent` (la sessione ha il contesto pieno); su
    **disco** viene scritta SEMPRE REDATTA (nessun segreto in chiaro). Flusso tipico del chiamante:

        h = ConversationHistory.load()
        turn = agent.run_turn(testo_utente, history=h.messages)
        h.replace(turn.messages)
        h.save(extra_secrets=[cfg.get("chat_id")])   # chat_id di sessione redatto in aggiunta
    """

    def __init__(self, messages=None):
        self.messages = list(messages or [])

    def is_empty(self) -> bool:
        return not self.messages

    def append(self, message) -> None:
        self.messages.append(message)

    def extend(self, messages) -> None:
        self.messages.extend(messages or [])

    def replace(self, messages) -> None:
        """Sostituisce l'intera cronologia (es. con `turn.messages` dopo un turno)."""
        self.messages = list(messages or [])

    def redacted_messages(self, *, extra_secrets=()):
        """Vista REDATTA dei messaggi senza persistere. `extra_secrets` (es. il `chat_id` di
        sessione) sono mascherati per **replace LOCALE**: NON si tocca il registro globale di
        `event_log` — così un segreto già registrato dall'app non viene mai de-registrato per
        sbaglio (regressione/race, Fable & Fugu #63). Guardia anti-frammento: solo i literal
        >= `_MIN_EXTRA_SECRET_LEN` sono mascherati (i chat ID reali Telegram `-100…` sono lunghi e
        coperti; un valore cortissimo non si redige per non mascherare sottostringhe banali)."""
        lits = [str(s) for s in (extra_secrets or [])
                if s and len(str(s)) >= _MIN_EXTRA_SECRET_LEN]
        return _deep_redact(self.messages, lits)

    def save(self, path=None, *, config_dir=None, extra_secrets=()) -> str:
        """Scrive la cronologia REDATTA su disco in modo ATOMICO. Ritorna il path scritto."""
        p = path or history_path(config_dir)
        parent = os.path.dirname(p)
        if parent:
            os.makedirs(parent, exist_ok=True)
        payload = {"version": HISTORY_SCHEMA_VERSION,
                   "messages": self.redacted_messages(extra_secrets=extra_secrets)}
        atomic_io.atomic_write_json(p, payload, ensure_ascii=False, indent=2)
        return p

    @classmethod
    def load(cls, path=None, *, config_dir=None):
        """Carica la cronologia dal file. **Fail-safe**: file assente, JSON corrotto o forma
        inattesa → cronologia VUOTA (l'assistente riparte pulito, non crasha)."""
        p = path or history_path(config_dir)
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return cls([])
        except (ValueError, OSError):
            # JSON corrotto / file illeggibile → cronologia vuota (fail-safe).
            return cls([])
        msgs = data.get("messages") if isinstance(data, dict) else None
        if not isinstance(msgs, list):
            return cls([])
        # Tiene SOLO i messaggi ben formati (dict con "role"): un file editato a mano con elementi
        # malformati non deve iniettare payload incompatibili nel client LLM (GPT #63).
        return cls([m for m in msgs if isinstance(m, dict) and "role" in m])
