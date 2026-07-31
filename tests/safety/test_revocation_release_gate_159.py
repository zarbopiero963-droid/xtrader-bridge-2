"""Test hard del **gate di release live** sulla lista di revoche (#157/#159).

Perché esiste. Il gate preesistente in `build.yaml` verifica solo che `REVOCATION_LIST_URL` non
sia il placeholder. Nel momento in cui si imposta l'URL reale quel flag diventa `False`, il gate
stampa «OK» e passa — e da lì **nessun controllo automatico** verifica che a quell'indirizzo ci sia
davvero una lista. È il buco segnalato come bloccante, indipendentemente e in accordo, da Claude
Fable 5 e Fugu Ultra sulla #159: un EXE distribuito mentre l'URL risponde 404 rende **non avviabile
il bridge di ogni cliente** — fail-closed corretto, esito disastroso.

Come è testato, e perché così. Il corpo del gate vive dentro `build.yaml` (come gli altri due gate,
per girare prima dell'install con soli import stdlib). Invece di riscriverne la logica qui — che
potrebbe divergere in silenzio da quella che gira davvero — questi test **estraggono lo script
dall'heredoc del workflow e lo eseguono**. Se qualcuno cambia il gate, questi test esercitano la
versione nuova; se qualcuno lo rimuove, diventano rossi.

L'estrazione è **testuale**, non via PyYAML: quel pacchetto non è in `requirements-dev.lock` (nota
di follow-up della #165) e importarlo qui renderebbe la suite non installabile in CI.
"""

import os

import pytest

from xtrader_bridge.licensing import revocation, revocation_client

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BUILD_YAML = os.path.join(_REPO_ROOT, ".github", "workflows", "build.yaml")

_STEP_ID = "revocation-live-gate"
_NOW = 1_700_000_000
# Seed di TEST corrispondente alla chiave pubblica incorporata (stesso delle altre suite licenza):
# serve perché il gate verifica con la chiave DI DEFAULT, come farà in release.
_TEST_SEED_HEX = "a1b2c3d4e5f60718293a4b5c6d7e8f90112233445566778899aabbccddeeff00"  # pragma: allowlist secret


def _corpi_del_gate() -> list:
    """Gli script Python del gate live, uno per job (`build`, `build-linux`), estratti dall'heredoc.

    Fail-closed sull'estrazione: se il passo sparisce o cambia forma al punto da non essere più
    riconoscibile, la lista è vuota e il test di presenza fallisce — non si passa in silenzio."""
    with open(_BUILD_YAML, encoding="utf-8") as f:
        righe = f.read().splitlines()
    corpi, i = [], 0
    while i < len(righe):
        if righe[i].strip() == f"id: {_STEP_ID}":
            # apertura heredoc → corpo → riga che contiene SOLO il terminatore
            apri = next(k for k in range(i, len(righe)) if righe[k].strip().startswith("python - <<'PY'"))
            chiudi = next(k for k in range(apri + 1, len(righe)) if righe[k].strip() == "PY")
            indent = len(righe[apri]) - len(righe[apri].lstrip())
            corpi.append("\n".join(r[indent:] if len(r) > indent else r
                                   for r in righe[apri + 1:chiudi]))
            i = chiudi
        i += 1
    return corpi


def _esegui(corpo: str) -> tuple:
    """`(exit_code, output)` eseguendo il corpo del gate. `sys.exit` diventa `SystemExit`."""
    import io
    import contextlib
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            exec(compile(corpo, "<gate-live>", "exec"), {"__name__": "__gate__"})
    except SystemExit as e:
        return (int(e.code or 0), buf.getvalue())
    return (0, buf.getvalue())


def _lista_firmata(*, now=_NOW, entries=()):
    return revocation.build_revocation_list(bytes.fromhex(_TEST_SEED_HEX), list(entries), now=now)


@pytest.fixture()
def gate(monkeypatch):
    """Il corpo del gate del job `build`, con orologio fermo e URL reale (non placeholder)."""
    corpi = _corpi_del_gate()
    assert corpi, (
        f"il passo «{_STEP_ID}» non è più in build.yaml o ha cambiato forma: senza quel gate una "
        "release può essere taggata mentre la lista di revoche non è pubblicata, e il bridge di ogni "
        "cliente non parte")
    monkeypatch.setattr(revocation_client, "REVOCATION_URL_IS_PLACEHOLDER", False)
    monkeypatch.setattr(revocation_client, "REVOCATION_LIST_URL", "https://revoche.esempio.test/l.txt")
    monkeypatch.setattr(revocation_client.time, "time", lambda: float(_NOW))
    return corpi[0]



