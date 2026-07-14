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

from . import atomic_io, config_store, custom_parser, event_log, health_check, log_privacy

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
    ]


def build_default_registry(*, config_loader=None, parsers_dir=None, logger=None) -> ToolRegistry:
    """Registry pronto con i tool sola-lettura di PR-1."""
    reg = ToolRegistry(logger=logger)
    for tool in build_read_only_tools(config_loader=config_loader, parsers_dir=parsers_dir):
        reg.register(tool)
    return reg


# ── Client Anthropic (iniettabile) + impl reale lazy-import fail-safe ───────────

SYSTEM_PROMPT = (
    "Sei l'assistente di configurazione di XTrader Signal Bridge. Aiuti il proprietario a "
    "configurare il bridge ESEGUENDO i suoi ordini tramite gli strumenti disponibili, non "
    "prendendo iniziative safety-critical. Non piazzi scommesse, non parli con XTrader/Betfair, "
    "non avvii il listener live o la modalità reale, non riveli segreti, non usi il web né esegui "
    "codice: queste azioni sono bloccate dal bridge a prescindere. Rispondi in italiano, conciso."
)


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
    literal di sessione passati esplicitamente (es. chat_id) — per replace LOCALE, senza toccare il
    registro globale."""
    out = event_log.redact_secrets(s)
    for lit in extra_literals:
        if lit:
            out = out.replace(lit, _EXTRA_REDACTED)
    return out


def _deep_redact(obj, extra_literals=()):
    """Redige RICORSIVAMENTE i messaggi preservando la struttura: testo utente/assistente,
    `tool_use.input`, `tool_result.content`, nomi. Copre anche:
    - le **chiavi** dei dict (GLM/GPT #63: un segreto usato come chiave non resta in chiaro; le
      chiavi strutturali legittime non sono toccate da `redact_secrets`);
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
        return {_deep_redact(k, extra_literals): _deep_redact(v, extra_literals)
                for k, v in obj.items()}
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
