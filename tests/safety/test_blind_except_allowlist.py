"""Guardia sui `except Exception` / bare `except:` "ciechi" (issue #186 finding 4).

Un `except Exception:` (o `except BaseException:`, o un bare `except:`) cattura **qualsiasi**
errore, anche quelli inattesi: usato dove serve (best-effort/fail-safe documentati) è corretto,
ma un nuovo blind-except introdotto per sbaglio può **ingoiare silenziosamente** un bug reale.

Questo test NON vieta i blind-except: ne fotografa il numero **per modulo** in una **allowlist**
con motivazione, e **fallisce se il conteggio cambia** (ratchet). Così:
- aggiungere un nuovo blind-except in un file → il conteggio sale → il test FALLISCE finché non
  lo si restringe a un'eccezione specifica, OPPURE lo si motiva aggiornando `_ALLOWLIST`;
- rimuoverne uno → il conteggio scende → il test FALLISCE per ricordare di **stringere** il
  baseline (mantiene l'allowlist onesta, come `test_build_exe_safety.py` per le opzioni PyInstaller).

Conta per **modulo** (non per riga) così un refactor che sposta le righe non rompe il test.
"""

import ast
import os

import pytest

_PKG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                    "xtrader_bridge")

# Allowlist: per ogni modulo che ne contiene, il numero di blind-except ATTESI + il perché.
# I blind-except qui sono best-effort/fail-safe documentati (spesso con `# noqa: BLE001`):
# GUI Tk (un callback che solleva non deve buttare giù la finestra), soft-import/fallback
# (keyring/credential store: qualsiasi errore = backend non disponibile), best-effort di
# teardown/log/summary (un fallimento non critico non deve propagare nel percorso safety).
# Aggiornare SOLO con motivazione esplicita quando si aggiunge/rimuove un blind-except.
_ALLOWLIST = {
    "app.py": (45, "glue runtime/GUI Tk: teardown, callback after(), log e auto-start best-effort; "
                   "event journal best-effort (#230); refill campo token su widget Tk distrutto (PR-08c); "
                   "engine/DB non disponibile → login Betfair senza riserva del lock (#172 audit); "
                   "probe is_syncing dell'anteprima ID fail-open (#192, Codex P2); "
                   "after_cancel del retry post-stop clear CSV su id scaduto/invalido (#259 A1, "
                   "stesso pattern del tick auto-sync); "
                   "install_global_log_redaction all'avvio best-effort (#259 D3: la redazione "
                   "è difensiva, non deve mai impedire l'avvio della GUI); "
                   "known_teams del dizionario Betfair per precompilare la mappatura nomi "
                   "best-effort (#282 PR 11: DB assente → [], la GUI non crasha); "
                   "delete_known_team best-effort (#282 PR 11-bis: DB assente → False); "
                   "known_market_terms best-effort (#283 PR 13: DB assente → liste vuote); "
                   "snapshot Riepilogo config best-effort (#293 slice 3: conteggio dizionario "
                   "Betfair e stato login → DB occupato/assente o sessione non inizializzata "
                   "degradano a False, il riepilogo sola-lettura non deve mai crashare); "
                   "avviso «già in esecuzione» su root Tk temporanea best-effort (#311-1.1: "
                   "in headless/display assente l'uscita della seconda istanza avviene comunque); "
                   "dialog conferma COLLAUDO (#311 §3.1): errore dialog → NON confermare "
                   "(fail-closed, stesso pattern di _confirm_real_mode/_confirm_multi_signal); "
                   "(#343 slice 4b: rimosso il blind-except sulla lettura del testo _status_lbl — "
                   "il semaforo Telegram ora usa lo stato CANONICO _listener_state, niente widget); "
                   "_refresh_health interamente best-effort (Fable #351): una sonda che solleva "
                   "(share instabile, config corrotta) non deve MAI rompere il monitoraggio "
                   "primario ne' i chiamanti _set_last/START/STOP/save; "
                   "apertura Wizard best-effort (#311 §3.4: un Toplevel che fallisce mostra "
                   "la classe dell'errore nel log invece di rompere la finestra principale); "
                   "singleton Wizard (Fable #354): riferimento stantio con winfo_exists che "
                   "solleva (Tk smontato) → si riapre un wizard nuovo invece di crashare; "
                   "lift/focus_force best-effort sul wizard vivo (GPT #354: un errore di "
                   "focus non deve degradare in un secondo Toplevel modale doppione); "
                   "selettore lingua al primo avvio (#343): apertura best-effort (senza "
                   "scelta resta il comportamento storico IT e si ripropone al prossimo "
                   "avvio) + destroy best-effort del selettore su widget già distrutto"),
    "atomic_io.py": (1, "cleanup del temporaneo su QUALSIASI errore di scrittura/rename (BaseException)"),
    "wizard_gui.py": (3, "vista Wizard (#311 §3.4, review Fable #354): (1) sonda in thread "
                         "che solleva → esito FAIL-CLOSED con la sola classe dell'errore e "
                         "flag _probe_running SEMPRE rilasciato (mai ⏳ eterna); (2) after() "
                         "su finestra/Tk distrutti durante la sonda → niente da aggiornare; "
                         "(3) winfo_exists che solleva a interprete smontato = finestra chiusa"),
    "wizard.py": (3, "sonde one-shot del Wizard (#311 §3.4): getMe/getUpdates/scrittura "
                     "di prova — qualsiasi errore diventa un esito FAIL-CLOSED col messaggio "
                     "SANIFICATO (mai il token/URL nell'errore), lo step non passa e il "
                     "wizard non crasha"),
    "parser_builder.py": (1, "isolamento PER-MESSAGGIO del tester batch (#311 §3.2, CodeRabbit "
                             "#350): un messaggio patologico non deve abortire il batch "
                             "nascondendo gli altri report — l'errore resta VISIBILE nel "
                             "verdetto ❌ di quel messaggio (fail-visible, mai silenzioso)"),
    "instance_lock.py": (2, "#311-1.1 single-instance: fail-open CONSAPEVOLE su errore imprevisto "
                         "del SO nella creazione del lock (un bridge inavviabile per un guasto raro "
                         "è peggio del caso limite; warning nei log) + release best-effort (a morte "
                         "processo rilascia comunque il SO: mutex named / flock)"),
    "config_store.py": (3, "backup config corrotta best-effort + rollback keyring best-effort + "
                           "gate #311-2.3 `_default_recognition_mode` fail-safe → NAME_ONLY"),
    "config_summary_gui.py": (1, "GUI Tk scheda Riepilogo (#293 slice 3, sola lettura): il "
                             "summary_provider che solleva mostra un avviso invece di rompere "
                             "la finestra (stesso pattern best-effort degli altri pannelli)"),
    "csv_writer.py": (1, "callback diagnostico best-effort di clear_stale_csv: un sink log/GUI che "
                         "solleva non deve rompere il cleanup anti-segnale-stantio all'avvio/STOP (#241)"),
    "dizionario.py": (1, "gate #311-2.3 `is_validated` fail-safe: dizionario assente/header rotto → "
                         "non validato (False) → default recognition_mode resta NAME_ONLY, mai BOTH su "
                         "dati inaffidabili"),
    "custom_parser_gui.py": (10, "GUI Tk del costruttore parser: render/azioni best-effort "
                             "(incl. resolver ID anteprima fail-open, #192; termini Betfair "
                             "per le tendine MarketType/MarketName/SelectionName best-effort, "
                             "#283 PR 13: sync in corso/DB assente → nessun suggerimento)"),
    "custom_pipeline.py": (1, "id_resolver iniettato: un resolver che solleva NON blocca la riga (fail-open)"),
    "dpi_awareness.py": (3, "#311 §3.5 fail-open per contratto: un fallimento DPI "
                            "(ctypes/windll assente, shcore mancante su Win<8.1, "
                            "awareness già impostata, API che solleva) non deve MAI "
                            "impedire l'avvio del bridge — esito testuale, mai raise"),
    "gui_utils.py": (1, "helper GUI best-effort"),
    "journal_view_gui.py": (2, "GUI Tk scheda Diario (#236): lettura ledger best-effort "
                            "(avviso invece di crash) e apertura cartella best-effort"),
    "known_teams_gui.py": (2, "GUI Tk ripulitura nomi Betfair (#282 PR 11-bis): lettura e "
                           "eliminazione best-effort (avviso invece di crash; DictionaryBusy "
                           "gestita a parte per il fail-fast durante la sync)"),
    "name_mapping_gui.py": (7, "GUI Tk mapping: render/azioni best-effort; "
                            "precompila nomi Betfair best-effort (#282 PR 11: provider "
                            "che solleva → avviso, nessun crash)"),
    "provider_gui.py": (3, "GUI Tk provider: render/azioni best-effort"),
    "reconnect_policy.py": (1, "classificazione errore di reconnect tollerante"),
    "source_chats_gui.py": (1, "GUI Tk sorgenti: best-effort"),
    "token_store.py": (5, "soft-import/fallback keyring: qualsiasi errore = backend non disponibile"),
    "tools_gui.py": (3, "GUI Tk finestra strumenti: apertura sotto-finestre best-effort"),
    "write_path.py": (2, "write-failure fail-safe: la scrittura CSV fallita non deve crashare → "
                         "rollback di coda/guardrail ed errore riportato, in commit_signal e "
                         "commit_signals (multi-riga #192)"),
    "betfair/auth_client.py": (2, "errore login safe: niente response/segreti nel messaggio; "
                                   "logout server-side best-effort: un fallimento non blocca il clear locale (#168)"),
    "betfair/auto_sync.py": (7, "ciclo auto login→sync→logout best-effort: logout/release/summary/state"),
    "betfair/credential_store.py": (6, "soft-import/fallback keyring credenziali Betfair; "
                                       "snapshot pre-save e rollback best-effort non devono "
                                       "sollevare (#259 D2: il ripristino non deve peggiorare "
                                       "uno stato già rotto)"),
    "betfair/dictionary_viewer_gui.py": (1, "GUI Tk viewer dizionario best-effort"),
    "betfair/log_safety.py": (2, "redazione log best-effort: il filtro non deve mai crashare il "
                                 "logging, e agganciare il filtro a un handler (anche via hook su "
                                 "addHandler) è best-effort (#166)"),
    "betfair/sync_engine.py": (1, "fallimento sync safe: SyncResult FAILED, niente crash/segreti"),
}


