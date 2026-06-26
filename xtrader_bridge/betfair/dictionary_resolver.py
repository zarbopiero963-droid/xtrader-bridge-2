"""Risoluzione degli ID Betfair dal dizionario locale (issue #86 PR-P12).

Dopo che il parser + la mappatura nomi/mercati hanno prodotto una riga a **nomi**
(EventName canonico, MarketType/MarketName, SelectionName), questo modulo prova a
trovare nel **dizionario Betfair locale** gli identificatori precisi
(`EventId`/`MarketId`/`SelectionId`) per quella combinazione, ristretta allo **sport**
del parser (event_type_id, fonte unica `xtrader_bridge.sports`).

Regola di flusso (dall'issue): *se trova gli ID usa l'identificazione precisa; se NON
trova, fallback alla modalità a nomi XTrader*. Quindi la risoluzione è **best-effort e
fail-open**: non blocca mai il segnale. È inoltre **all-or-nothing e conservativa**:
ritorna gli ID **solo** quando l'intera catena evento → mercato → selezione si risolve
in modo **univoco**; qualunque assenza o ambiguità → nessun ID (la riga resta a nomi),
così non si scrive mai un identificatore sbagliato (un evento sbagliato = scommessa
sbagliata). Sola lettura: solo `SELECT` via i metodi di lettura del DB; nessuna rete,
nessuna scrittura, nessuna operazione di scommessa.

Limiti noti (by-design, sempre **fail-open** ai nomi):

- la selezione è confrontata per `runner_name` (nome Betfair grezzo, es. "The Draw",
  "Yes", "Over 2.5 Goals"). Per le selezioni-squadra (Match Odds) coincide con il nome
  canonicalizzato dalla mappatura nomi; per selezioni generiche il cui nome XTrader
  differisce dal runner Betfair ("Pareggio"/"Sì"/"Over 2,5 gol") la corrispondenza può
  non avvenire: in tal caso si ritorna `{}` e la riga resta a nomi (nessun ID errato, mai
  bloccato). Una traduzione XTrader↔runner Betfair completa è fuori dallo scope di P12;
- per ottenere "ID se trovato, altrimenti nomi" la modalità del parser deve essere
  **name-capable** (`NAME_ONLY` o `BOTH`): con `BOTH` la riga è valida sia con la tripla ID
  (dizionario trovato) sia coi soli nomi (dizionario mancante). Un parser `ID_ONLY` che si
  affida al dizionario per gli ID resta, per scelta, **fail-closed** su un miss (non si
  declassa in silenzio la modalità scelta dall'utente).
"""

from .. import sports
from ..dizionario import normalize


def _active(rows):
    out = []
    for r in rows:
        try:
            if int(r.get("active", 0)) == 1:
                out.append(r)
        except (TypeError, ValueError):
            continue
    return out


def _split_event_name(event_name: str):
    """Divide l'EventName canonico "Casa - Trasferta" in ``(casa, trasferta)`` normalizzati,
    o ``None`` se non c'è il separatore " - " (lo stesso prodotto da
    `dizionario.compose_event_name`)."""
    parts = str(event_name or "").split(" - ", 1)
    if len(parts) != 2:
        return None
    home, away = parts[0].strip(), parts[1].strip()
    if not home or not away:
        return None
    return normalize(home), normalize(away)


def _hcap_value(v):
    """Handicap come float per il confronto numerico, o ``None`` se non numerico.
    Accetta la **virgola** decimale ("1,5") oltre al punto, perché il parser può fornire
    l'handicap con la virgola mentre SQLite lo memorizza come REAL ("1.5") — un confronto
    testuale fallirebbe (Codex)."""
    s = str(v if v is not None else "").strip().replace(",", ".")
    if not s:
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _unique(values):
    """L'unico valore della collezione se è esattamente uno (e non vuoto), altrimenti
    ``None`` (zero o ambiguo)."""
    uniq = {v for v in values if v}
    if len(uniq) == 1:
        return next(iter(uniq))
    return None


