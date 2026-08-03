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

import pathlib
import re

RADICE = pathlib.Path(__file__).resolve().parents[2]


def _metodi_di_app_chiamati_con_argomenti() -> dict:
    """Metodi di `App` che il codice invoca passando almeno un argomento → nome → firma.

    Un metodo con parametro **opzionale** mai passato da nessun chiamante non è un problema:
    uno stub a zero argomenti lo soddisfa. Conta solo ciò che viene davvero chiamato con
    argomenti, altrimenti il gate segnalerebbe stub innocui."""
    src = (RADICE / "xtrader_bridge" / "app.py").read_text(encoding="utf-8")
    firme = {m.group(1): m.group(2)
             for m in re.finditer(r"^    def (_?\w+)\(self(.*?)\)\s*(?:->.*?)?:", src, re.MULTILINE)}
    con_argomenti = {}
    for nome, firma in firme.items():
        if not firma.strip():
            continue
        for chiamata in re.findall(rf"self\.{re.escape(nome)}\(([^)]*)\)", src):
            if chiamata.strip():
                con_argomenti[nome] = f"def {nome}(self{firma})"
                break
    return con_argomenti


def test_nessuno_stub_dei_test_ignora_gli_ARGOMENTI_del_metodo_vero():
    """Un `lambda:` senza parametri assegnato a un metodo che il codice chiama CON argomenti.

    Fail-first: prima della correzione questo test elencava 9 siti."""
    attesi = _metodi_di_app_chiamati_con_argomenti()
    assert attesi, "nessun metodo trovato: la scansione di app.py non funziona più"

    infedeli = []
    for f in sorted((RADICE / "tests").rglob("*.py")):
        if f.name == pathlib.Path(__file__).name:
            continue                                  # questo file cita i nomi negli esempi
        for n, riga in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            m = re.match(r"\s*\w+\.(_\w+)\s*=\s*lambda\s*:", riga)
            if m and m.group(1) in attesi:
                infedeli.append(f"{f.relative_to(RADICE)}:{n} — {m.group(1)} "
                                f"stub a 0 argomenti, ma «{attesi[m.group(1)]}» "
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
    Lo stub `telegram.ext` del conftest NON basta: viene installato solo quando PTB è assente."""
    colpevoli = []
    for f in sorted((RADICE / "tests").rglob("*.py")):
        if f.name == pathlib.Path(__file__).name:
            continue                                  # questo file nomina _run_bot nei commenti
        testo = f.read_text(encoding="utf-8")
        esegue = re.search(r"App\._run_bot\(", testo)
        # Serve la SOSTITUZIONE vera, non una citazione: il primo giro di questo gate
        # cercava la parola «ApplicationBuilder» nel file e passava per via del docstring
        # che la nominava — un test decorativo che non provava niente.
        sostituisce = re.search(r"setattr\(\s*\w+\s*,\s*[\"']ApplicationBuilder[\"']", testo)
        if esegue and not sostituisce:
            colpevoli.append(f.relative_to(RADICE))

    assert not colpevoli, (
        "questi test eseguono `App._run_bot` senza sostituire `ApplicationBuilder`: "
        "aprono una connessione di rete VERA e l'esito dipende dalla rete\n  "
        + "\n  ".join(str(c) for c in colpevoli))
