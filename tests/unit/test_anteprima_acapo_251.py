"""#251 — l'anteprima mostrava la cella NON sanificata, quindi diversa dal file scritto.

Il write-path è `_sanitize_row(_localize_row(riga))`: la sanificazione viene **dopo** la
localizzazione. L'anteprima usa `csv_writer.localize_row`, che è il wrapper pubblico di
`_localize_row` e la sanificazione non la applicava affatto:

    valore estratto      anteprima mostrava      file conteneva
    "Inter\\r\\nMilan"       "Inter\\r\\nMilan"          "Inter Milan"
    "=1+1"               "=1+1"                  "'=1+1"

**Decisione del proprietario: opzione C.** L'anteprima neutralizza gli **a-capo** come il
file, ma **non** aggiunge l'apostrofo anti-formula.

Il perché delle due metà è diverso, e per questo la scelta non è «sanificare tutto»:

- **gli a-capo vanno mostrati neutralizzati** perché `"Inter\\r\\nMilan"` e `"Inter Milan"`
  sono due nomi squadra diversi, e quello che verrà davvero cercato su Betfair è il secondo.
  Mostrare il primo manda l'operatore a cercare un problema dove non c'è;
- **l'apostrofo NON va mostrato** perché è una mitigazione anti-injection, non un dato: è un
  carattere che l'utente non ha scritto e che non descrive né il messaggio né la scommessa.
  Vederlo nell'anteprima confonde su ciò che il parser ha estratto.

La parità resta quindi **parziale e dichiarata**, non promessa: è esattamente il difetto che
il docstring di `localize_row` aveva già una volta (prometteva una parità totale che il codice
non ha mai dato) e che la #250 aveva ristretto al vero. Qui la promessa si allarga di un passo,
e resta vera.

**La cosa che conta di più è che non torni a divergere.** Se l'anteprima *rifacesse* la
neutralizzazione con una sua regex, la prossima modifica al write-path le separerebbe di nuovo
— è la classe di difetto corretta quattro volte sulla #253 e due sulla #255. Perciò la
neutralizzazione è **una funzione sola** (`neutralize_linebreaks`), condivisa da
`_sanitize_cell` e dall'anteprima, e qui sotto c'è un test che lo pretende su input generati.
"""

import pytest

from xtrader_bridge import csv_writer


# ── Il difetto della issue ──────────────────────────────────────────────────

@pytest.mark.parametrize("grezzo,atteso", [
    ("Inter\r\nMilan", "Inter Milan"),      # interno: UN solo spazio, non due
    ("Inter\nMilan", "Inter Milan"),
    ("Inter\rMilan", "Inter Milan"),
    ("1.85\r\n", "1.85"),                   # coda: RIMOSSO, niente spazio residuo
    ("\r\nInter", "Inter"),                 # testa: rimosso
    ("\r\n", ""),                           # solo a-capo: cella vuota
    ("Inter\r\n\r\nMilan", "Inter Milan"),  # a-capo multipli: sempre uno spazio solo
])
def test_251_anteprima_neutralizza_gli_acapo_come_il_file(grezzo, atteso):
    """Il cuore della issue. Misurato prima della correzione, l'anteprima restituiva il
    valore grezzo con l'a-capo dentro, mentre il file conteneva già la forma neutralizzata."""
    assert csv_writer.localize_row({"EventName": grezzo})["EventName"] == atteso


def test_251_ma_NON_aggiunge_l_apostrofo_anti_formula():
    """L'altra metà dell'opzione C, ed è la parte che si perde per prima se qualcuno «completa»
    la parità in futuro credendo di migliorarla.

    L'apostrofo è una mitigazione, non un dato: nell'anteprima direbbe all'operatore che il
    parser ha estratto un carattere che non c'era nel messaggio."""
    for formula in ("=1+1", "+1", "-cmd", "@SUM(A1)", " =1+1"):
        mostrato = csv_writer.localize_row({"EventName": formula})["EventName"]
        assert mostrato == formula, f"{formula!r} -> {mostrato!r}: apostrofo comparso"
        assert not mostrato.startswith("'"), mostrato
    # ...ma nel FILE l'apostrofo c'è eccome: le due viste sono diverse di proposito
    assert csv_writer._sanitize_cell("=1+1") == "'=1+1"


