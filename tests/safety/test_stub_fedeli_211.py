"""Gli stub dei test devono rispettare la firma del metodo che sostituiscono — Issue #211 R1.

**Perché esiste.** Nel report Codex verificato nella #211, un test integrazione sostituiva
`_set_status_reconnecting` con `lambda: None` — zero argomenti — mentre il metodo vero è
`def _set_status_reconnecting(self, epoch=None)` e il codice lo chiama `self._set_status_
reconnecting(epoch)`, cioè **con** un argomento.

Lo stub sopravviveva solo perché quel ramo non veniva raggiunto nell'ambiente di CI. Cambiato
ambiente, il ramo si raggiunge e lo stub **solleva `TypeError`**: un test rosso su un difetto
inesistente, o — peggio, nell'altra direzione — un fake che accetta ciò che il vero rifiuta e
nasconde un difetto reale.

Riprodotto il 03/08 su `main` bloccando le connessioni di rete durante la suite:

    FAILED test_run_bot_eccezione_imprevista_chiude_loop_e_handle
    xtrader_bridge/app.py:3785: TypeError

**La classe, non il sito.** La #211 ne nominava 2; la scansione ne ha trovati **9**, su quattro
metodi diversi (`_set_status_reconnecting`, `_set_status_connected`, `_resync_token_field`,
`_save_config`), tutti chiamati con argomenti da `app.py`. Questo test presidia la classe.

**Il secondo gate: il doppio che non c'è.** Correggere gli stub ha scoperto un difetto peggiore
nascosto sotto. `test_bot_after_teardown_76.py` eseguiva il VERO `_run_bot` senza sostituire
`ApplicationBuilder`: il suo docstring prometteva «sotto gli stub del conftest», ma quello stub
esiste **solo quando `python-telegram-bot` NON è installato**. Con PTB presente il test costruiva
una `Application` VERA e apriva una **connessione di rete reale**. Terminava solo perché la rete
rispondeva rifiutando il token — un errore permanente. Con la rete bloccata l'errore diventa
`NetworkError`, cioè **transitorio**: il supervisor entra nel backoff e il test **si appende**
(verificato: pytest-timeout lo uccide a `stop_event.wait(delay)`, `app.py:3842`). Lo stub
infedele mascherava tutto: il suo `TypeError` era permanente e chiudeva il giro in fretta.
"""

import ast
import pathlib

RADICE = pathlib.Path(__file__).resolve().parents[2]


def _albero(percorso: pathlib.Path) -> ast.Module:
    return ast.parse(percorso.read_text(encoding="utf-8"), filename=str(percorso))


def _firma(fn) -> str:
    """Firma leggibile del metodo, per il messaggio d'errore."""
    a = fn.args
    parti = [x.arg for x in (*a.posonlyargs, *a.args)]
    if a.vararg:
        parti.append("*" + a.vararg.arg)
    parti += [x.arg for x in a.kwonlyargs]
    if a.kwarg:
        parti.append("**" + a.kwarg.arg)
    return f"def {fn.name}({', '.join(parti)})"


def _metodi_di_app_chiamati_con_argomenti() -> dict:
    """Metodi di `App` che il codice invoca passando almeno un argomento → nome → firma.

    Un metodo con parametro **opzionale** mai passato da nessun chiamante non è un problema:
    uno stub a zero argomenti lo soddisfa. Conta solo ciò che viene davvero chiamato con
    argomenti, altrimenti il gate segnalerebbe stub innocui.

    Analisi via **AST**, non regex (rilievo convergente di Sourcery, GPT-5.5 e Fable sulla
    PR #221). Il primo giro leggeva `app.py` con `re.finditer` su `^    def nome(self...)`:
    una firma spezzata su piu' righe, un decoratore o un tipo di ritorno annotato la
    facevano sparire dall'elenco — e un metodo che sparisce dall'elenco e' un metodo che il
    gate **smette di sorvegliare in silenzio**, che e' il difetto peggiore possibile per un
    gate. Con l'AST la formattazione non conta."""
    albero = _albero(RADICE / "xtrader_bridge" / "app.py")
    classe = next((n for n in ast.walk(albero)
                   if isinstance(n, ast.ClassDef) and n.name == "App"), None)
    assert classe is not None, "classe App non trovata in app.py: la scansione e' da rifare"

    metodi = {}
    for n in classe.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = n.args
            # Un metodo che accetta SOLO self non puo' essere chiamato con argomenti.
            if len(a.posonlyargs) + len(a.args) > 1 or a.kwonlyargs or a.vararg or a.kwarg:
                metodi[n.name] = _firma(n)

    con_argomenti = {}
    for n in ast.walk(albero):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "self"
                and n.func.attr in metodi and (n.args or n.keywords)):
            con_argomenti[n.func.attr] = metodi[n.func.attr]
    return con_argomenti