@pytest.fixture(autouse=True)
def _chiave_deployata_e_quella_di_test(chiave_pubblica_di_test):
    """Dal 2026-07-31 il modulo porta la chiave pubblica REALE del proprietario (#12 PARTE 0).
    Questo file esercita la logica di licenza con una keypair di TEST, quindi qui la chiave
    "deployata" dev'essere quella di test: senza, si verificherebbero firme che nessun test di
    questo file può produrre. Vedi `chiave_pubblica_di_test` in tests/conftest.py."""

def test_il_gate_e_presente_in_ENTRAMBI_i_job():
    """Windows e Linux producono entrambi un artifact distribuibile: un gate su uno solo lascerebbe
    l'altra strada aperta."""
    assert len(_corpi_del_gate()) == 2, "il gate live deve esserci in `build` E in `build-linux`"


def test_lista_NON_pubblicata_blocca(gate, monkeypatch):
    """Il caso reale di oggi: l'URL risponde 404 → `fetch_signed` ritorna `None` (è già fail-safe)."""
    monkeypatch.setattr(revocation_client, "fetch_signed", lambda url, timeout=None: None)

    code, out = _esegui(gate)

    assert code == 1, f"una lista non scaricabile deve bloccare la release; output: {out}"
    assert "NON scaricabile" in out


def test_lista_pubblicata_ma_NON_verificabile_blocca(gate, monkeypatch):
    """Contenuto presente ma non firmato con la chiave incorporata: un URL dirottato, un file
    troncato o una lista firmata con un'altra chiave non devono far passare la release."""
    monkeypatch.setattr(revocation_client, "fetch_signed",
                        lambda url, timeout=None: "payload-non-firmato.spazzatura")

    code, out = _esegui(gate)

    assert code == 1 and "NON verificabile" in out, out


def test_lista_STANTIA_blocca(gate, monkeypatch):
    """Pubblicata e firmata, ma vecchia oltre la finestra: distribuire adesso significherebbe
    consegnare un EXE che si blocca appena avviato."""
    vecchia = _lista_firmata(now=_NOW - revocation_client.MAX_LIST_AGE_S - 3600)
    monkeypatch.setattr(revocation_client, "fetch_signed", lambda url, timeout=None: vecchia)

    code, out = _esegui(gate)

    assert code == 1 and "STANTIA" in out, out


def test_lista_pubblicata_fresca_e_verificabile_passa(gate, monkeypatch):
    """La controprova indispensabile: senza, tutti i test sopra passerebbero anche con un gate che
    blocca **sempre** — e nessuno potrebbe più taggare una release."""
    fresca = _lista_firmata(now=_NOW - 3600)
    monkeypatch.setattr(revocation_client, "fetch_signed", lambda url, timeout=None: fresca)

    code, out = _esegui(gate)

    assert code == 0, f"una lista pubblicata, firmata e fresca deve passare; output: {out}"
    assert "OK" in out


def test_lista_vuota_ma_valida_passa(gate, monkeypatch):
    """«Nessuno revocato» è uno stato **legittimo e frequente**: la lista firmata esiste e va
    accettata. Un gate che pretendesse entry bloccherebbe il caso normale."""
    vuota = _lista_firmata(now=_NOW - 60, entries=())
    monkeypatch.setattr(revocation_client, "fetch_signed", lambda url, timeout=None: vuota)

    code, out = _esegui(gate)

    assert code == 0, out


def test_url_placeholder_non_applicabile(gate, monkeypatch):
    """Con l'URL ancora di sviluppo non c'è niente da scaricare: competente è il gate precedente,
    e questo non deve inventarsi un fallimento (né fare rete)."""
    monkeypatch.setattr(revocation_client, "REVOCATION_URL_IS_PLACEHOLDER", True)

    def mai(url, timeout=None):
        raise AssertionError("con l'URL placeholder il gate non deve fare rete")
    monkeypatch.setattr(revocation_client, "fetch_signed", mai)

    code, out = _esegui(gate)

    assert code == 0 and "placeholder" in out.lower(), out


def test_i_due_job_eseguono_lo_STESSO_gate():
    """Windows e Linux devono applicare la stessa regola: due copie divergenti significherebbe che
    un artifact passa e l'altro no, senza che nessuno se ne accorga."""
    build, build_linux = _corpi_del_gate()
    assert build == build_linux
