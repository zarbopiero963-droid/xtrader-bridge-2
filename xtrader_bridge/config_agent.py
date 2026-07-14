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

from . import (atomic_io, bridge_mode, config_store, custom_parser, event_log, health_check,
               language_select, log_privacy, wizard)

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
                           base_dir=None, logger=None) -> ToolRegistry:
    """Registry pronto con i tool sola-lettura (PR-1), i tool di conoscenza (PR-7 Blocco A) **e** i
    tool di scrittura gated (PR-4). I tool di scrittura sono registrati ma **offerti al modello solo
    con `allow_writes=True`** (li filtra `tool_specs`); il gate `dispatch(allow_writes=...)` resta
    l'ultima difesa; e la scrittura vera è gated dalla UI (`on_proposal` → conferma umana), mai dal
    modello. `base_dir` è iniettabile per i test (radice da cui leggere le guide)."""
    reg = ToolRegistry(logger=logger)
    for tool in build_read_only_tools(config_loader=config_loader, parsers_dir=parsers_dir):
        reg.register(tool)
    for tool in build_guide_tools(base_dir=base_dir):
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
            self._client = anthropic.Anthropic(api_key=self._api_key)
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
        tool (guardate), e ritorna quando il modello smette di chiamare tool (o al cap)."""
        messages = list(history or [])
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
