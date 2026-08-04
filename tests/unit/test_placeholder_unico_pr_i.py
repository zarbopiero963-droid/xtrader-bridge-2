"""PR-I (#194) — un placeholder non risolto non deve mai passare per un valore reale.

Quattro difetti, **una sola causa**: il repository aveva quattro predicati diversi per la
stessa domanda, e tre erano più permissivi del quarto.

| sito | predicato prima | difetto |
|---|---|---|
| `value_maps._is_placeholder` | `"{" in v or "}" in v` | nessuno — indurito dalla #16 L2-2 |
| `dizionario.has_placeholder` | `re \\{[A-Z_]+\\}` | **B10**: cieco su `{HOME_TEAM`, `HOME_TEAM}`, `{home_team}` |
| `mapping.resolve_selection` | `"{" in nome` | **B18**: vede `{`, mai `}` |
| `custom_parser_engine.matches_message` | *nessuno* | **B16**: il placeholder conta come contenuto |

Più **B19**: `mapping._subst` faceva due `str.replace` in sequenza, quindi un nome squadra
preso verbatim dal messaggio poteva iniettare *l'altro* placeholder e far uscire la squadra
avversaria — il lato della scommessa invertito.

È la lezione della #192 scritta in un test: «tre correzioni della #16 su sei avevano lasciato
siblings non allineati». Qui il predicato è **uno solo** (`validators.has_unresolved_placeholder`)
e i quattro siti vi delegano, così la prossima correzione si scrive in un posto solo.
"""

import pytest

from xtrader_bridge import custom_parser_engine as engine
from xtrader_bridge import dizionario, mapping, validators, value_maps
from xtrader_bridge.custom_parser import CustomParserDef, FieldRule

# Le forme che l'audit #192 (M6) elenca come non riconosciute dal predicato stretto.
FORME_ROTTE = ["{HOME_TEAM", "HOME_TEAM}", "{home_team}", "{Home_Team}", "{TEAM_1}", "}{"]
FORME_SANE = ["Inter", "Inter - Milan", "Over 2.5", "1.85", "", "Nome (con parentesi)"]


# ── la fonte unica ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("rotto", ["{HOME_TEAM}"] + FORME_ROTTE)
def test_la_fonte_unica_riconosce_ogni_forma_rotta(rotto):
    """Una graffa sola basta: i valori betting reali non ne contengono mai."""
    assert validators.has_unresolved_placeholder(rotto) is True, rotto


@pytest.mark.parametrize("sano", FORME_SANE)
def test_la_fonte_unica_non_ha_falsi_positivi(sano):
    assert validators.has_unresolved_placeholder(sano) is False, sano


def test_la_fonte_unica_regge_i_non_stringa():
    """Arriva da JSON e da CSV editabili a mano: `None`, numeri e liste non devono far
    esplodere un predicato usato per decidere se scartare una selezione."""
    for valore in (None, 0, 1.85, [], True, [1, 2]):
        assert validators.has_unresolved_placeholder(valore) is False, repr(valore)


def test_la_fonte_unica_e_coerente_sui_dict():
    """Rilievo GPT-5.5 sulla #252: la risposta non deve dipendere dal *contenuto* del tipo.

    Con `str(value or "")` un `dict` dava due risposte diverse — `{}` → `False` (falsy, quindi
    collassato a stringa vuota) e `{"a": 1}` → `True` (`str` lo scrive con le graffe) — e la
    risposta permissiva capitava proprio sul caso vuoto. Ora entrambi sono `True`: se una
    struttura arriva a un predicato sui placeholder è un errore di programmazione, e scartare
    il valore è la direzione sicura."""
    assert validators.has_unresolved_placeholder({}) is True
    assert validators.has_unresolved_placeholder({"a": 1}) is True


