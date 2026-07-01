"""Test della diagnostica del Parser Personalizzato (CP-08b): esito per-campo.

Esercita la catena reale estrazione→transform→value-map→validazione e i codici
errore mostrati in "Prova messaggio". Niente GUI, niente CSV reale, niente token.
"""

from xtrader_bridge import parser_diagnostics as pd
from xtrader_bridge import recognition, value_maps
from xtrader_bridge.custom_parser import CustomParserDef, FieldRule

_BUILTIN = value_maps.registry()   # built-in (niente lettura dizionario/CSV)


def _defn(*rules):
    return CustomParserDef(name="T", rules=list(rules))


def _f(diag, target):
    return next(f for f in diag.fields if f.target == target)


def _full_name_rules(**over):
    """Set NAME_ONLY valido a valori fissi + Price/BetType, sovrascrivibile."""
    rules = {
        "Provider": FieldRule(target="Provider", fixed_value="TG"),
        "EventName": FieldRule(target="EventName", fixed_value="Inter v Milan", required=True),
        "MarketType": FieldRule(target="MarketType", fixed_value="MATCH_ODDS", required=True),
        "SelectionName": FieldRule(target="SelectionName", fixed_value="Pareggio", required=True),
        "BetType": FieldRule(target="BetType", fixed_value="PUNTA", required=True),
        "Price": FieldRule(target="Price", fixed_value="1.85", required=True),
    }
    rules.update(over)
    return _defn(*rules.values())


# ── caso pronto ─────────────────────────────────────────────────────────────

def test_pronto_tutti_ok():
    defn = _full_name_rules(
        EventName=FieldRule(target="EventName", start_after="🆚", required=True),
        Price=FieldRule(target="Price", start_after="Quota", required=True),
    )
    diag = pd.diagnose(defn, "🆚Inter v Milan\nQuota 1.85",
                       provider="TG", mode=recognition.NAME_ONLY,
                       value_maps_registry=_BUILTIN)
    assert diag.placeable is True
    assert diag.message_error == ""
    assert all(f.ok for f in diag.fields)
    assert _f(diag, "EventName").final == "Inter v Milan"
    assert _f(diag, "Price").final == "1.85"


# ── errori di estrazione ──────────────────────────────────────────────────────

def test_start_not_found():
    defn = _defn(FieldRule(target="EventName", start_after="🆚", required=True))
    diag = pd.diagnose(defn, "nessun emoji qui", value_maps_registry=_BUILTIN)
    fd = _f(diag, "EventName")
    assert fd.error == pd.START_NOT_FOUND
    assert fd.raw == ""
    assert diag.placeable is False


def test_end_not_found():
    defn = _defn(FieldRule(target="EventName", start_after="A:", end_before="|", required=True))
    diag = pd.diagnose(defn, "A: Inter v Milan", value_maps_registry=_BUILTIN)
    assert _f(diag, "EventName").error == pd.END_NOT_FOUND


def test_required_empty_senza_estrazione():
    # Regola obbligatoria senza fixed/start/end (come da skeleton): vuota → REQUIRED_EMPTY.
    defn = _defn(FieldRule(target="EventName", required=True))
    diag = pd.diagnose(defn, "qualsiasi", value_maps_registry=_BUILTIN)
    assert _f(diag, "EventName").error == pd.REQUIRED_EMPTY


def test_optional_vuoto_non_blocca():
    defn = _defn(FieldRule(target="MarketName", start_after="ZZZ", required=False))
    diag = pd.diagnose(defn, "nessun marker", value_maps_registry=_BUILTIN)
    fd = _f(diag, "MarketName")
    # start non trovato: lo segnaliamo, ma essendo opzionale non è un OK-fittizio.
    assert fd.error == pd.START_NOT_FOUND
    assert fd.required is False


# ── value-map ────────────────────────────────────────────────────────────────