def test_251_il_file_NON_cambia():
    """Guardia sul rischio vero: questa modifica tocca solo ciò che la GUI mostra. Se avesse
    cambiato anche una cella del write-path, sarebbe un difetto del CSV — cioè la cosa che la
    issue dichiarava esplicitamente di NON voler toccare."""
    campioni = ["Inter\r\nMilan", "1.85\r\n", "=1+1", "\r\n=1+1", "1,85", "Inter", "", "0.5"]
    for v in campioni:
        # `_sanitize_cell` è il write-path: il suo comportamento è quello di prima
        prodotto = csv_writer._sanitize_cell(v)
        assert "\r" not in prodotto and "\n" not in prodotto, (v, prodotto)
    assert csv_writer._sanitize_cell("Inter\r\nMilan") == "Inter Milan"
    assert csv_writer._sanitize_cell("1.85\r\n") == "1.85"
    assert csv_writer._sanitize_cell("\r\n=1+1") == "'=1+1"


# ── L'invariante che impedisce di divergere di nuovo ────────────────────────

@pytest.mark.parametrize("valore", [
    "Inter\r\nMilan", "a\nb", "a\rb", "\r\n", "x\r\n\r\ny", "1.85\r\n", "\r\n1.85",
    "  spazi  ", "=1+1", "\r\n=1+1", "Inter", "", "1,85", "0.5", "-0.5",
    "a\n\n\nb", "\n\na\n\n", "Real Madrid", "Über\r\nWien",
])
def test_251_anteprima_e_file_trattano_gli_ACAPO_allo_STESSO_modo(valore):
    """La garanzia strutturale: sugli a-capo le due viste non possono divergere.

    Non si confrontano le celle intere — sarebbero diverse di proposito, per via
    dell'apostrofo — ma il **risultato della sola neutralizzazione a-capo**, che deve essere
    identico perché entrambe chiamano la stessa funzione. Se qualcuno in futuro riscrivesse la
    logica in uno dei due posti, questo test lo prende.
    """
    anteprima = csv_writer.localize_row({"EventName": valore})["EventName"]
    scritto = csv_writer._sanitize_cell(valore)
    # 1. nessuna delle due viste lascia sopravvivere un a-capo
    for vista, nome in ((anteprima, "anteprima"), (scritto, "file")):
        assert "\r" not in vista and "\n" not in vista, f"{nome}: a-capo sopravvissuto in {vista!r}"
    # 2. e a meno dell'apostrofo (che è deliberato) le due viste coincidono
    assert scritto == anteprima or scritto == "'" + anteprima, (
        f"anteprima {anteprima!r} e file {scritto!r} divergono per qualcosa che NON è "
        f"l'apostrofo: le due neutralizzazioni si sono separate")


def test_251_la_neutralizzazione_e_UNA_SOLA_funzione():
    """Fonte unica (Regola 3), verificata chiamandola: se domani qualcuno la duplicasse, la
    duplicazione non farebbe fallire nulla — ma il test sopra sì, appena le due copie
    divergessero. Questo qui ancora l'esistenza del punto unico."""
    assert hasattr(csv_writer, "neutralize_linebreaks")
    assert csv_writer.neutralize_linebreaks("Inter\r\nMilan") == "Inter Milan"
    assert csv_writer.neutralize_linebreaks("1.85\r\n") == "1.85"
    assert csv_writer.neutralize_linebreaks("") == ""
    assert csv_writer.neutralize_linebreaks("Inter") == "Inter"


# ── Ciò per cui il wrapper è nato non deve rompersi ─────────────────────────

def test_251_i_decimali_restano_localizzati():
    """`localize_row` esiste dalla #342 per mostrare i decimali come usciranno nel file. La
    #251 aggiunge la neutralizzazione a-capo: non deve togliere ciò che c'era."""
    riga = {"Price": "1.85", "Handicap": "-0.5"}
    assert csv_writer.localize_row(riga, "IT")["Price"] == "1,85"
    assert csv_writer.localize_row(riga, "ES")["Handicap"] == "-0,5"
    assert csv_writer.localize_row(riga, "EN")["Price"] == "1.85"


def test_251_localizzazione_e_acapo_insieme():
    """I due trattamenti si compongono nell'ordine giusto (prima localizza, poi neutralizza —
    lo stesso ordine del write-path `_sanitize_row(_localize_row(...))`)."""
    riga = {"Price": "1.85\r\n", "EventName": "Inter\r\nMilan"}
    fuori = csv_writer.localize_row(riga, "IT")
    assert fuori["Price"] == "1,85", fuori          # localizzato E ripulito
    assert fuori["EventName"] == "Inter Milan"


def test_251_non_stringhe_e_None_non_esplodono():
    """Fail-safe: nell'anteprima arrivano righe costruite dal parser, che su input ostile può
    produrre valori non-stringa. Un'anteprima non deve mai sollevare."""
    fuori = csv_writer.localize_row({"A": None, "B": 42, "C": 1.85, "D": ""})
    assert fuori["A"] in ("", None)
    assert "\r" not in str(fuori["B"]) and "\n" not in str(fuori["B"])


# ── End-to-end: i TRE consumatori, non i due della issue ────────────────────