def _stub_a_zero_argomenti(percorso: pathlib.Path):
    """Assegnazioni `qualcosa.metodo = lambda: ...` nel file → (nome_metodo, riga).

    Anche qui AST: `lambda` con lista argomenti VUOTA, indipendentemente da come e'
    scritta o spezzata."""
    for n in ast.walk(_albero(percorso)):
        if not isinstance(n, ast.Assign) or not isinstance(n.value, ast.Lambda):
            continue
        a = n.value.args
        if a.posonlyargs or a.args or a.kwonlyargs or a.vararg or a.kwarg:
            continue                                   # lo stub accetta argomenti: fedele
        for bersaglio in n.targets:
            if isinstance(bersaglio, ast.Attribute):
                yield bersaglio.attr, n.lineno


def test_nessuno_stub_dei_test_ignora_gli_ARGOMENTI_del_metodo_vero():
    """Un `lambda:` senza parametri assegnato a un metodo che il codice chiama CON argomenti.

    Fail-first: prima della correzione questo test elencava 9 siti."""
    attesi = _metodi_di_app_chiamati_con_argomenti()
    assert attesi, "nessun metodo trovato: la scansione di app.py non funziona più"

    infedeli = []
    for f in sorted((RADICE / "tests").rglob("*.py")):
        if f.name == pathlib.Path(__file__).name:
            continue                                  # questo file cita i nomi negli esempi
        for nome, riga in _stub_a_zero_argomenti(f):
            if nome in attesi:
                infedeli.append(f"{f.relative_to(RADICE)}:{riga} — {nome} "
                                f"stub a 0 argomenti, ma «{attesi[nome]}» "
                                f"è chiamato CON argomenti")

    assert not infedeli, (
        "stub che non rispettano la firma del metodo vero — useranno `lambda *a, **k:`:\n  "
        + "\n  ".join(infedeli))


def test_chi_esegue_run_bot_deve_sostituire_ApplicationBuilder():
    """Nessun test può eseguire il VERO `_run_bot` col `ApplicationBuilder` REALE.

    `_run_bot` costruisce l'app Telegram e fa `await app.initialize()`: col builder vero
    quella è una **connessione di rete**. Un test che ci finisce dentro non è più
    deterministico — passa o si appende a seconda di COME la rete fallisce (token rifiutato =
    permanente → esce; rete assente = `NetworkError` transitorio → backoff infinito).

    Fail-first: prima della correzione questo test elencava `test_bot_after_teardown_76.py`.
    Lo stub `telegram.ext` del conftest NON basta: viene installato solo quando PTB è assente.

    **Il limite, dichiarato** (rilievo Sourcery/GPT-5.5 sulla PR #221). Il gate riconosce la
    chiamata DIRETTA `App._run_bot(...)` e la sostituzione fatta NELLO STESSO file. Un test
    che raggiungesse `_run_bot` per alias, o che ricevesse il builder finto da una fixture in
    `conftest.py`, sarebbe segnalato qui pur essendo corretto. È il verso giusto in cui
    sbagliare: un **falso positivo** fallisce rumorosamente e si sistema in un minuto,
    mentre un falso negativo rimetterebbe in silenzio una connessione vera dentro la suite —
    che è il difetto per cui questo file esiste. Se un domani la fixture condivisa diventa la
    norma, il gate va esteso a riconoscerla, non allentato."""
    io_stesso = pathlib.Path(__file__).name
    colpevoli = []
    for f in sorted((RADICE / "tests").rglob("*.py")):
        if f.name == io_stesso:
            continue                                  # questo file nomina _run_bot nei commenti
        esegue = sostituisce = False
        for n in ast.walk(_albero(f)):
            if not isinstance(n, ast.Call):
                continue
            # `App._run_bot(a, cfg, epoch)` — esecuzione del vero supervisor.
            if isinstance(n.func, ast.Attribute) and n.func.attr == "_run_bot":
                esegue = True
            # Serve la SOSTITUZIONE vera, non una citazione: il primo giro di questo gate
            # cercava la parola «ApplicationBuilder» nel testo e passava per via del
            # docstring che la nominava — un test decorativo che non provava niente.
            # `monkeypatch.setattr(app_mod, "ApplicationBuilder", ...)`: conta il secondo
            # argomento, cioè il NOME sostituito, non una stringa qualunque nel file.
            if (isinstance(n.func, ast.Attribute) and n.func.attr == "setattr"
                    and len(n.args) >= 2 and isinstance(n.args[1], ast.Constant)
                    and n.args[1].value == "ApplicationBuilder"):
                sostituisce = True
        if esegue and not sostituisce:
            colpevoli.append(f.relative_to(RADICE))

    assert not colpevoli, (
        "questi test eseguono `App._run_bot` senza sostituire `ApplicationBuilder`: "
        "aprono una connessione di rete VERA e l'esito dipende dalla rete\n  "
        + "\n  ".join(str(c) for c in colpevoli))
