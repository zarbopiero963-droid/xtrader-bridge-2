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
    "app.py": (28, "glue runtime/GUI Tk: teardown, callback after(), log e auto-start best-effort; "
                   "event journal best-effort (#230); refill campo token su widget Tk distrutto (PR-08c)"),
    "atomic_io.py": (1, "cleanup del temporaneo su QUALSIASI errore di scrittura/rename (BaseException)"),
    "config_store.py": (2, "backup config corrotta best-effort + rollback keyring best-effort"),
    "custom_parser_gui.py": (8, "GUI Tk del costruttore parser: render/azioni best-effort"),
    "custom_pipeline.py": (1, "id_resolver iniettato: un resolver che solleva NON blocca la riga (fail-open)"),
    "gui_utils.py": (1, "helper GUI best-effort"),
    "name_mapping_gui.py": (6, "GUI Tk mapping: render/azioni best-effort"),
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
    "betfair/credential_store.py": (4, "soft-import/fallback keyring credenziali Betfair"),
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