def test_value_map_miss():
    # value-map che non trova il valore (registry vuoto → mappa sconosciuta → "").
    defn = _defn(FieldRule(target="SelectionName", start_after="Sel:",
                           value_map="selectionname", required=True))
    diag = pd.diagnose(defn, "Sel: valore_inesistente", value_maps_registry={})
    fd = _f(diag, "SelectionName")
    assert fd.raw == "valore_inesistente"
    assert fd.final == ""
    assert fd.error == pd.VALUE_MAP_MISS


# ── validator: prezzo / bettype / modalità ────────────────────────────────────

def test_invalid_price_non_numerico():
    defn = _full_name_rules(
        Price=FieldRule(target="Price", start_after="Quota", required=True))
    diag = pd.diagnose(defn, "Quota 1.60 Stake 1", mode=recognition.NAME_ONLY,
                       provider="TG", value_maps_registry=_BUILTIN)
    fd = _f(diag, "Price")
    assert fd.raw == "1.60 Stake 1"        # estratto fino a fine riga: sporco
    assert fd.error == pd.INVALID_PRICE
    assert diag.placeable is False


def test_invalid_bettype():
    defn = _full_name_rules(
        BetType=FieldRule(target="BetType", fixed_value="BACK", required=True),
        Price=FieldRule(target="Price", start_after="Quota", required=True))
    diag = pd.diagnose(defn, "Quota 1.85", mode=recognition.NAME_ONLY,
                       provider="TG", value_maps_registry=_BUILTIN)
    assert _f(diag, "BetType").error == pd.INVALID_BETTYPE


def test_mode_required_missing_crea_campo_sintetico():
    # NAME_ONLY ma NESSUNA regola MarketType → campo sintetico MODE_REQUIRED_MISSING.
    rules = {
        "Provider": FieldRule(target="Provider", fixed_value="TG"),
        "EventName": FieldRule(target="EventName", fixed_value="Inter v Milan", required=True),
        "SelectionName": FieldRule(target="SelectionName", fixed_value="Pareggio", required=True),
        "BetType": FieldRule(target="BetType", fixed_value="PUNTA", required=True),
        "Price": FieldRule(target="Price", start_after="Quota", required=True),
    }
    diag = pd.diagnose(_defn(*rules.values()), "Quota 1.85",
                       mode=recognition.NAME_ONLY, provider="TG",
                       value_maps_registry=_BUILTIN)
    fd = _f(diag, "MarketType")
    assert fd.error == pd.MODE_REQUIRED_MISSING
    assert fd.required is True
    assert diag.placeable is False


# ── gate di contenuto ─────────────────────────────────────────────────────────

def test_no_content_match_solo_valori_fissi():
    # Tutti i campi fissi: la riga validerebbe, ma non estrae nulla dal messaggio →
    # il runtime la scarterebbe (NO_CONTENT_MATCH), quindi NON è "pronta" (Codex).
    diag = pd.diagnose(_full_name_rules(), "messaggio non pertinente",
                       mode=recognition.NAME_ONLY, provider="TG",
                       value_maps_registry=_BUILTIN)
    assert diag.message_error == pd.NO_CONTENT_MATCH
    assert diag.placeable is False
    assert diag.status == pd.NO_CONTENT_MATCH


def test_minprice_invalido_attribuito_alla_colonna_giusta():
    # Price valido ma MinPrice invalido: l'errore va su MinPrice, non su Price (Codex).
    defn = _full_name_rules(
        Price=FieldRule(target="Price", start_after="Quota", required=True),
        MinPrice=FieldRule(target="MinPrice", start_after="Min", required=False))
    diag = pd.diagnose(defn, "Quota 1.85\nMin 0.5", mode=recognition.NAME_ONLY,
                       provider="TG", value_maps_registry=_BUILTIN)
    assert _f(diag, "MinPrice").error == pd.INVALID_PRICE
    assert _f(diag, "Price").error == pd.OK
    assert diag.placeable is False


