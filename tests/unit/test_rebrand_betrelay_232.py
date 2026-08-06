"""#232 Strato 1 — «XTrader Signal Bridge» → «BetRelay», solo il BRAND VISIBILE.

Decisione del proprietario: il programma cambia nome commerciale in **BetRelay**, perché serve
un nome neutro rispetto al software di destinazione — il bridge non serve più solo XTrader
(Italia) ma tutta la famiglia Betting Toolkit (.COM/.ES/.LAT). Dare «XTrader Bridge» a un
utente Betting Toolkit è ambiguo.

Il nome è **uguale in tutte le lingue**: BetRelay è il nostro prodotto, non un termine da
tradurre. Da non confondere con la #286, che traduceva il nome del software di *destinazione*.

## Il principio: rename A STRATI

Questo è lo **Strato 1**: il brand che l'utente vede. Lo **Strato 2** — cartella `%APPDATA%`,
mutex single-instance, servizio keyring — **non si tocca qui**, e questo file lo pretende con
test dedicati, perché rinominarli non è cosmetico:

    APP_DIR_NAME  = "XTraderBridge"   rinominarlo senza migrazione PERDE la config
    DEFAULT_NAME  = "XTraderBridge"   è il mutex: rinominarlo permette DUE istanze insieme
    SERVICE       = "XTraderBridge"   è il keyring: rinominarlo PERDE il token salvato

Il caso peggiore è il mutex: durante un aggiornamento la vecchia versione e la nuova userebbero
nomi diversi, quindi il lock anti-doppia-istanza non le vedrebbe come la stessa app — due
bridge che scrivono lo stesso CSV.

## La trappola che l'issue non aveva previsto

`tests/safety/test_license_manager_isolation.py` distingue i workflow che buildano il bridge da
quelli che buildano il License Manager, per impedire che il secondo finisca dentro il primo. Il
riconoscimento avviene per **nome dell'EXE**:

    _BUILDS_BRIDGE = re.compile(r"XTrader-Signal-Bridge|--collect-submodules\\s+xtrader_bridge")

Misurato: `build-nuitka.yaml` **non contiene** `--collect-submodules xtrader_bridge`, quindi per
quel workflow il riconoscimento dipende **solo** dal nome dell'EXE. Rinominarlo senza aggiornare
la regex lo farebbe sparire dal radar della guardia — che continuerebbe a passare **verde** non
avendo più nulla da controllare. Una guardia che tace è indistinguibile da una che approva.
"""

import re

import pytest

from xtrader_bridge import config_store, instance_lock, token_store

NUOVO = "BetRelay"

#: Lo Strato 2, che questa PR NON tocca. Nome del modulo → attributo → valore che deve restare.
INTERNI_INTOCCABILI = (
    (config_store, "APP_DIR_NAME", "la cartella %APPDATA%: rinominarla senza migrazione perde la config"),
    (instance_lock, "DEFAULT_NAME", "il mutex single-instance: rinominarlo permette DUE istanze insieme"),
    (token_store, "SERVICE", "il servizio keyring: rinominarlo perde il token salvato dall'utente"),
)


# ── ① il brand visibile ───────────────────────────────────────────────────────────────

def test_il_titolo_della_finestra_dice_betrelay():
    """FAIL-FIRST: la finestra si intitolava «XTrader Signal Bridge v…»."""
    import inspect

    from xtrader_bridge import app

    src = inspect.getsource(app)
    assert 'self.title(f"BetRelay v' in src, "titolo finestra non rinominato"
    assert "XTrader Signal Bridge v" not in src, "titolo vecchio rimasto"


def test_l_header_della_gui_dice_betrelay():
    """FAIL-FIRST: l'header diceva «🤖 XTrader Signal Bridge». Emoji 📡 scelta dal proprietario:
    il satellite richiama il *relay* del nome — il programma inoltra segnali, non li genera."""
    import inspect

    from xtrader_bridge import app

    src = inspect.getsource(app)
    assert "📡  BetRelay" in src, "header GUI non rinominato"
    assert "🤖  XTrader Signal Bridge" not in src, "header vecchio rimasto"