def test_la_fonte_unica_e_fail_closed_sui_contenitori_con_placeholder():
    """Casi chiesti da CodeRabbit sulla #252 — e la scelta è *deliberatamente* l'opposto
    della sua proposta, con la ragione scritta.

    CodeRabbit proponeva `if not isinstance(value, str): return False`, per allineare il
    codice al docstring che prometteva «non-stringa → False». Il rilievo era giusto — codice
    e docstring divergevano — ma la direzione no: con quella scelta un contenitore che
    *contiene* un placeholder verrebbe giudicato «nessun placeholder», quindi usato come
    valore reale, e finirebbe nel CSV stringificato con le graffe dentro. Fail-OPEN, che è
    esattamente la classe di difetto che questa PR chiude.

    Allineato quindi il **docstring** al codice invece del contrario: qualunque valore che si
    *scrive* con una graffa è trattato come placeholder e scartato. Un contenitore che arriva
    fin qui è comunque un errore di programmazione — tutti i chiamanti reali passano stringhe
    (CSV `DictReader`, valori estratti dal parser, `_subst`) — e su un errore di
    programmazione la direzione sicura è scartare."""
    assert validators.has_unresolved_placeholder(["{HOME_TEAM}"]) is True
    assert validators.has_unresolved_placeholder({"nome": "{HOME_TEAM}"}) is True
    # Un contenitore SENZA graffe resta un non-placeholder: la regola guarda il testo, non il tipo.
    assert validators.has_unresolved_placeholder(["Inter", "Milan"]) is False


# ── B10 · dizionario.has_placeholder era fail-OPEN ───────────────────────────

@pytest.mark.parametrize("rotto", FORME_ROTTE)
def test_b10_il_dizionario_riconosce_le_forme_rotte(rotto):
    """`has_placeholder` calcola il flag `dynamic`, cioè «è sicuro persistere questo come
    valore FISSO?». Con la regex stretta `\\{[A-Z_]+\\}` la risposta era «sì» per ogni forma
    rotta o minuscola — e `fill_placeholders` non le sostituisce, quindi sarebbero finite
    **verbatim** come nome mercato o selezione."""
    assert dizionario.has_placeholder(rotto) is True, rotto


def test_b10_il_dizionario_non_perde_la_forma_stretta():
    assert dizionario.has_placeholder("{HOME_TEAM}") is True
    assert dizionario.has_placeholder("Inter - Milan") is False


def test_b10_i_tre_predicati_ora_concordano():
    """La guardia anti-drift vera: nessun disallineamento fra i siti.

    È il difetto che la #192 ha trovato tre volte di fila («siblings non allineati»), quindi
    non basta correggere: serve un test che fallisca se un domani divergono di nuovo."""
    for valore in ["{HOME_TEAM}"] + FORME_ROTTE + FORME_SANE:
        atteso = validators.has_unresolved_placeholder(valore)
        assert dizionario.has_placeholder(valore) is atteso, valore
        assert value_maps._is_placeholder(valore) is atteso, valore


# ── B18 · resolve_selection guardava solo `{` ────────────────────────────────

def test_b18_una_graffa_chiusa_orfana_non_deve_passare(monkeypatch):
    """`HOME_TEAM}` sopravviveva come nome di selezione reale.

    Si inietta una riga di dizionario con la forma rotta: il dizionario **spedito** è pulito,
    quindi il difetto vive solo su un dizionario editato — ma la funzione deve essere
    fail-closed comunque, che è ciò che il suo docstring promette già oggi
    («oppure None se rimane un placeholder non sostituito»)."""
    riga = {
        "MarketType_XTrader": "MATCH_ODDS",
        "MarketName_XTrader": "Vincente",
        "SelectionName_XTrader": "HOME_TEAM}",   # graffa CHIUSA orfana
        "Handicap": "0",
        "BetType_XTrader": "PUNTA",
    }
    monkeypatch.setattr(mapping, "_index", lambda: {mapping.alias_key("m", "s"): riga})
    assert mapping.resolve_selection("m", "s", home="Inter", away="Milan") is None


