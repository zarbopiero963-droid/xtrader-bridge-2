"""P3-16 + P3-18 audit #76 — config_store.load_config: marker solo-RAM da disco e
JSON annidato patologico.

- **P3-16**: `cfg.update(data)` accettava dal FILE i marker SOLO-IN-RAM
  (`_post_corruption`, `_token_load_incomplete`) che solo `load_config` può mettere in
  base allo stato runtime reale. `save_config` non li scrive mai (li fa `pop` prima
  della scrittura): se sono nel file è manomissione — e un `_token_load_incomplete`
  fasullo trasformerebbe un clear token VOLUTO in «preserva» nel ramo CLEAR.
- **P3-18**: la tupla `except` del load non includeva `RecursionError` (subclass di
  RuntimeError, non di ValueError): un JSON annidato oltre il limite crashava
  l'avvio invece di finire nel recovery `.bak` come ogni altra corruzione.

Funzioni REALI su file tmp, nessun mock."""

import json

import pytest

from tests.unit import json_patologico
from xtrader_bridge import config_store


# ── P3-16: marker manomessi su disco scartati ────────────────────────────────────────

def test_marker_manomessi_su_disco_scartati(tmp_path):
    """FAIL-FIRST: pre-patch i marker entravano in cfg dal file manomesso."""
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"provider": "PBet",
                             "_post_corruption": True,
                             "_token_load_incomplete": True}), encoding="utf-8")

    cfg = config_store.load_config(str(p))

    assert config_store.POST_CORRUPTION_KEY not in cfg          # scartato
    assert config_store.TOKEN_LOAD_INCOMPLETE_KEY not in cfg    # scartato
    assert cfg["provider"] == "PBet"                            # il resto carica normale


def test_marker_runtime_su_file_corrotto_resta(tmp_path):
    """Regressione bloccata: lo strip vale SOLO per i valori da disco — il marker
    messo dal runtime su file davvero corrotto deve restare (issue #199)."""
    p = tmp_path / "config.json"
    p.write_text("{not json", encoding="utf-8")

    cfg = config_store.load_config(str(p))

    assert cfg.get(config_store.POST_CORRUPTION_KEY) is True    # runtime, legittimo
    assert list(tmp_path.glob("*.bak*")), "file corrotto messo in backup"


def test_save_non_persiste_mai_i_marker(tmp_path):
    """Il contratto completo: anche con i marker in RAM, il file scritto non li
    contiene (già vero prima — pinnato qui accanto allo strip in load)."""
    p = tmp_path / "config.json"
    cfg = config_store.load_config(str(p))
    cfg[config_store.POST_CORRUPTION_KEY] = True
    cfg[config_store.TOKEN_LOAD_INCOMPLETE_KEY] = True

    config_store.save_config(cfg, str(p))

    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert config_store.POST_CORRUPTION_KEY not in on_disk
    assert config_store.TOKEN_LOAD_INCOMPLETE_KEY not in on_disk


# ── P3-18: JSON annidato oltre il limite → recovery, non crash ───────────────────────

def test_json_annidato_patologico_recovery_non_crash(tmp_path):
    """FAIL-FIRST: pre-patch `json.load` sollevava RecursionError (fuori dalla tupla
    except) e l'avvio crashava; ora: backup `.bak` + default sicuri, come per ogni
    altra corruzione.

    **R5 della #211 — il difetto non era la profondità, era l'asserzione.** `3000` livelli
    non sono patologici in assoluto: lo sono *relativamente* a `sys.getrecursionlimit()`.
    Misurato, alzando il limite a 6000 smettevano di esserlo e questo test andava ROSSO —
    pur avendo `load_config` funzionato perfettamente. Un rosso senza un bug.

    La profondità resta **fissa** (`json_patologico.PROFONDITA`), per una ragione misurata e
    scritta lì: legarla al limite farebbe crescere senza tetto i frame C consumati dallo
    scanner, e su Windows sarebbe un segfault del runner. Quello che cambia è **l'asserzione**:
    l'invariante — l'avvio non crasha — si pretende sempre; il recovery (`.bak` + marker) è il
    *come*, e ha senso pretenderlo solo dove l'input è davvero ostile, cosa che
    `premessa_regge()` verifica invece di darla per scontata. Prima erano confusi, ed è per
    questo che il test andava rosso quando invece stava andando tutto bene.
    """
    p = tmp_path / "config.json"
    documento = json_patologico.json_annidato_oggetti("a")
    p.write_text(documento, encoding="utf-8")

    cfg = config_store.load_config(str(p))              # l'INVARIANTE: non deve sollevare

    assert isinstance(cfg, dict)

    if not json_patologico.premessa_regge(documento):
        # Ambiente esotico: il documento non è ostile qui, quindi non c'è alcun recovery da
        # pretendere. Lo si dice invece di fallire — e invece di tacere fingendo copertura.
        pytest.skip("questo interprete decodifica il documento: premessa di R5 non valida")

    # …e solo con la premessa verificata, il MECCANISMO di recovery.
    assert cfg.get(config_store.POST_CORRUPTION_KEY) is True    # trattato da corruzione
    assert list(tmp_path.glob("*.bak*")), "file patologico messo in backup"
    assert not p.exists() or "a" not in json.dumps(cfg)[:20]    # non caricato com'era