def test_il_titolo_della_diagnostica_dice_betrelay():
    """Il report di diagnostica che l'utente esporta e allega quando chiede aiuto: se dicesse
    ancora il nome vecchio, chi lo riceve non saprebbe di che programma si parla."""
    from xtrader_bridge import diagnostics

    assert diagnostics._TITLE.startswith(NUOVO), diagnostics._TITLE
    assert "XTrader Signal Bridge" not in diagnostics._TITLE


def test_il_dialogo_doppia_istanza_dice_betrelay():
    """Il messaggio che l'utente legge quando apre il programma due volte. È anche l'unico posto
    dove il nome visibile e il nome del MUTEX si somigliano: qui cambia il primo, non il secondo."""
    import inspect

    from xtrader_bridge import app

    src = inspect.getsource(app)
    assert "BetRelay è già in esecuzione" in src
    assert "XTrader Bridge è già in esecuzione" not in src


# ── ② lo Strato 2 NON si tocca ────────────────────────────────────────────────────────

@pytest.mark.parametrize("modulo, attributo, perche", INTERNI_INTOCCABILI)
def test_gli_interni_non_sono_stati_rinominati(modulo, attributo, perche):
    """**I test più importanti di questo file.**

    Lo Strato 1 è cosmetico; questi tre nomi non lo sono. Se un domani qualcuno «completasse»
    il rebrand passando un `sed` su «XTraderBridge», questi test lo fermano prima della CI —
    e prima che un utente perda la configurazione, il token, o si ritrovi due bridge che
    scrivono lo stesso CSV.
    """
    assert getattr(modulo, attributo) == "XTraderBridge", (
        f"{modulo.__name__}.{attributo} è stato rinominato: {perche}. "
        f"È Strato 2 (#232) e richiede una migrazione, non una rinomina."
    )


# ── ③ la guardia di isolamento deve riconoscere la build rinominata ───────────────────

def test_la_guardia_di_isolamento_riconosce_ancora_le_build_del_bridge():
    """**La trappola che l'issue non aveva previsto**, ed è la ragione per cui questo file
    esiste oltre ai quattro test cosmetici.

    `test_license_manager_isolation` impedisce che il License Manager finisca dentro l'EXE del
    bridge. Riconosce «una build del bridge» dal nome dell'EXE — e per `build-nuitka.yaml` è
    l'**unico** appiglio, perché quel workflow non usa `--collect-submodules xtrader_bridge`
    (misurato: 0 occorrenze).

    Rinominare l'EXE senza aggiornare la regex non avrebbe rotto nulla di visibile: il test
    sarebbe rimasto VERDE, semplicemente senza più trovare build da controllare. Il difetto si
    sarebbe visto solo il giorno in cui qualcuno avesse aggiunto `license_manager` a quel
    workflow — cioè troppo tardi.
    """
    from tests.safety.test_license_manager_isolation import _BUILDS_BRIDGE

    build_nuova = "nuitka --onefile --output-filename=BetRelay.exe main.py"
    assert _BUILDS_BRIDGE.search(build_nuova), (
        "la guardia di isolamento non riconosce più una build del bridge dopo la rinomina: "
        "smetterebbe di proteggere `build-nuitka.yaml` restando verde"
    )

    # …e continua a riconoscere anche il nome storico, così una build non ancora migrata
    # non sfugge: riconoscerne DI PIÙ è la direzione sicura.
    build_vecchia = "pyinstaller --onefile --name XTrader-Signal-Bridge main.py"
    assert _BUILDS_BRIDGE.search(build_vecchia), "il nome storico non è più riconosciuto"