def test_b18_la_forma_normale_continua_a_risolvere(monkeypatch):
    """Controllo positivo: chiudere il buco non deve rendere irrisolvibile il caso buono."""
    riga = {
        "MarketType_XTrader": "MATCH_ODDS",
        "MarketName_XTrader": "Vincente",
        "SelectionName_XTrader": "{HOME_TEAM}",
        "Handicap": "0",
        "BetType_XTrader": "PUNTA",
    }
    monkeypatch.setattr(mapping, "_index", lambda: {mapping.alias_key("m", "s"): riga})
    esito = mapping.resolve_selection("m", "s", home="Inter", away="Milan")
    assert esito is not None and esito["SelectionName"] == "Inter"


# ── B19 · _subst invertiva il lato ───────────────────────────────────────────

def test_b19_un_nome_squadra_ostile_non_puo_invertire_il_lato():
    """Il difetto peggiore dei quattro, anche se oggi su codice morto.

    I nomi squadra arrivano **verbatim dal messaggio**. Con due `replace` in sequenza, un
    `home` che *contiene* `{AWAY_TEAM}` veniva prima inserito al posto di `{HOME_TEAM}`, e poi
    il secondo `replace` lo trasformava nella squadra **avversaria**: la selezione «vittoria
    casa» diventava «vittoria trasferta». Il lato invertito è l'invariante che `CLAUDE.md`
    protegge per prima.

    Con la sostituzione a passata singola il testo inserito non viene più riesaminato."""
    risultato = mapping._subst("{HOME_TEAM}", home="{AWAY_TEAM}", away="Milan")
    assert risultato != "Milan", "lato invertito: la casa è diventata la trasferta"
    assert risultato == "{AWAY_TEAM}"


def test_b19_la_sostituzione_normale_resta_identica():
    assert mapping._subst("{HOME_TEAM} - {AWAY_TEAM}", "Inter", "Milan") == "Inter - Milan"
    assert mapping._subst("{HOME_TEAM}", "Inter", "") == "Inter"
    assert mapping._subst("{AWAY_TEAM}", "", "Milan") == "Milan"


def test_b19_bis_fill_placeholders_aveva_lo_STESSO_difetto():
    """Il sibling che il piano non citava, trovato col grep di Regola 2.

    `dizionario.fill_placeholders` faceva **tre** `replace` in sequenza — `{HOME_TEAM}`,
    `{AWAY_TEAM}`, `{EVENT_NAME}` — quindi soffriva della identica inversione di lato di
    `mapping._subst`, misurata: `fill_placeholders("{HOME_TEAM}", "{AWAY_TEAM}", "Milan")`
    restituiva **`"Milan"`**.

    È esattamente il difetto che la #192 ha trovato tre volte («siblings non allineati»):
    correggere il sito citato e lasciare il gemello. Ora entrambi delegano alla stessa
    `validators.substitute_placeholders`, quindi non possono più divergere."""
    assert dizionario.fill_placeholders("{HOME_TEAM}", "{AWAY_TEAM}", "Milan") == "{AWAY_TEAM}"


def test_b19_bis_fill_placeholders_resta_corretto_sui_casi_normali():
    assert dizionario.fill_placeholders("{HOME_TEAM} - {AWAY_TEAM}", "Inter", "Milan") == "Inter - Milan"
    assert dizionario.fill_placeholders("{EVENT_NAME}", "Inter", "Milan") == "Inter - Milan"
    assert dizionario.fill_placeholders("{HOME_TEAM} +1", "Inter", "Milan") == "Inter +1"


def test_b19_bis_event_name_solo_con_entrambe_le_squadre():
    """Contratto invariato: `{EVENT_NAME}` si compone solo se si conoscono entrambe le
    squadre, altrimenti resta un placeholder che il chiamante rileva e scarta."""
    assert dizionario.fill_placeholders("{EVENT_NAME}", "Inter", "") == "{EVENT_NAME}"
    assert dizionario.fill_placeholders("{EVENT_NAME}", "", "Milan") == "{EVENT_NAME}"