def _is_broad_name(node) -> bool:
    return isinstance(node, ast.Name) and node.id in ("Exception", "BaseException")


def _handler_is_blind(node: ast.ExceptHandler) -> bool:
    """``True`` se l'handler cattura in modo "cieco": bare ``except:``, ``except Exception``/
    ``except BaseException``, oppure un handler a **tupla** che include uno di quei due
    (``except (Exception, X):``) — altrimenti il blind-catch sfuggirebbe (Codex P2 su #232)."""
    t = node.type
    if t is None:                                       # bare `except:`
        return True
    if _is_broad_name(t):                               # except Exception / BaseException
        return True
    if isinstance(t, ast.Tuple):                        # except (Exception, X) / (BaseException, …)
        return any(_is_broad_name(e) for e in t.elts)
    return False


class _BlindExceptVisitor(ast.NodeVisitor):
    def __init__(self):
        self.count = 0

    def visit_ExceptHandler(self, node):
        if _handler_is_blind(node):
            self.count += 1
        self.generic_visit(node)


def _scan_blind_excepts():
    """Mappa modulo (relpath POSIX) → numero di blind-except, su tutto `xtrader_bridge/`."""
    counts = {}
    for dirpath, _dirs, files in os.walk(_PKG):
        if "__pycache__" in dirpath:
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            tree = ast.parse(open(path, encoding="utf-8").read())
            v = _BlindExceptVisitor()
            v.visit(tree)
            if v.count:
                rel = os.path.relpath(path, _PKG).replace(os.sep, "/")
                counts[rel] = v.count
    return counts