def test_la_guardia_non_e_diventata_onnivora():
    """La metà opposta: allargare la regex non deve farle scambiare per «build del bridge» il
    workflow DEDICATO del License Manager, che impacchetta `license_manager` legittimamente per
    il proprio EXE. Se succedesse, quel workflow risulterebbe sempre in violazione."""
    from tests.safety.test_license_manager_isolation import _BUILDS_BRIDGE

    build_lm = ("pyinstaller --onefile --name LicenseManager "
                "--collect-submodules license_manager tools/lm.py")
    assert not _BUILDS_BRIDGE.search(build_lm), (
        "la guardia scambia il build del License Manager per un build del bridge"
    )


def test_il_handoff_cita_lo_stesso_header_del_codice():
    """Rilievo Claude Fable 5 sulla #299: il handoff diceva ancora «🤖 BetRelay» mentre
    `app.py` era già passato a «📡». Drift documentale **nel documento che è il gate**.

    `design_handoff.md` cita l'header **verbatim** in due punti — è il suo scopo: chi fa il
    design lo legge per sapere cosa disegnare. Se diverge dal codice, disegna un'altra app.
    Il gate del `CLAUDE.md` pretende che l'handoff sia aggiornato; questo test pretende che
    sia aggiornato **con il valore giusto**, che è la parte che un gate umano si perde.

    **Legge l'header via AST, non con un grep di riga** (rilievo GPT-5.5 sulla #299). La prima
    stesura cercava una riga contenente insieme «BetRelay» e «text=»: si rompe se la chiamata
    viene formattata su più righe, cioè su un refactor che non cambia nulla di sostanziale.
    L'AST vede la struttura e non la formattazione — è la stessa scelta già fatta nella #285.
    """
    import ast
    import inspect
    import pathlib
    import textwrap

    from xtrader_bridge import app

    albero = ast.parse(textwrap.dedent(inspect.getsource(app.App._build_ui)))
    etichette = [
        kw.value.value
        for n in ast.walk(albero)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "CTkLabel"
        for kw in n.keywords
        if kw.arg == "text" and isinstance(kw.value, ast.Constant)
        and isinstance(kw.value.value, str) and "BetRelay" in kw.value.value
    ]
    assert etichette, "nessuna CTkLabel con «BetRelay» trovata in _build_ui"
    assert all("📡" in e for e in etichette), f"header senza l'emoji attesa: {etichette!r}"

    handoff = (pathlib.Path(app.__file__).parent.parent
               / "docs" / "design" / "design_handoff.md")
    if not handoff.exists():
        pytest.skip("design_handoff.md non presente in questo albero")

    testo = handoff.read_text(encoding="utf-8")
    assert "🤖  BetRelay" not in testo, (
        "il design handoff cita ancora «🤖  BetRelay» mentre il codice usa «📡»: chi fa il "
        "design disegnerebbe un header che l'app non ha"
    )
    assert "📡  BetRelay" in testo, "il design handoff non cita l'header attuale"


def test_il_percorso_csv_di_default_dice_betrelay():
    """Il default di `csv_path`, deciso dal proprietario insieme al resto del rebrand.

    **Non è solo un placeholder grafico**: `config_store.DEFAULTS["csv_path"]` è il valore che
    eredita ogni installazione NUOVA. Chi ha già una config tiene il suo percorso — il default
    non tocca nulla di esistente — ma a un utente nuovo il programma proponeva una cartella
    che porta il nome vecchio.

    Il campo GUI mostra lo stesso percorso come esempio: se i due divergessero, il
    suggerimento e il valore precompilato indicherebbero posti diversi.
    """
    from xtrader_bridge import app as app_mod

    assert config_store.DEFAULTS["csv_path"] == r"C:\BetRelay\segnali.csv"
    assert "BetRelay" in app_mod._FIELD_PLACEHOLDERS["csv_path"]
    assert "XTrader" not in app_mod._FIELD_PLACEHOLDERS["csv_path"]


