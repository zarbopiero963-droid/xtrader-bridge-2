"""#285 — «Catalogo XTrader» → «Catalogo Betfair», e la colonna «Betfair / XTrader» → «Betfair».

Richiesta del proprietario, segnata in arancione su due schermate dell'app. Il concetto che
quelle due etichette nominano **è Betfair**: il catalogo mercati/selezioni e il nome canonico
della squadra vengono da lì, non da XTrader. Chiamarli «XTrader» mandava l'utente a cercare in
un posto dove quei dati non stanno.

## Perché questo file esiste, e cosa NON deve fare

Il rischio di questo task non è sbagliare la rinomina: è **rinominare troppo**. Nel codice ci
sono decine di «XTrader» corrette, che parlano davvero del software:

    "✅ Conferme XTrader"                     la chat notifiche di XTrader
    "🔒 CSV bloccato da XTrader"              XTrader tiene il file aperto
    "🔬 Collaudo XTrader — scrive il CSV…"    modalità che riguarda XTrader
    "XTrader Signal Bridge"                   il nome del prodotto

Un `sed` globale su «XTrader» cambierebbe anche il testo di un **gate di sicurezza** (il
dialog COLLAUDO). Quindi qui non si asserisce «XTrader non compare più»: si asserisce che le
**due etichette specifiche** sono cambiate **e che tutto il resto è rimasto** — c'è una
sezione apposta per la seconda metà, ed è quella che rende sicura la prima.

## Le chiavi i18n SONO le stringhe italiane

Cambiare l'etichetta italiana cambia la **chiave** del catalogo. Se EN/ES non seguono, la
traduzione resta orfana e l'utente inglese vede l'italiano. Qui si verifica attraverso l'**API
pubblica** `tr_in()` — cioè come la vede l'utente — invece di ispezionare `_CATALOG`: una
chiave presente nel dizionario ma non raggiungibile dalla `tr_in` sarebbe copertura finta.
"""

import ast
import inspect
import pathlib
import textwrap

import pytest

from xtrader_bridge import i18n, name_mapping_gui

#: Le due etichette, prima e dopo, con la traduzione attesa in ciascuna lingua.
#:
#: Le traduzioni sono ESPLICITE e non «diverse dalla chiave», perché per «Betfair» — un nome
#: proprio — la traduzione inglese *è* «Betfair»: un test scritto come `tradotta != chiave`
#: sarebbe rosso per sempre su una traduzione perfettamente corretta. È il difetto che questo
#: file aveva nella prima stesura, trovato eseguendolo invece che leggendolo.
RINOMINE = (
    ("Catalogo XTrader:", "Catalogo Betfair:",
     {"EN": "Betfair catalog:", "ES": "Catálogo Betfair:"}),
    ("Betfair / XTrader", "Betfair",
     {"EN": "Betfair", "ES": "Betfair"}),
)

#: Gli «XTrader» che devono RESTARE: parlano del software, non di Betfair.
DA_NON_TOCCARE = (
    "Conferme XTrader",
    "CSV bloccato da XTrader",
    "XTrader Signal Bridge",
)


def _etichette_ctklabel(funzione) -> list:
    """Le stringhe passate a `CTkLabel(text=…)`, srotolando `i18n.tr(...)`.

    Legge il sorgente perché le etichette sono costruite dentro `_build_ui`, che richiede una
    root Tk viva: in un test unitario headless non è istanziabile.
    """
    albero = ast.parse(textwrap.dedent(inspect.getsource(funzione)))
    fuori = []
    for n in ast.walk(albero):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
            continue
        if n.func.attr != "CTkLabel":
            continue
        for kw in n.keywords:
            if kw.arg != "text":
                continue
            v = kw.value
            if (isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute)
                    and v.func.attr == "tr" and v.args):
                v = v.args[0]
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                fuori.append(v.value)
    return fuori


# ── ① l'etichetta del catalogo nel pannello Parser ────────────────────────────────────

def test_l_etichetta_del_catalogo_dice_betfair():
    """FAIL-FIRST: diceva «Catalogo XTrader:», mandando l'utente a cercare i mercati dentro
    XTrader — mentre il catalogo da cui quei valori vengono è quello di Betfair."""
    from xtrader_bridge import custom_parser_gui

    etichette = _etichette_ctklabel(custom_parser_gui.CustomParserPanel._build_ui)

    assert "Catalogo Betfair:" in etichette, etichette
    assert "Catalogo XTrader:" not in etichette, "l'etichetta vecchia è rimasta"


# ── ② l'intestazione di colonna nella tabella nomi ────────────────────────────────────

def test_l_intestazione_di_colonna_dice_solo_betfair():
    """FAIL-FIRST: diceva «Betfair / XTrader». Si legge da `_HEADER_COLUMNS`, che il modulo
    dichiara fonte unica per `_build_ui` e per i test — quindi la verifica è sul DATO reale
    dell'header, non su una grep del sorgente."""
    intestazioni = [nome for nome, _larghezza in name_mapping_gui._HEADER_COLUMNS]

    assert "Betfair" in intestazioni, intestazioni
    assert "Betfair / XTrader" not in intestazioni, "l'intestazione vecchia è rimasta"


