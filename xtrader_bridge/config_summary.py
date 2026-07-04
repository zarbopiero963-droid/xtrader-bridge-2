"""#293 (slice 3): riepilogo READ-ONLY della configurazione — logica pura, testabile.

La schermata «Riepilogo configurazione» dà il **colpo d'occhio** su ciò che il bridge
farà davvero, senza saltare tra le schede Generale/Betfair/Chat sorgenti/Parser/Mapping:

- **Modalità**: Simulazione (DRY_RUN) vs REALE;
- **Betfair**: dizionario sincronizzato sì/no + login attivo sì/no;
- **per ogni canale** → parser assegnato → traduzioni (nomi/mercati) attive → «Pronto?».

Questo modulo è **puro**: non tocca GUI, Telegram, CSV, rete o config su disco. Riusa gli
STESSI predicati che governano il runtime (`signal_router`, `parser_manager`,
`safety_guard`, `*_mapping_store`), così il riepilogo **non può divergere** da ciò che il
listener processa davvero. È **sola lettura**: nessuna funzione qui scrive o modifica nulla.

«Pronto?» è **severo** (scelta del proprietario) e coerente col fail-closed del runtime: un
canale è pronto solo se è ascoltabile (chat_id presente + sorgente attiva), ha un parser che
**si carica ed è valido**, e tutte le mappature selezionate **si risolvono** (nessun profilo
fantasma `⚠`). Qualsiasi anello mancante → «non pronto» con il motivo, mai un falso verde.
"""

from dataclasses import dataclass, field

from . import (
    market_mapping_store,
    name_mapping_store,
    parser_manager,
    safety_guard,
    signal_router,
    source_manager,
)

# Motivi di «non pronto» (prefissi STABILI: i test vi si ancorano). I primi due prefissi
# possono essere completati con un dettaglio dinamico (nome parser / elenco profili).
REASON_NO_CHAT_ID = "Manca chat_id"
REASON_DISABLED = "Sorgente disattivata"
REASON_NO_PARSER = "Nessun parser assegnato"
REASON_PARSER_UNLOADABLE = "Parser non caricabile"        # + ": <nome>"
REASON_MISSING_TRANSLATION = "Traduzione mancante"        # + ": <profili>"


@dataclass(frozen=True)
class TranslationSummary:
    """Stato delle traduzioni (profili di mappatura) di UN tipo (nomi o mercati) per un
    canale. `resolved` = profili selezionati che esistono davvero; `missing` = selezionati
    ma **non risolti** (fantasma `⚠`): un fantasma NON conta come traduzione attiva e rende
    il canale non pronto (coerente col fail-closed di `*_mapping_store`)."""

    resolved: tuple = ()
    missing: tuple = ()

    @property
    def count(self) -> int:
        """Numero di traduzioni ATTIVE (solo i profili risolti)."""
        return len(self.resolved)

    @property
    def has_missing(self) -> bool:
        return bool(self.missing)


@dataclass(frozen=True)
class ChannelSummary:
    """Riga di riepilogo per un canale: da dove arriva, che parser usa, quali traduzioni
    sono attive e se è «Pronto?» (con il motivo se non lo è)."""

    chat_id: str
    name: str
    enabled: bool
    parser_name: str            # nome del parser risolto ("" = nessuno)
    parser_loaded: bool         # True se il parser si carica ed è valido (fail-closed)
    names: TranslationSummary = field(default_factory=TranslationSummary)
    markets: TranslationSummary = field(default_factory=TranslationSummary)
    ready: bool = False
    reason: str = ""            # motivo se non pronto ("" quando ready=True)


@dataclass(frozen=True)
class ConfigSummary:
    """Riepilogo completo, sola lettura, della configurazione corrente."""

    real_mode: bool             # True = REALE, False = Simulazione (DRY_RUN)
    betfair_synced: bool        # dizionario Betfair locale presente (sync fatta)
    betfair_logged_in: bool     # sessione Betfair attiva (token RAM, non persistito)
    channels: tuple = ()        # tuple[ChannelSummary], ordine di presentazione

    @property
    def total_channels(self) -> int:
        return len(self.channels)

    @property
    def ready_channels(self) -> int:
        return sum(1 for c in self.channels if c.ready)


def _channel_rows(cfg: dict) -> list:
    """Elenco dei canali da riepilogare, in ordine di presentazione: prima le
    **sorgenti** configurate (`source_chats`, comprese quelle disattivate, nell'ordine di
    config), poi gli eventuali canali ammessi ma **senza voce sorgente** (il `chat_id`
    legacy mono-chat o una chiave `parser_by_chat`), ordinati per id. Ogni riga è
    `{chat_id, name, enabled}`. Copre così l'intero insieme che il listener ascolterebbe
    più le sorgenti spente (visibilità), senza duplicati."""
    rows = []
    seen = set()
    for s in source_manager.source_chats(cfg):
        rows.append({"chat_id": s["chat_id"], "name": s["name"], "enabled": s["enabled"]})
        seen.add(s["chat_id"])
    extra = sorted(cid for cid in signal_router.allowed_chats(cfg)
                   if cid and cid not in seen)
    for cid in extra:
        rows.append({"chat_id": cid, "name": "", "enabled": True})
    return rows