def test_una_config_esistente_conserva_il_suo_percorso_csv(tmp_path):
    """**Rilievo Claude Fable 5 sulla #299, punto 2** — la metà che rende innocuo il cambio di
    default: chi ha già configurato il bridge **non viene spostato**.

    Il default vale solo per le chiavi ASSENTI. Un utente che ha puntato XTrader su
    `C:\\XTrader\\segnali.csv` deve continuare a scriverci: se il caricamento «migrasse» il
    percorso al nuovo default, il bridge scriverebbe in una cartella che XTrader non guarda —
    e i segnali sparirebbero **in silenzio**, senza nessun errore visibile.

    È l'unico modo in cui il rebrand poteva diventare una perdita di segnali su un'installazione
    esistente, quindi è pinnato qui e non lasciato al test generico sul merge dei default.
    """
    import json

    p = tmp_path / "config.json"
    p.write_text(json.dumps({"csv_path": r"C:\XTrader\segnali.csv"}), encoding="utf-8")

    cfg = config_store.load_config(str(p))
    assert cfg["csv_path"] == r"C:\XTrader\segnali.csv", (
        "il percorso CSV salvato dall'utente è stato sostituito dal nuovo default: il bridge "
        "scriverebbe dove XTrader non legge"
    )


def test_il_preflight_del_percorso_csv_blocca_l_avvio_e_precede_il_listener():
    """**Rilievo Claude Fable 5 sulla #299, punto 2** — l'altra metà: su un'installazione NUOVA
    il default `C:\\BetRelay\\` è una cartella che tipicamente **non esiste**.

    Il comportamento sicuro c'è già (`csv_path_problem` a START), ma non era pinnato da nessuna
    parte: nulla impediva a un refactor di spostare il pre-flight **dopo** l'avvio del listener.
    In quel caso il bridge risulterebbe «ATTIVO» scrivendo verso un percorso inutilizzabile —
    il fallimento sarebbe silenzioso, e silenzioso è il modo peggiore di sbagliare qui.

    `_start` è GUI/thread-coupled e non istanziabile headless: si pinna il **wiring**, stesso
    pattern già usato da `test_start_senza_parser_attivo_e_bloccante`. La logica pura di
    `csv_path_problem` è coperta a parte in `test_config_basic`.
    """
    import inspect

    from xtrader_bridge import app

    src = inspect.getsource(app.App._start)
    assert "csv_path_problem" in src, "il pre-flight del percorso CSV è sparito da _start"

    idx = src.index("csv_path_problem")
    blocco = src[idx:idx + 400]
    assert "Avvio annullato" in blocco, "il problema di percorso non è più segnalato all'utente"
    assert "return" in blocco, (
        "il pre-flight non è più BLOCCANTE: il listener partirebbe con un percorso inutilizzabile"
    )

    # …e sta PRIMA dell'avvio vero. L'ancora deve esistere (niente fallback no-op che passerebbe
    # in silenzio su un rename), e comparire DOPO il guard.
    assert "_bot_thread" in src
    assert idx < src.index("_bot_thread"), (
        "il pre-flight del percorso CSV è finito DOPO l'avvio del listener: il bridge andrebbe "
        "in stato ATTIVO prima di sapere se il CSV è scrivibile"
    )


# ── ④ il nome dell'EXE nei workflow di build ──────────────────────────────────────────

@pytest.mark.parametrize("workflow", ["build.yaml", "build-nuitka.yaml"])
def test_i_workflow_producono_l_exe_col_nome_nuovo(workflow):
    """FAIL-FIRST: entrambi producevano `XTrader-Signal-Bridge.exe`."""
    import pathlib

    percorso = pathlib.Path(__file__).parent.parent.parent / ".github" / "workflows" / workflow
    if not percorso.exists():
        pytest.skip(f"{workflow} non presente in questo albero")

    testo = percorso.read_text(encoding="utf-8")
    assert re.search(r"\bBetRelay\.exe\b", testo), f"{workflow} non produce BetRelay.exe"
    assert "XTrader-Signal-Bridge.exe" not in testo, f"{workflow} produce ancora il nome vecchio"
