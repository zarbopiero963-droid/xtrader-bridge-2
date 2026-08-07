"""Il tool degli screenshot non deve distruggere la licenza vera di chi lo lancia.

Rilievo **GPT-5.5 sulla PR #310**, e non era teorico: `app_con_licenza_di_prova.py` scriveva la
licenza di TEST dritta in `license_state.json` della cartella dati. Su una macchina con una
licenza reale — quella del proprietario — il token vero spariva, e l'app normale poi rifiutava
quello di prova perché firmato con la chiave di test. Cioè: **scattare uno screenshot
disattivava il programma**, e l'originale non era più recuperabile.

Questi test esercitano le due funzioni reali del tool, non una copia della logica.
"""

import importlib.util
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_MODULO = _ROOT / "tools" / "screenshots" / "app_con_licenza_di_prova.py"


def _carica():
    """Importa il launcher per percorso: `tools/` non è un pacchetto importabile."""
    spec = importlib.util.spec_from_file_location("app_con_licenza_di_prova", _MODULO)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture
def tool():
    return _carica()


def test_una_licenza_esistente_viene_messa_al_riparo_non_persa(tool, tmp_path):
    """Il caso che il rilievo descrive: c'è una licenza vera e il tool sta per sovrascriverla."""
    percorso = tmp_path / "license_state.json"
    percorso.write_text('{"token": "LICENZA-VERA-DEL-PROPRIETARIO", "last_seen": 1}',
                        encoding="utf-8")
    originale = percorso.read_bytes()

    backup = tool.preserva_licenza_esistente(percorso)

    assert backup, "nessun backup creato: la licenza vera verrebbe sovrascritta e persa"
    assert pathlib.Path(backup).read_bytes() == originale, \
        "il backup non contiene la licenza originale byte per byte"
    assert not percorso.exists(), \
        "la licenza vera è ancora al suo posto: il tool la sovrascriverebbe invece di spostarla"


def test_il_ripristino_rimette_esattamente_la_licenza_di_prima(tool, tmp_path):
    """Fine della sessione di scatto: quello che si ritrova dev'essere il token ORIGINALE,
    non quello di prova — altrimenti l'app resta disattivata dopo gli screenshot."""
    percorso = tmp_path / "license_state.json"
    percorso.write_text('{"token": "LICENZA-VERA-DEL-PROPRIETARIO", "last_seen": 1}',
                        encoding="utf-8")
    originale = percorso.read_bytes()

    backup = tool.preserva_licenza_esistente(percorso)
    # il launcher scrive la sua licenza di prova al posto di quella vera
    percorso.write_text('{"token": "LICENZA-DI-PROVA-FIRMATA-COL-SEED-DI-TEST", "last_seen": 2}',
                        encoding="utf-8")

    tool.ripristina_licenza(backup, percorso)

    assert percorso.read_bytes() == originale, \
        "dopo il ripristino non c'è la licenza vera: l'app resterebbe disattivata"
    assert not pathlib.Path(backup).exists(), \
        "il backup è rimasto sul disco: alla corsa dopo il tool si rifiuterebbe di partire"


def test_senza_licenza_non_crea_nessun_backup(tool, tmp_path):
    """La macchina di documentazione tipica non ha licenza: non deve nascere un file inutile
    che poi bloccherebbe la corsa successiva."""
    percorso = tmp_path / "license_state.json"

    assert tool.preserva_licenza_esistente(percorso) is None
    assert not (tmp_path / ("license_state.json" + tool.SUFFISSO_BACKUP)).exists()


def test_un_backup_gia_presente_ferma_il_tool_invece_di_sovrascriverlo(tool, tmp_path):
    """Il caso pericoloso di seconda istanza.

    Se una corsa precedente è stata uccisa prima del ripristino, il backup contiene la licenza
    VERA. Ripartire sovrascrivendolo la distruggerebbe — cioè il danno esatto da cui questa
    funzione difende, arrivato per un'altra strada. Deve fermarsi.
    """
    percorso = tmp_path / "license_state.json"
    percorso.write_text('{"token": "licenza-di-prova-rimasta", "last_seen": 2}', encoding="utf-8")
    backup = tmp_path / ("license_state.json" + tool.SUFFISSO_BACKUP)
    backup.write_text('{"token": "LICENZA-VERA-DEL-PROPRIETARIO", "last_seen": 1}',
                      encoding="utf-8")
    intatto = backup.read_bytes()

    with pytest.raises(SystemExit) as errore:
        tool.preserva_licenza_esistente(percorso)

    assert tool.SUFFISSO_BACKUP in str(errore.value), \
        "il messaggio non dice quale file rimettere a posto: inutile a chi lo legge"
    assert backup.read_bytes() == intatto, \
        "il backup con la licenza VERA è stato sovrascritto: è il danno che il tool deve evitare"


def test_il_ripristino_non_solleva_se_non_ce_niente_da_ripristinare(tool, tmp_path):
    """`ripristina_licenza` gira da `atexit`, dove un'eccezione non serve a nessuno e sporca
    l'uscita del processo."""
    percorso = tmp_path / "license_state.json"
    tool.ripristina_licenza(None, percorso)                       # nessun backup registrato
    tool.ripristina_licenza(str(tmp_path / "inesistente"), percorso)   # backup sparito