def test_nessun_blind_except_nuovo_o_non_motivato():
    actual = _scan_blind_excepts()
    expected = {k: v[0] for k, v in _ALLOWLIST.items()}

    # File con blind-except ma NON in allowlist → nuovo file non motivato.
    non_allowlisted = sorted(set(actual) - set(expected))
    assert not non_allowlisted, (
        "Blind-except (`except Exception`/bare `except:`) in moduli NON in allowlist: "
        f"{ {f: actual[f] for f in non_allowlisted} }. "
        "Restringili a un'eccezione specifica, oppure aggiungi il file a _ALLOWLIST con il motivo.")

    # Conteggio diverso dal baseline → aumentato (nuovo blind-except) o diminuito (stringi il baseline).
    drifted = {f: (actual.get(f, 0), expected[f]) for f in expected if actual.get(f, 0) != expected[f]}
    assert not drifted, (
        "Conteggio blind-except cambiato rispetto all'allowlist (attuale, atteso): "
        f"{drifted}. Se hai AGGIUNTO un except ampio, restringilo o motivalo aggiornando _ALLOWLIST; "
        "se ne hai RIMOSSO uno, abbassa il numero nel baseline.")


def test_allowlist_totale_coerente():
    # Il totale dell'allowlist deve coincidere con la somma per-file (nessun refuso nel baseline).
    actual = _scan_blind_excepts()
    assert sum(actual.values()) == sum(v[0] for v in _ALLOWLIST.values())


def _count_in_snippet(code: str) -> int:
    v = _BlindExceptVisitor()
    v.visit(ast.parse(code))
    return v.count


def test_rileva_handler_a_tupla_che_include_exception():
    # Codex P2 (#232): un handler a TUPLA che include Exception/BaseException è un blind-catch
    # e va contato — altrimenti `except (Exception, X):` sfuggirebbe alla guardia.
    assert _count_in_snippet("try:\n pass\nexcept (Exception, ValueError):\n pass\n") == 1
    assert _count_in_snippet("try:\n pass\nexcept (ValueError, BaseException):\n pass\n") == 1
    # bare / nome singolo restano contati
    assert _count_in_snippet("try:\n pass\nexcept Exception:\n pass\n") == 1
    assert _count_in_snippet("try:\n pass\nexcept:\n pass\n") == 1
    # tuple SOLO di eccezioni specifiche NON è cieco → non contato
    assert _count_in_snippet("try:\n pass\nexcept (ValueError, KeyError):\n pass\n") == 0
    assert _count_in_snippet("try:\n pass\nexcept ValueError:\n pass\n") == 0


def test_ogni_voce_allowlist_ha_un_motivo():
    # Ogni voce del baseline DEVE avere una motivazione non vuota (l'audit chiede una lista motivata).
    for f, (n, reason) in _ALLOWLIST.items():
        assert n > 0, f"voce baseline con conteggio non positivo: {f}"
        assert isinstance(reason, str) and reason.strip(), f"voce baseline senza motivo: {f}"
