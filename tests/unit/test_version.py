"""Test della versione app (PR-18/PHASE 8): unica fonte di verità + uso nella build."""

import re
from pathlib import Path

import xtrader_bridge


def test_version_definita_e_semver():
    # __version__ è l'unica fonte di verità usata da GUI e build: deve esistere ed
    # essere un MAJOR.MINOR.PATCH valido (così il nome artifact non è mai vuoto/rotto).
    ver = xtrader_bridge.__version__
    assert isinstance(ver, str) and ver
    assert re.fullmatch(r"\d+\.\d+\.\d+", ver), f"versione non semver: {ver!r}"


def test_build_workflow_usa_la_versione_dal_package():
    # La build NON deve hardcodare la versione: deve leggerla da xtrader_bridge.__version__
    # (così cambia in un solo posto). Verifichiamo che il workflow la estragga di lì.
    wf = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "build.yaml"
    text = wf.read_text(encoding="utf-8")
    assert "xtrader_bridge" in text and "__version__" in text
    # L'artifact è nominato dallo step meta (versionato), non con un nome fisso.
    assert "steps.meta.outputs.artifact" in text
    # Il file .exe interno resta a nome stabile.
    assert "XTrader-Signal-Bridge.exe" in text
    # Su windows-latest il print() di Python emette CRLF e $(...) lascia un \r:
    # la versione DEVE essere ripulita da CR/LF, altrimenti il nome artifact è
    # malformato (`...v0.1.0\r-<data>`). Verifichiamo lo strip difensivo.
    assert "tr -d '\\r\\n'" in text