def test_points_malformato_attribuito_alla_colonna_points():
    # #17 (Codex P2): un Points valorizzato ma non positivo è attribuito alla colonna Points.
    defn = _full_name_rules(Points=FieldRule(target="Points", start_after="P", required=False))
    diag = pd.diagnose(defn, "P -5", mode=recognition.NAME_ONLY,
                       provider="TG", value_maps_registry=_BUILTIN)
    assert _f(diag, "Points").error == pd.INVALID_POINTS
    assert diag.placeable is False


def test_piu_colonne_invalide_segnalate_tutte():
    # #70 (Codex P2): `validator.validate` si ferma al PRIMO errore (BetType), ma la
    # diagnostica per-colonna deve segnalare TUTTE le colonne invalide, non solo la prima.
    # Fail-first: prima l'overlay marcava solo BetType e lasciava Price a OK.
    defn = _full_name_rules(
        EventName=FieldRule(target="EventName", start_after="🆚", required=True),
        BetType=FieldRule(target="BetType", fixed_value="BACK"),   # non PUNTA/BANCA
        Price=FieldRule(target="Price", fixed_value="abc"))        # non numerico
    diag = pd.diagnose(defn, "🆚Inter v Milan", mode=recognition.NAME_ONLY,
                       provider="TG", value_maps_registry=_BUILTIN)
    assert _f(diag, "BetType").error == pd.INVALID_BETTYPE
    assert _f(diag, "Price").error == pd.INVALID_PRICE      # non più OK
    assert diag.placeable is False


def test_estrazione_fallita_preservata_per_campo_mode_required():
    # #70 (Codex P2): un campo OPZIONALE nella regola ma richiesto dalla MODALITÀ, se
    # l'estrazione fallisce (delimitatore non nel testo), deve mostrare il motivo AZIONABILE
    # (START_NOT_FOUND), non il generico MODE_REQUIRED_MISSING che nasconde la causa.
    # Fail-first: prima l'overlay INVALID_MISSING_FIELDS sovrascriveva START_NOT_FOUND.
    defn = _full_name_rules(
        EventName=FieldRule(target="EventName", start_after="🆚", required=True),
        Price=FieldRule(target="Price", start_after="Quota", required=True),
        MarketType=FieldRule(target="MarketType", start_after="Market:", required=False))
    diag = pd.diagnose(defn, "🆚Inter v Milan\nQuota 1.85", mode=recognition.NAME_ONLY,
                       provider="TG", value_maps_registry=_BUILTIN)
    fd = _f(diag, "MarketType")
    assert fd.error == pd.START_NOT_FOUND       # motivo azionabile preservato
    assert fd.required is True                  # ma marcato come richiesto dalla modalità
    assert diag.placeable is False


def test_bounds_incoerenti_attribuiti_a_min_e_max():
    # #17 (Codex P2): limiti incoerenti (Min > Max) sono segnalati su MinPrice E MaxPrice,
    # non su Price (singolarmente ogni valore è una quota valida).
    defn = _full_name_rules(
        Price=FieldRule(target="Price", start_after="Quota", required=True),
        MinPrice=FieldRule(target="MinPrice", start_after="Min", required=False),
        MaxPrice=FieldRule(target="MaxPrice", start_after="Max", required=False))
    diag = pd.diagnose(defn, "Quota 2.0\nMin 3.0\nMax 1.5", mode=recognition.NAME_ONLY,
                       provider="TG", value_maps_registry=_BUILTIN)
    assert _f(diag, "MinPrice").error == pd.INVALID_PRICE_BOUNDS
    assert _f(diag, "MaxPrice").error == pd.INVALID_PRICE_BOUNDS
    assert _f(diag, "Price").error == pd.OK
    assert diag.placeable is False


