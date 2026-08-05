"""#233 — il default di `RouteResult.source` nominava un parser RIMOSSO.

`source: str = HARDCODED` puntava al parser automatico P.Bet, disattivato dal live in CP-09b e
**cancellato dal repository** nella #76 P3-15 (`xtrader_bridge/parser.py`, ~390 righe). Il modulo
non è più nemmeno importabile — `tests/unit/test_pbet_removed_76.py` lo verifica.

`source` non resta interno: esce sul **log dell'operatore** (`signal_outcome.describe_write`) e
sul **diario eventi** (`app.py`, quattro `_journal`). Sono i due record su cui si fa diagnosi a
posteriori, quindi un valore falso lì non è un dettaglio estetico: è il registro forense del
bridge che attribuisce una scrittura a un componente inesistente.

**L'issue lo dava per irraggiungibile; non lo era.** I quattro siti di *produzione* passano
`source` esplicito, ma otto test costruiscono `RouteResult` senza — e uno di questi
(`test_app_runtime_glue.py`, segnale scartato) manda il risultato proprio al diario. Prima di
questa correzione quel diario registrava `source="hardcoded"`.

Il default ora è `UNKNOWN`: dichiara di **non sapere** invece di nominare qualcosa che non
esiste. È la differenza fra un fallback onesto e uno che mente — la stessa distinzione delle
#254/#261/#263/#264/#265.
"""

import ast
import pathlib

from xtrader_bridge import signal_outcome, signal_router

_SORGENTE = pathlib.Path(signal_router.__file__)


def test_233_il_default_di_source_non_nomina_il_parser_rimosso():
    """Il cuore della issue. Rosso prima della correzione: il default era `"hardcoded"`."""
    res = signal_router.RouteResult(row={"EventName": "Inter v Milan"})
    assert res.source != "hardcoded", (
        "il default di RouteResult.source nomina il parser P.Bet, RIMOSSO nella #76: "
        "finirebbe nel diario e nel log come sorgente della scrittura")
    assert res.source == signal_router.UNKNOWN
    assert res.source == "unknown"


def test_233_il_log_operatore_non_attribuisce_il_segnale_a_un_parser_inesistente():
    """La superficie che conta: `source` esce di qui e finisce sotto gli occhi dell'operatore.

    Senza questo test la correzione sarebbe verificata solo sulla dataclass, non su ciò che
    l'utente legge davvero — ed è la lezione della #259, dove un test che chiamava solo la
    funzione interna lasciava scoperto il percorso reale.
    """
    res = signal_router.RouteResult(row={"EventName": "Inter v Milan"})
    riga = signal_outcome.describe_write(
        {"EventName": "Inter v Milan", "SelectionName": "Over 2,5 goal", "Price": "1,85"},
        res.source, 1).signal_log

    assert "hardcoded" not in riga, riga
    assert "📱 Segnale (unknown)" in riga, riga


def test_233_nessun_identificatore_HARDCODED_residuo_nel_router():
    """Guardia anti-reintroduzione. Misura il CODICE via AST, non il testo del file.

    La prima stesura faceva un `in` sul sorgente grezzo, e ha bocciato **il commento che
    spiega la rimozione** — cioè avrebbe vietato di documentare il perché. Una guardia che
    per funzionare pretende che il codice taccia sulla propria storia è tarata male: il
    difetto è la *costante viva*, non la parola.

    L'AST non contiene i commenti, quindi la spiegazione resta e il vincolo si stringe su ciò
    che conta davvero — un identificatore o un letterale realmente presenti nel codice. È lo
    stesso principio del gate blind-except: si misura la struttura, non il testo.
    """
    albero = ast.parse(_SORGENTE.read_text(encoding="utf-8"))

    nomi = {n.id for n in ast.walk(albero) if isinstance(n, ast.Name)}
    nomi |= {n.attr for n in ast.walk(albero) if isinstance(n, ast.Attribute)}
    assert "HARDCODED" not in nomi, (
        "l'identificatore `HARDCODED` è tornato in signal_router.py: nomina il parser P.Bet "
        "rimosso nella #76, e non ha più un referente nel repository")

    letterali = {n.value for n in ast.walk(albero)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "hardcoded" not in letterali, (
        "il letterale 'hardcoded' è tornato nel codice di signal_router.py (i commenti non "
        "contano: l'AST non li vede, e spiegare la rimozione è legittimo)")


def test_233_i_quattro_siti_di_produzione_dichiarano_ANCORA_la_sorgente():
    """Contro-guardia: la correzione non deve trasformare un `source` esplicito in un default.

    Se un domani un sito smettesse di passarlo, il valore diventerebbe `unknown` — onesto, ma
    comunque una perdita di informazione. Qui si blocca quella deriva leggendo l'AST: ogni
    costruzione di `RouteResult` dentro il router deve indicare la sorgente, posizionalmente
    (terzo argomento) o per nome.
    """
    albero = ast.parse(_SORGENTE.read_text(encoding="utf-8"))
    costruzioni = [n for n in ast.walk(albero)
                   if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id == "RouteResult"]
    assert len(costruzioni) == 4, f"attesi 4 siti di costruzione, trovati {len(costruzioni)}"

    for chiamata in costruzioni:
        per_nome = "source" in {k.arg for k in chiamata.keywords}
        posizionale = len(chiamata.args) >= 3          # row, status, source
        assert per_nome or posizionale, (
            f"RouteResult costruito senza `source` a riga {chiamata.lineno}: "
            "cadrebbe sul default `unknown` perdendo la sorgente reale")