def _translation_summary(selected, existing: set) -> TranslationSummary:
    """Divide i profili SELEZIONATI da un parser in risolti (esistono nello store) e
    mancanti (fantasma `⚠`). Preserva l'ordine di selezione. Stessa distinzione risolto/
    fantasma usata dall'indicatore «🔗 Traduzioni attive» del Parser (#293 slice 2)."""
    sel = [str(p).strip() for p in (selected or []) if str(p or "").strip()]
    resolved = tuple(p for p in sel if p in existing)
    missing = tuple(p for p in sel if p not in existing)
    return TranslationSummary(resolved=resolved, missing=missing)


def summarize_channel(cfg: dict, row: dict, *, existing_names: set,
                      existing_markets: set, parsers_dir: str = None) -> ChannelSummary:
    """Riepilogo severo di UN canale. `existing_names`/`existing_markets` sono gli insiemi
    dei profili di mappatura esistenti (passati dal chiamante per calcolarli una sola
    volta). Fail-closed: qualsiasi anello mancante → non pronto, mai un falso «Pronto»."""
    chat_id = str(row.get("chat_id", "") or "").strip()
    name = str(row.get("name", "") or "").strip()
    enabled = bool(row.get("enabled", True))

    parser_name = parser_manager.resolve_parser_name(cfg, chat_id)
    defn = parser_manager.load_active(cfg, chat_id, parsers_dir) if parser_name else None
    parser_loaded = defn is not None

    names = _translation_summary(
        defn.name_mapping_profiles if defn else (), existing_names)
    markets = _translation_summary(
        defn.market_mapping_profiles if defn else (), existing_markets)

    # «Pronto?» severo, in ordine di precedenza (dal problema più a monte).
    if not chat_id:
        ready, reason = False, REASON_NO_CHAT_ID
    elif not enabled:
        ready, reason = False, REASON_DISABLED
    elif not parser_name:
        ready, reason = False, REASON_NO_PARSER
    elif not parser_loaded:
        ready, reason = False, f"{REASON_PARSER_UNLOADABLE}: {parser_name}"
    elif names.has_missing or markets.has_missing:
        miss = ", ".join(names.missing + markets.missing)
        ready, reason = False, f"{REASON_MISSING_TRANSLATION}: {miss}"
    else:
        ready, reason = True, ""

    return ChannelSummary(
        chat_id=chat_id, name=name, enabled=enabled, parser_name=parser_name,
        parser_loaded=parser_loaded, names=names, markets=markets,
        ready=ready, reason=reason)


def parser_translation_flags(cfg: dict, parser_name, *, parsers_dir: str = None):
    """`(nomi_attive, mercati_attive)` booleani per il parser `parser_name`: ``True`` se il
    parser seleziona almeno un profilo di mappatura **risolto** (esistente) di quel tipo — la
    stessa nozione di «traduzione attiva» del Riepilogo (#293). Parser vuoto o non caricabile →
    `(False, False)` (fail-closed: nessun falso ✓). Usato dai chip «Traduzioni» di Chat sorgenti
    (#293 slice 6). Puro: nessuna GUI; `load_active` è già fail-safe (file mancante/invalido →
    None), quindi non solleva."""
    name = str(parser_name or "").strip()
    if not name:
        return (False, False)
    defn = parser_manager.load_active({"active_parser": name}, "", parsers_dir)
    if defn is None:
        return (False, False)
    cfg = cfg if isinstance(cfg, dict) else {}
    names_existing = set(name_mapping_store.profile_names(cfg))
    markets_existing = set(market_mapping_store.profile_names(cfg))
    names_active = any(p in names_existing for p in defn.name_mapping_profiles)
    markets_active = any(p in markets_existing for p in defn.market_mapping_profiles)
    return (names_active, markets_active)


def summarize_config(cfg: dict, *, betfair_synced: bool = False,
                     betfair_logged_in: bool = False,
                     parsers_dir: str = None) -> ConfigSummary:
    """Costruisce il riepilogo READ-ONLY della configurazione.

    `betfair_synced`/`betfair_logged_in` sono passati dal chiamante (letti dal DB/sessione
    Betfair, che questo modulo puro non conosce), così l'aggregazione resta testabile senza
    rete né SQLite. `parsers_dir` = cartella dei parser (default → `custom_parser`)."""
    cfg = cfg if isinstance(cfg, dict) else {}
    existing_names = set(name_mapping_store.profile_names(cfg))
    existing_markets = set(market_mapping_store.profile_names(cfg))
    channels = tuple(
        summarize_channel(cfg, row, existing_names=existing_names,
                          existing_markets=existing_markets, parsers_dir=parsers_dir)
        for row in _channel_rows(cfg))
    return ConfigSummary(
        real_mode=not safety_guard.is_dry_run(cfg),
        betfair_synced=bool(betfair_synced),
        betfair_logged_in=bool(betfair_logged_in),
        channels=channels)