def test_l_intestazione_resta_distinguibile_da_quella_accanto():
    """Perché «Betfair» da solo non è ambiguo, che è la domanda che l'issue lasciava aperta:
    la colonna accanto dice esplicitamente che quello è il nome scritto dal canale, quindi le
    due restano distinte anche senza il suffisso.

    Il test lo pretende invece di darlo per buono: se un domani la colonna accanto venisse
    rinominata in qualcosa di generico, «Betfair» da solo tornerebbe ambiguo e questo lo dice.
    """
    intestazioni = [nome for nome, _ in name_mapping_gui._HEADER_COLUMNS]
    i = intestazioni.index("Betfair")

    assert i + 1 < len(intestazioni), "«Betfair» è l'ultima colonna: non c'è più il contrasto"
    assert "canale" in intestazioni[i + 1].lower(), intestazioni


# ── ③ le tre lingue: nessuna traduzione orfana ────────────────────────────────────────

@pytest.mark.parametrize("lingua", ["EN", "ES"])
@pytest.mark.parametrize("_vecchia, nuova, attese", RINOMINE)
def test_le_nuove_etichette_sono_tradotte(lingua, _vecchia, nuova, attese):
    """Le chiavi del catalogo SONO le stringhe italiane: cambiare l'etichetta cambia la
    chiave, e se EN/ES non seguono l'utente inglese vede l'italiano.

    Verificato via `tr_in()`, l'API pubblica — cioè come lo vede l'utente — invece di
    ispezionare `_CATALOG`: una entry presente nel dizionario ma non raggiungibile dalla
    traduzione sarebbe copertura finta.
    """
    assert i18n.tr_in(lingua, nuova) == attese[lingua]


@pytest.mark.parametrize("vecchia, _nuova, _attese", RINOMINE)
def test_le_vecchie_chiavi_non_sono_rimaste_nel_catalogo(vecchia, _nuova, _attese):
    """La metà che impedisce di aggiungere la nuova e dimenticare la vecchia: due chiavi per
    lo stesso concetto è il modo in cui una traduzione orfana sopravvive senza farsi vedere —
    non rompe nulla, semplicemente non viene più usata da nessuno."""
    sorgente = pathlib.Path(i18n.__file__).read_text(encoding="utf-8")
    assert vecchia not in sorgente, (
        f"«{vecchia}» è ancora in i18n.py: chiave vecchia rimasta accanto alla nuova"
    )


@pytest.mark.parametrize("lingua", ["EN", "ES"])
def test_il_tooltip_lungo_non_nomina_piu_xtrader(lingua):
    """Il terzo testo visibile, che l'issue elencava fra le voci di catalogo: la riga di aiuto
    sotto il titolo della tabella nomi. Nomina lo stesso concetto delle due etichette, quindi
    rinominare quelle e lasciare lui vorrebbe dire mostrare due nomi per la stessa cosa nella
    stessa schermata."""
    chiave = ("Traduce i nomi squadra così come li scrive il canale nel nome atteso da "
              "Betfair. Seleziona i profili nel Parser Personalizzato.")
    tradotta = i18n.tr_in(lingua, chiave)

    assert tradotta != chiave, f"tooltip non tradotto in {lingua}"
    assert "XTrader" not in tradotta, tradotta


# ── ④ la metà che rende sicura la rinomina: ciò che NON va toccato ────────────────────

@pytest.mark.parametrize("resta", DA_NON_TOCCARE)
def test_gli_xtrader_veri_non_sono_stati_rinominati(resta):
    """**Il test più importante di questo file.**

    Il rischio di #285 non è sbagliare la rinomina, è rinominare troppo: «Conferme XTrader»,
    «CSV bloccato da XTrader» e il nome del prodotto parlano davvero del software, e uno di
    quei testi sta in un **gate di sicurezza**. Se un domani qualcuno passasse un `sed`
    globale su «XTrader» — la scorciatoia ovvia per un task che si chiama «rinomina» — questo
    test lo ferma prima della CI.
    """
    pacchetto = pathlib.Path(i18n.__file__).parent
    trovato = any(
        resta in p.read_text(encoding="utf-8", errors="ignore")
        for p in pacchetto.glob("*.py")
    )
    assert trovato, f"«{resta}» è sparito: parla del software XTrader e NON va rinominato"


def test_l_invariante_di_sicurezza_del_handoff_nomina_ancora_entrambi_i_sistemi():
    """La stessa trappola, ma nelle DOCS — e non è teorica: **è successa in questa PR**.

    `design_handoff.md` elenca fra le invarianti di sicurezza «Nessuna automazione di puntata
    diretta verso Betfair/XTrader dalla UI». Lì «Betfair/XTrader» **non** è la colonna
    rinominata: significa «verso Betfair *o* XTrader», cioè i due sistemi esterni. Una
    sostituzione generica su «Betfair/XTrader» l'ha mutilata in «verso Betfair», togliendo
    XTrader dall'elenco di ciò verso cui la UI non automatizza nulla — un'invariante di
    sicurezza indebolita da una rinomina cosmetica.

    Le guardie sopra coprivano il codice; questa copre il handoff, che è il documento
    consegnato a chi fa il design e quindi il posto dove un'invariante persa fa più danno.
    """
    handoff = (pathlib.Path(i18n.__file__).parent.parent
               / "docs" / "design" / "design_handoff.md")
    if not handoff.exists():                      # docs non incluse in un packaging ridotto
        pytest.skip("design_handoff.md non presente in questo albero")

    testo = handoff.read_text(encoding="utf-8")
    riga = [r for r in testo.splitlines() if 'di puntata diretta' in r]
    assert riga, "l'invariante «nessuna automazione di puntata diretta» è sparita dal handoff"
    assert "Betfair/XTrader" in riga[0], (
        f"l'invariante nomina un solo sistema: {riga[0].strip()!r} — deve restare "
        f"«verso Betfair/XTrader», perché parla dei due sistemi esterni, non della colonna"
    )
