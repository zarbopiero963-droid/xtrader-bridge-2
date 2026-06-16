"""Mapping alias Telegram → selezione XTrader in italiano (PR-08).

Usa il dizionario reale (`data/dizionario_xtrader.csv`) per tradurre un alias
del segnale in MarketType / MarketName / SelectionName italiani, sostituendo i
placeholder dinamici ({HOME_TEAM}/{AWAY_TEAM}). Rende operativo il dizionario di
PR-07: niente più SelectionName inglesi tipo "Over 0.5 Goals" quando l'alias è
riconosciuto.

`resolve(market_alias, selection_alias)` lavora sugli alias propri del dizionario.
`resolve_shorthand(text)` accetta le forme brevi dei messaggi Telegram
(es. "OVER 2.5", "GG", "1") tramite la tabella SYNONYMS.
Alias sconosciuto → None (il chiamante decide; il blocco duro è PR-10).
"""

from .dizionario import alias_key, load_dizionario

# Forme brevi dei messaggi Telegram → (MarketAliasTelegram, SelectionAliasTelegram)
# del dizionario. Le chiavi sono già normalizzate (minuscolo, spazi singoli,
# virgola→punto). Set iniziale: il parser robusto (PR-09) ne amplierà la copertura.
SYNONYMS = {
    "1":          ("esito_finale", "1"),
    "x":          ("esito_finale", "x"),
    "2":          ("esito_finale", "2"),
    "gg":         ("goal_no_goal", "goal"),
    "goal":       ("goal_no_goal", "goal"),
    "ng":         ("goal_no_goal", "no goal"),
    "no goal":    ("goal_no_goal", "no goal"),
    "over 0.5":   ("over_under_0.5_ft", "over 0.5 ft"),
    "under 0.5":  ("over_under_0.5_ft", "under 0.5 ft"),
    "over 1.5":   ("over_under_1.5_ft", "over 1.5 ft"),
    "under 1.5":  ("over_under_1.5_ft", "under 1.5 ft"),
    "over 2.5":   ("over_under_2.5_ft", "over 2.5 ft"),
    "under 2.5":  ("over_under_2.5_ft", "under 2.5 ft"),
    "over 3.5":   ("over_under_3.5_ft", "over 3.5 ft"),
    "under 3.5":  ("over_under_3.5_ft", "under 3.5 ft"),
}

_INDEX = None


def _index() -> dict:
    """Indice (lazy, in cache) del dizionario per chiave alias normalizzata."""
    global _INDEX
    if _INDEX is None:
        _INDEX = {}
        for row in load_dizionario():
            _INDEX[alias_key(row["MarketAliasTelegram"], row["SelectionAliasTelegram"])] = row
    return _INDEX


def _norm_shorthand(text: str) -> str:
    # minuscolo, spazi singoli, virgola→punto (decimali "2,5" -> "2.5").
    return " ".join(str(text).strip().lower().replace(",", ".").split())


def _subst(value: str, home: str, away: str) -> str:
    out = str(value)
    if home:
        out = out.replace("{HOME_TEAM}", home)
    if away:
        out = out.replace("{AWAY_TEAM}", away)
    return out


def resolve(market_alias: str, selection_alias: str, home: str = "", away: str = ""):
    """Risolve una coppia di alias del dizionario in una selezione XTrader.

    Ritorna un dict (MarketType/MarketName/SelectionName/Handicap/BetType) con i
    placeholder sostituiti, oppure None se la coppia non è nel dizionario.
    """
    row = _index().get(alias_key(market_alias, selection_alias))
    if not row:
        return None
    return {
        "MarketType":    row["MarketType_XTrader"],
        "MarketName":    _subst(row["MarketName_XTrader"], home, away),
        "SelectionName": _subst(row["SelectionName_XTrader"], home, away),
        "Handicap":      row["Handicap"] or "0",
        "BetType":       row["BetType_XTrader"],
    }


def resolve_shorthand(text: str, home: str = "", away: str = ""):
    """Risolve una forma breve Telegram (es. "OVER 2.5", "GG", "1") via SYNONYMS.

    Ritorna lo stesso dict di `resolve()`, oppure None se la forma non è mappata.
    """
    pair = SYNONYMS.get(_norm_shorthand(text))
    if not pair:
        return None
    return resolve(pair[0], pair[1], home, away)