def test_b19_una_squadra_mancante_lascia_il_placeholder():
    """Contratto invariato: senza la squadra il placeholder resta, così il chiamante lo
    rileva e scarta la selezione invece di scrivere un nome vuoto."""
    assert mapping._subst("{HOME_TEAM}", "", "Milan") == "{HOME_TEAM}"


# ── B16 · un placeholder estratto contava come contenuto reale ───────────────

def _parser_con_id_fissi():
    """Il parser pericoloso della #192 L17: ID di riconoscimento FISSI più un'estrazione.

    Con gli ID fissi la riga è piazzabile per QUALSIASI messaggio; l'unica cosa che impedisce
    la scommessa spuria è il gate di contenuto. Se un placeholder conta come contenuto, il
    gate si apre su un messaggio che non porta alcun dato reale."""
    return CustomParserDef(
        name="conIdFissi",
        rules=[
            FieldRule(target="MarketId", fixed_value="1"),
            FieldRule(target="SelectionId", fixed_value="7"),
            FieldRule(target="EventName", start_after="Match:", required=True),
        ],
    )


def test_b16_un_placeholder_estratto_non_e_contenuto_reale():
    """Il messaggio del bot col template ROTTO non deve far scattare il parser.

    `"Match: {HOME_TEAM} v {AWAY_TEAM}"` è ciò che un bot pubblica quando il suo template non
    è stato riempito. Il valore estratto è non vuoto, quindi contava come contenuto — e con
    gli ID fissi la scommessa partiva su un messaggio privo dei dati veri."""
    defn = _parser_con_id_fissi()
    assert engine.matches_message(defn, "Match: {HOME_TEAM} v {AWAY_TEAM}") is False


def test_b16_un_messaggio_vero_continua_a_scattare():
    """Controllo positivo, indispensabile: il gate non deve chiudersi sul caso buono."""
    defn = _parser_con_id_fissi()
    assert engine.matches_message(defn, "Match: Inter v Milan") is True


@pytest.mark.parametrize("rotto", ["{HOME_TEAM", "HOME_TEAM}", "{home_team}"])
def test_b16_vale_anche_per_le_forme_rotte(rotto):
    """Non solo il placeholder canonico: anche un template troncato a metà."""
    defn = _parser_con_id_fissi()
    assert engine.matches_message(defn, f"Match: {rotto}") is False


@pytest.mark.parametrize("modo", ["NAME_ONLY", "ID_ONLY", "BOTH"])
def test_b16_vale_in_tutte_le_modalita_di_riconoscimento(modo):
    """Copertura per modalità (richiesta GPT-5.5 sulla #252).

    Il gate di contenuto si comporta diversamente per modalità — quali campi contano come
    «di riconoscimento» cambia fra `NAME_ONLY`, `ID_ONLY` e `BOTH` — quindi una correzione
    verificata su una sola modalità non dice nulla sulle altre. Qui la regola è
    **obbligatoria**, che è il ramo che ritorna `True` per primo in tutte e tre: se il
    placeholder non fosse filtrato, il gate si aprirebbe in ognuna."""
    defn = CustomParserDef(
        name="perModo",
        mode=modo,
        rules=[
            FieldRule(target="MarketId", fixed_value="1"),
            FieldRule(target="SelectionId", fixed_value="7"),
            FieldRule(target="EventName", start_after="Match:", required=True),
        ],
    )
    assert engine.matches_message(defn, "Match: {HOME_TEAM} v {AWAY_TEAM}") is False
    assert engine.matches_message(defn, "Match: Inter v Milan") is True, (
        f"controllo positivo fallito in {modo}: il gate si è chiuso sul messaggio buono"
    )


def test_b16_un_placeholder_parziale_dentro_un_valore_vero_blocca():
    """Fail-closed sul caso ambiguo: se una parte del valore è ancora un placeholder, il
    valore NON è un dato reale — meglio non scattare che scommettere su un nome a metà."""
    defn = _parser_con_id_fissi()
    assert engine.matches_message(defn, "Match: Inter v {AWAY_TEAM}") is False
