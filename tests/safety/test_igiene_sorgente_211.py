"""#211 R2/R3/R4 — tre residui che nessun controllo automatico poteva fermare.

Il job CI `lint` è **soft-warning per scelta dichiarata** (`pyproject.toml`: *«Il job è NON
bloccante: questi strumenti segnalano, non impediscono il merge»*). È una decisione legittima
— ma significa che un import morto o una chiave duplicata **non rendono rosso niente**, e
infatti dei tre residui annotati nella #211 il 31/07 non solo nessuno era stato chiuso: gli
import morti erano **cresciuti da 2 a 5**, e uno dei nuovi l'ha lasciato la PR che chiudeva
la famiglia `OverflowError` (`import math` in `signal_queue.py`, orfano da `48f258b`).

Queste guardie girano nel job `safety`, che è **bloccante**. Non duplicano il lavoro di ruff:
lo rendono esigibile su ciò che è spedito all'utente.

Perché AST e non `ruff` in sottoprocesso: `ruff` **non** è in `requirements-dev.txt` — sta in
`requirements-lint.txt`, installato solo dal job `lint` (lo dice `test_lint_config.py`).
Un test che lo invocasse fallirebbe negli altri job, oppure si auto-skipperebbe — cioè
tacerebbe, che è il difetto che queste guardie esistono per impedire.

Il rilevatore è stato **validato contro ruff come oracolo** prima di essere adottato: sugli
stessi quattro ambiti dà gli stessi identici 5 siti. La prima stesura ne dava 22, perché
contava anche `from __future__ import annotations` — una direttiva del compilatore che non è
un nome e non può risultare «usata». Senza l'oracolo quella guardia sarebbe nata rumorosa, e
una guardia rumorosa si disattiva.
"""

import ast
import collections
import pathlib

import pytest

_RADICE = pathlib.Path(__file__).resolve().parents[2]

#: Ciò che finisce nelle mani dell'utente. `tests/` è **escluso di proposito** e il numero è
#: dichiarato qui invece di essere taciuto: al momento della scrittura contiene 23 import
#: inutilizzati, quasi tutti deliberati (fixture importate per l'effetto collaterale della
#: registrazione, ri-export, import usati solo da `monkeypatch`). Ripulirli è un lavoro a sé;
#: fingere che non ci siano — o allargare la guardia e poi metterli in allowlist — sarebbe il
#: «cap muto» che questa serie di PR sta togliendo.
AMBITI = ("xtrader_bridge", "license_manager", "tools", "main.py")