def test_251_end_to_end_anteprima_del_parser():
    """Il percorso reale della GUI «Prova messaggio»: `preview_rows` compone il `summary` con
    `localize_row`. Un a-capo lì dentro spezzerebbe anche visivamente la riga di riepilogo."""
    from xtrader_bridge import custom_parser as cp
    from xtrader_bridge.parser_builder import ParserBuilder

    defn = cp.CustomParserDef(
        name="T", mode="ID_ONLY", team_separator="v",
        rules=[
            cp.FieldRule(target="Provider", fixed_value="TG"),
            cp.FieldRule(target="EventName", start_after="Match:", end_before="|", required=True),
            cp.FieldRule(target="MarketId", fixed_value="1.23", required=True),
            cp.FieldRule(target="SelectionId", fixed_value="99", required=True),
            cp.FieldRule(target="Price", fixed_value="1.85", required=True),
            cp.FieldRule(target="BetType", fixed_value="BACK", required=True),
        ])
    # il messaggio contiene un a-capo DENTRO il campo delimitato
    righe = ParserBuilder(defn).preview_rows("Match: Inter\nMilan| fine\n", provider="TG")
    assert righe, "nessuna riga di anteprima"
    assert "\n" not in righe[0].summary and "\r" not in righe[0].summary, righe[0].summary
    assert "Inter Milan" in righe[0].summary, righe[0].summary


def test_251_la_riga_di_LOG_del_segnale_non_mostra_un_acapo_grezzo():
    """Sibling trovato cercando la CLASSE invece del sito (Regola 2), non citato nella issue.

    `signal_outcome.describe_write` compone la riga di log e l'etichetta «ULTIMO SEGNALE»
    della GUI dai valori **grezzi** della riga. Misurato prima della correzione, con un
    a-capo dentro `EventName`:

        log      : '📱 Segnale (custom): Inter\\r\\nMilan  |  Over 2,5 goal  q.1.85'
        etichetta: '🏆 Inter\\r\\nMilan  |  Over 2,5 goal  |  q.1.85'
        CSV       : 'Inter Milan'

    È la stessa divergenza della #251 su due superfici in più — e qui è **peggio** che
    nell'anteprima: un `\\r\\n` dentro un'etichetta Tk non si limita a mentire, **spezza il
    layout** del pannello Log, che è una riga per evento.

    Non è un rischio di scommessa: il CSV era già corretto (B11, #250). È il record che
    l'operatore legge quando indaga a non dire il vero.
    """
    from xtrader_bridge import signal_outcome

    riga = {"EventName": "Inter\r\nMilan", "SelectionName": "Over 2,5 goal", "Price": "1.85"}
    out = signal_outcome.describe_write(riga, "custom", 1)
    for vista, nome in ((out.signal_log, "signal_log"), (out.last_signal, "last_signal")):
        assert "\r" not in vista and "\n" not in vista, f"{nome}: a-capo grezzo in {vista!r}"
        assert "Inter Milan" in vista, f"{nome}: {vista!r}"
    # e il resto della riga non è stato toccato
    assert "Over 2,5 goal" in out.signal_log and "q.1.85" in out.signal_log, out.signal_log


def test_251_il_log_del_segnale_non_altera_i_valori_normali():
    """Contro-guardia del test sopra: la neutralizzazione non deve cambiare nulla su una riga
    normale — altrimenti si «corregge» un log che funzionava."""
    from xtrader_bridge import signal_outcome

    riga = {"EventName": "Inter - Milan", "SelectionName": "Over 2,5 goal", "Price": "1,85"}
    out = signal_outcome.describe_write(riga, "custom", 2)
    assert out.signal_log == "📱 Segnale (custom): Inter - Milan  |  Over 2,5 goal  q.1,85"
    assert out.last_signal == "🏆 Inter - Milan  |  Over 2,5 goal  |  q.1,85"


def test_251_end_to_end_tool_test_message_dell_assistente():
    """Il TERZO consumatore, che la issue non citava: `config_agent.test_message` compone le
    sue `columns` con lo stesso `localize_row` e il suo commento dichiara «riga COME uscirebbe
    nel file».

    Se l'anteprima della GUI e quella dell'assistente divergessero, sarebbe una nuova istanza
    della stessa classe di difetto — due viste della stessa cosa che dicono cose diverse.
    Nessun file dell'assistente è stato modificato: si allinea perché la funzione condivisa è
    una sola (area dichiarata sana dall'audit, regola 5).
    """
    riga = csv_writer.localize_row({"EventName": "Inter\r\nMilan", "Price": "1.85"}, "IT")
    assert riga["EventName"] == "Inter Milan"
    assert riga["Price"] == "1,85"