def test_bound_singolo_offending_non_segnala_il_limite_assente():
    # #268 (Codex P2): se SOLO un limite contraddice Price (Price=2.0, MinPrice=3.0, nessun
    # MaxPrice), l'errore va segnalato SOLO su MinPrice — non su un MaxPrice opzionale ASSENTE
    # (che manderebbe l'utente a correggere una colonna che non ha nemmeno configurato).
    defn = _full_name_rules(
        Price=FieldRule(target="Price", start_after="Quota", required=True),
        MinPrice=FieldRule(target="MinPrice", start_after="Min", required=False))
    diag = pd.diagnose(defn, "Quota 2.0\nMin 3.0", mode=recognition.NAME_ONLY,
                       provider="TG", value_maps_registry=_BUILTIN)
    assert _f(diag, "MinPrice").error == pd.INVALID_PRICE_BOUNDS
    # nessun errore-bounds su un MaxPrice inesistente (non deve essere creato un campo fantasma)
    assert not any(f.target == "MaxPrice" and f.error == pd.INVALID_PRICE_BOUNDS
                   for f in diag.fields)
    assert diag.placeable is False


# ── report testuale ───────────────────────────────────────────────────────────

def test_format_report_non_pronto():
    defn = _defn(FieldRule(target="EventName", start_after="🆚", required=True))
    report = pd.format_report(pd.diagnose(defn, "no emoji", value_maps_registry=_BUILTIN))
    assert "NON PRONTO" in report
    assert "EventName" in report
    assert pd.START_NOT_FOUND in report


def test_format_report_pronto():
    defn = _full_name_rules(
        EventName=FieldRule(target="EventName", start_after="🆚", required=True),
        Price=FieldRule(target="Price", start_after="Quota", required=True))
    report = pd.format_report(pd.diagnose(
        defn, "🆚Inter v Milan\nQuota 1.85", provider="TG",
        mode=recognition.NAME_ONLY, value_maps_registry=_BUILTIN))
    assert report.startswith("PRONTO")


# ── tabella diagnostica (vista del builder, CP-08b) ──────────────────────────

def _row(rows, target):
    return next(r for r in rows if r.target == target)


def test_diagnostic_table_ok_ed_errore_per_campo():
    # Una riga per colonna: stato/motivo/delimitatori/valore estratto già pronti.
    defn = _defn(
        FieldRule(target="EventName", start_after="🆚", end_before="\n", required=True),
        FieldRule(target="Price", start_after="Quota:", required=True),  # delimitatore assente nel msg
    )
    diag = pd.diagnose(defn, "🆚Inter v Milan\n", mode=recognition.NAME_ONLY,
                       value_maps_registry=_BUILTIN)
    rows = pd.diagnostic_table(diag, defn)
    ev = _row(rows, "EventName")
    assert ev.ok is True and ev.status == "✅ OK"
    assert ev.extracted == "Inter v Milan"
    assert ev.start_after == "🆚" and ev.end_before == "↵"   # newline reso leggibile
    pr = _row(rows, "Price")
    assert pr.ok is False and pr.status == "⛔ ERR"
    assert pr.reason == pd.explain(pd.START_NOT_FOUND)
    assert pr.end_before == "(fine riga)"                    # end_before vuoto = default


def test_diagnostic_table_valore_fisso_e_banner_no_content():
    # Tutti fissi → NO_CONTENT_MATCH: prima riga = banner; i fissi mostrano "(valore fisso)".
    defn = _full_name_rules()
    diag = pd.diagnose(defn, "messaggio non pertinente", provider="TG",
                       mode=recognition.NAME_ONLY, value_maps_registry=_BUILTIN)
    rows = pd.diagnostic_table(diag, defn)
    assert rows[0].banner is True
    assert rows[0].target == pd.NO_CONTENT_MATCH and rows[0].ok is False
    assert _row(rows, "EventName").start_after == "(valore fisso)"
    # mapping mostrato come "grezzo → finale" quando la value-map cambia il valore
    defn2 = _defn(FieldRule(target="SelectionName", start_after="S:", value_map="bettype", required=True))
    diag2 = pd.diagnose(defn2, "S: back", value_maps_registry=_BUILTIN)
    assert _row(pd.diagnostic_table(diag2, defn2), "SelectionName").extracted == "back → PUNTA"