def _import_morti(percorso: pathlib.Path):
    """Nomi importati e mai riferiti nel file. Conservativo per costruzione: davanti a una
    forma che non sa decidere **tace**, perché un falso positivo qui blocca la CI di chi non
    ha sbagliato nulla.

    Tre esclusioni, ciascuna con la sua ragione:

    - `from __future__ import …` — direttiva del compilatore, non un nome (è il caso che
      separava il mio conteggio da quello di ruff: 22 contro 5);
    - `from x import *` — la provenienza dei nomi non è decidibile staticamente: sul file
      intero non si dice nulla;
    - righe con `noqa` — la soppressione è già una dichiarazione esplicita di chi ha scritto.

    Le stringhe costanti contano come uso: coprono `__all__` e le annotazioni-stringa, dove il
    nome compare come testo e non come `ast.Name`.
    """
    src = percorso.read_text(encoding="utf-8")
    righe = src.splitlines()
    albero = ast.parse(src)

    legati = {}
    for n in ast.walk(albero):
        if not isinstance(n, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(n, ast.ImportFrom):
            if n.module == "__future__":
                continue
            if any(a.name == "*" for a in n.names):
                return []
        riga = righe[n.lineno - 1] if n.lineno <= len(righe) else ""
        if "noqa" in riga.lower():
            continue
        for a in n.names:
            legati[a.asname or a.name.split(".")[0]] = n.lineno

    usati = set()
    for n in ast.walk(albero):
        if isinstance(n, ast.Name):
            usati.add(n.id)
        elif isinstance(n, ast.Attribute):
            radice = n
            while isinstance(radice, ast.Attribute):
                radice = radice.value
            if isinstance(radice, ast.Name):
                usati.add(radice.id)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            usati.add(n.value)

    try:
        etichetta = str(percorso.relative_to(_RADICE))
    except ValueError:                      # file fuori dal repo (le contro-guardie)
        etichetta = str(percorso)
    return [(etichetta, r, nome)
            for nome, r in sorted(legati.items(), key=lambda kv: kv[1]) if nome not in usati]


def _sorgenti(ambiti=AMBITI):
    for a in ambiti:
        p = _RADICE / a
        if p.is_file():
            yield p
        else:
            yield from sorted(p.rglob("*.py"))


def test_211_R2_nessun_import_morto_nel_codice_spedito():
    """Un import morto non è solo rumore: è la **traccia di un refactor lasciato a metà**, e
    finché resta nessuno sa se il modulo doveva usare quel simbolo o no.

    È il caso di `custom_pipeline.numbers_re`, che il `CLAUDE.md` cita per nome nella Regola 3
    come una delle fonti duplicate da cui nacque il bug B17. L'import c'era, l'uso no.
    """
    morti = [m for f in _sorgenti() for m in _import_morti(f)]

    assert morti == [], (
        "import mai usati nel codice spedito:\n  "
        + "\n  ".join(f"{f}:{r} → {k}" for f, r, k in morti)
        + "\n\nRimuovilo, oppure — se il modulo DOVEVA usarlo — usalo: un import morto è la "
          "traccia di un refactor a metà, e taciuto diventa indistinguibile da una svista.")


def test_211_il_rilevatore_di_import_morti_VEDE_davvero(tmp_path):
    """Contro-guardia: un rilevatore che non trova nulla è indistinguibile da uno rotto."""
    f = tmp_path / "esempio.py"
    f.write_text("from __future__ import annotations\n"
                 "import os\n"
                 "import sys\n\n\n"
                 "def f():\n"
                 "    return os.sep\n", encoding="utf-8")

    morti = _import_morti(f)

    assert len(morti) == 1, morti
    assert morti[0][2] == "sys", morti      # `os` è usato, `annotations` non è un nome


@pytest.mark.parametrize("sorgente,atteso", [
    ("import os  # noqa: F401\n", 0),                       # soppressione esplicita: si rispetta
    ("from os import *\n", 0),                              # non decidibile: si tace
    ("from __future__ import annotations\n", 0),            # direttiva, non un nome
    ("import os\nA = ['os']\n", 0),                         # citato come stringa (__all__)
    ("import os as _o\n", 1),                               # alias non usato: si vede
])
def test_211_il_rilevatore_e_conservativo_dove_deve(sorgente, atteso, tmp_path):
    """Le forme su cui un rilevatore ingenuo sbaglia. Ognuna qui è una scelta, non un caso:
    davanti all'indecidibile la guardia tace, perché bloccare la CI di chi non ha sbagliato
    è il modo più rapido per far disattivare una guardia."""
    f = tmp_path / "caso.py"
    f.write_text(sorgente, encoding="utf-8")

    assert len(_import_morti(f)) == atteso, _import_morti(f)


def _chiavi_duplicate(percorso: pathlib.Path):
    """Chiavi stringa ripetute dentro uno stesso dict letterale, con le righe."""
    albero = ast.parse(percorso.read_text(encoding="utf-8"))
    fuori = []
    for n in ast.walk(albero):
        if not isinstance(n, ast.Dict):
            continue
        coppie = [(k.value, k.lineno) for k in n.keys
                  if isinstance(k, ast.Constant) and isinstance(k.value, str)]
        conta = collections.Counter(k for k, _ in coppie)
        for chiave, quante in conta.items():
            if quante > 1:
                fuori.append((chiave, [r for k, r in coppie if k == chiave]))
    return fuori


def test_211_R3_nessuna_chiave_di_traduzione_ripetuta():
    """La trappola: in un dict letterale **l'ultima chiave vince, in silenzio**. Chi domani
    modifica la prima occorrenza vedrà la modifica non avere alcun effetto, e non c'è nulla
    che glielo dica — nessun errore, nessun avviso, la traduzione semplicemente resta com'era.

    Il controllo va fatto sul **sorgente** e non sul dizionario costruito: lì il duplicato è
    invisibile per definizione, perché è già stato risolto dall'interprete. È la ragione per
    cui questa guardia è AST e non un `assert` sul catalogo caricato.

    Oggi i valori delle dieci coppie coincidono, quindi non c'è drift **ancora**: è una
    trappola armata, non un danno in corso.
    """
    dup = _chiavi_duplicate(_RADICE / "xtrader_bridge" / "i18n.py")

    assert dup == [], (
        "chiavi ripetute nello stesso dict di traduzione (l'ultima vince in silenzio):\n  "
        + "\n  ".join(f"{k!r} alle righe {r}" for k, r in dup))


def test_211_il_rilevatore_di_duplicati_VEDE_davvero(tmp_path):
    """Contro-guardia della precedente, e non è teorica: una guardia che leggesse il dict
    **costruito** invece del sorgente passerebbe sempre, perché lì il duplicato non esiste
    più. Qui si costruisce il caso e si pretende che venga trovato."""
    f = tmp_path / "cat.py"
    f.write_text('T = {"a": "uno", "b": "due", "a": "uno"}\n', encoding="utf-8")

    dup = _chiavi_duplicate(f)

    assert len(dup) == 1 and dup[0][0] == "a", dup
    # ...e la controprova che il dict costruito NON lo mostra:
    spazio = {}
    exec(f.read_text(encoding="utf-8"), spazio)          # noqa: S102 - sorgente scritto qui sopra
    assert len(spazio["T"]) == 2, "il duplicato è già sparito nel dict costruito"


#: Le dieci chiavi che erano duplicate e di cui questa PR ha rimosso la seconda occorrenza,
#: con la traduzione che DEVE restare. Pinnate verbatim: se una rimozione futura togliesse
#: quella sbagliata, o se qualcuno cancellasse la superstite credendola l'inutile, la GUI
#: tornerebbe in italiano per un utente inglese o spagnolo — e nessuno se ne accorgerebbe,
#: perché `tr()` è fail-safe e restituisce la chiave italiana senza dire nulla.
CHIAVI_EX_DUPLICATE = {
    "Sport": {"EN": "Sport", "ES": "Deporte"},
    "🔄 Aggiorna": {"EN": "🔄 Refresh", "ES": "🔄 Actualizar"},
    "🗑 Elimina": {"EN": "🗑 Delete", "ES": "🗑 Eliminar"},
    "Eliminazione annullata.": {"EN": "Deletion cancelled.", "ES": "Eliminación cancelada."},
    "⏳ Dizionario occupato: riprova tra poco.": {
        "EN": "⏳ Dictionary busy: try again shortly.",
        "ES": "⏳ Diccionario ocupado: reinténtalo en breve."},
}


def test_211_le_chiavi_ex_duplicate_traducono_ancora():
    """Rilievo Claude Fable 5 sulla PR #280, ed era fondato.

    La neutralità della rimozione era **misurata** (`_CATALOG` identico prima e dopo, EN 469
    voci ed ES 476) ma **scritta solo nel corpo della PR**: nessun test la teneva. Cioè
    un'affermazione vera che nessuna guardia difende — esattamente il difetto che questa serie
    di PR sta togliendo dal repository.

    Non si pinnano i **conteggi** (469/476): si romperebbero a ogni traduzione nuova e
    legittima, e una guardia che dà rosso sul lavoro corretto viene disattivata. Si pinnano le
    **dieci chiavi toccate**, che è ciò che il rilievo teme davvero: una regressione silenziosa
    di traduzioni GUI.

    Silenziosa alla lettera: `tr()` è fail-safe e su una chiave mancante restituisce la
    stringa italiana. L'utente inglese vedrebbe «🗑 Elimina» al posto di «🗑 Delete» senza che
    nulla vada storto nel programma.
    """
    from xtrader_bridge import i18n

    originale = i18n.get_language()
    try:
        for chiave, attese in CHIAVI_EX_DUPLICATE.items():
            for lingua, atteso in attese.items():
                i18n.set_language(lingua)
                assert i18n.tr(chiave) == atteso, (
                    f"{lingua}: {chiave!r} → {i18n.tr(chiave)!r}, atteso {atteso!r}. "
                    "Una rimozione ha tolto la chiave superstite invece del duplicato: "
                    "l'utente vedrebbe l'italiano senza alcun errore.")
    finally:
        i18n.set_language(originale)


def test_211_italiano_resta_il_riferimento_senza_catalogo():
    """Contro-guardia: in italiano `tr()` deve restituire la chiave **così com'è**, senza
    passare dal catalogo. Senza questa, un test che confronta stringhe uguali passerebbe
    anche se il catalogo italiano non esistesse — o se ne nascesse uno per sbaglio."""
    from xtrader_bridge import i18n

    originale = i18n.get_language()
    try:
        i18n.set_language("IT")
        for chiave in CHIAVI_EX_DUPLICATE:
            assert i18n.tr(chiave) == chiave, chiave
        assert "IT" not in i18n._CATALOG, "l'italiano è il riferimento: non ha un catalogo"
    finally:
        i18n.set_language(originale)