class DictionaryResolver:
    """Risolve gli ID Betfair dal dizionario locale (`BetfairLocalDB`), sola lettura.

    `db` è iniettabile nei test. Nessuno stato: ogni `resolve_ids` interroga il DB."""

    def __init__(self, db):
        self.db = db

    def resolve_ids(self, *, sport, event_name, market_type="", market_name="",
                    selection_name="", handicap="") -> dict:
        """Ritorna ``{"EventId","MarketId","SelectionId"}`` se l'intera catena evento →
        mercato → selezione si risolve in modo univoco per lo `sport` dato; altrimenti
        ``{}`` (la riga resta a nomi: fallback). Non solleva sui dati: input ambigui o
        assenti danno semplicemente ``{}``."""
        etid = sports.event_type_id_for_sport(sport)
        if not etid:
            return {}   # sport non specificato/ignoto → nessun scoping affidabile

        event_id = self._match_event(etid, event_name)
        if not event_id:
            return {}
        market_id = self._match_market(event_id, market_type, market_name)
        if not market_id:
            return {}
        selection_id = self._match_selection(market_id, selection_name, handicap)
        if not selection_id:
            return {}
        return {"EventId": event_id, "MarketId": market_id, "SelectionId": selection_id}

    # ── livelli ────────────────────────────────────────────────────────────────
    def _match_event(self, etid, event_name):
        """EventId UNICO il cui nome combacia (normalizzato) o i cui partecipanti
        coincidono (in qualunque ordine) con "Casa - Trasferta"; altrimenti ``None``."""
        target_name = normalize(event_name)
        pair = _split_event_name(event_name)
        matches = []
        for ev in _active(self.db.fetchall("betfair_events")):
            if str(ev.get("event_type_id", "")) != etid:
                continue
            if target_name and normalize(ev.get("name", "")) == target_name:
                matches.append(ev.get("event_id"))
                continue
            if pair is not None:
                p1 = normalize(ev.get("participant_1", ""))
                p2 = normalize(ev.get("participant_2", ""))
                if p1 and p2 and {p1, p2} == set(pair):
                    matches.append(ev.get("event_id"))
        return _unique(matches)

    def _match_market(self, event_id, market_type, market_name):
        """MarketId UNICO dell'evento che combacia per `market_type` (preferito) o, in
        sua assenza, per `market_name` (normalizzati); altrimenti ``None``."""
        mtype = normalize(market_type)
        mname = normalize(market_name)
        if not mtype and not mname:
            return None
        matches = []
        for mk in _active(self.db.fetchall("betfair_markets")):
            if str(mk.get("event_id", "")) != str(event_id):
                continue
            if mtype and normalize(mk.get("market_type", "")) == mtype:
                matches.append(mk.get("market_id"))
            elif not mtype and mname and normalize(mk.get("market_name", "")) == mname:
                matches.append(mk.get("market_id"))
        return _unique(matches)

    def _match_selection(self, market_id, selection_name, handicap):
        """SelectionId UNICO del mercato il cui `runner_name` combacia (normalizzato) **e**
        il cui handicap **coincide** con quello della riga; altrimenti ``None``.

        L'handicap deve SEMPRE concordare, anche con una sola selezione omonima (Codex P1):
        altrimenti una riga con `Handicap=0` verrebbe arricchita con la SelectionId della
        linea +1.5 — un ID che punta a un mercato/linea diverso da quello del segnale. Il
        confronto è numerico (virgola→punto→float); handicap assente/non numerico = 0
        (default di contratto), così i mercati senza handicap (es. Match Odds, selezioni a
        0) combaciano normalmente."""
        target = normalize(selection_name)
        if not target:
            return None
        row_h = _hcap_value(handicap)
        if row_h is None:
            row_h = 0.0
        matches = []
        for s in _active(self.db.get_selections(market_id)):
            if normalize(s.get("runner_name", "")) != target:
                continue
            sel_h = _hcap_value(s.get("handicap"))
            if sel_h is None:
                sel_h = 0.0
            if sel_h == row_h:
                matches.append(s.get("selection_id"))
        return _unique(matches)
