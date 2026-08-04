"""B9 (#194 PR-H · #192 M5) — un file parser AVVELENATO non deve uccidere la lista.

Il difetto. Tutti i siti che leggono un parser da disco catturano
``(OSError, ValueError[, json.JSONDecodeError])``. Un file JSON ostile può però
sollevare classi che NON stanno in quella tupla, misurate su questo repo:

- ``RecursionError`` — un array annidato migliaia di livelli (``json`` decodifica
  ricorsivamente);
- ``OverflowError`` — ``{"version": Infinity}``: ``json.loads`` accetta il letterale
  ``Infinity`` per default, e ``int(float("inf"))`` esplode.

Nessuna delle due è ``ValueError``. Il risultato è che **un solo file** nella cartella
dei parser fa fallire l'intero elenco: i parser sani diventano invisibili.

Portata onesta: NON è un rischio di scommessa. Senza parser caricabile «▶ AVVIA» resta
bloccato (fail-closed) e nessuna riga raggiunge il CSV. È usabilità — più un crash della
GUI sul percorso «apri parser», che invece un messaggio d'errore lo avrebbe.

Ogni test qui asserisce DUE cose insieme: che la chiamata non esploda, **e** che il
parser sano sia ancora lì. La sola assenza di eccezione passerebbe anche su un'API che
restituisce una lista vuota — cioè sul difetto travestito.
"""

import json
import os

import pytest

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import parser_builder, parser_io, parser_manager


# ── corpus dei file ostili ───────────────────────────────────────────────────
# Tenuto come dizionario e usato via `parametrize`: quando in futuro emergerà una
# terza classe (un campo nuovo, un letterale JSON esotico), si aggiunge UNA riga qui
# e tutti i siti la esercitano — invece di ricordarsi nove test da aggiornare.
VELENI = {
    # RecursionError: json decodifica gli array ricorsivamente.
    "annidamento_profondo": '{"rules": ' + "[" * 3000 + "]" * 3000 + "}",
    # OverflowError: `Infinity` è un letterale che json.loads accetta di default,
    # e `int(float("inf"))` solleva OverflowError — non ValueError.
    "version_infinita": '{"name": "X", "rules": [], "version": Infinity}',
}


def _scrivi_veleno(dir_path, testo, nome="z_veleno.json"):
    """Depone un file ostile nella cartella dei parser e ne ritorna il path."""
    path = os.path.join(dir_path, nome)
    with open(path, "w", encoding="utf-8") as f:
        f.write(testo)
    return path


def _parser_sano(dir_path, nome="Sano", **kwargs):
    """Salva un parser valido, quello che DEVE restare visibile nonostante il veleno."""
    defn = cp.CustomParserDef(
        name=nome,
        rules=[cp.FieldRule(target="EventName", start_after="Match:", end_before="\n")],
        **kwargs,
    )
    cp.save_parser(defn, dir_path)
    return defn


@pytest.fixture
def cartella(tmp_path):
    return str(tmp_path)


# ── ① la lista dei nomi (parser_manager.available_parser_names) ──────────────

@pytest.mark.parametrize("veleno", sorted(VELENI), ids=sorted(VELENI))
def test_available_parser_names_salta_il_file_avvelenato(cartella, veleno):
    """Il sito del difetto originale: la tendina/elenco dei parser selezionabili."""
    _parser_sano(cartella)
    _scrivi_veleno(cartella, VELENI[veleno])

    nomi = parser_manager.available_parser_names(cartella)

    assert nomi == ["Sano"], "il file avvelenato ha nascosto il parser sano"


# ── ② il caricamento per nome (parser_manager._load_by_name) ─────────────────

@pytest.mark.parametrize("veleno", sorted(VELENI), ids=sorted(VELENI))
def test_load_by_name_su_file_avvelenato_e_fail_closed(cartella, veleno):
    """Chiedere PROPRIO il parser avvelenato deve dare `None` (fail-closed), non un crash.

    È il percorso del live: `load_primary_parser`/`load_all_parsers` passano di qui.
    """
    _scrivi_veleno(cartella, VELENI[veleno], nome="Veleno.json")

    assert parser_manager._load_by_name("Veleno", cartella) is None


@pytest.mark.parametrize("veleno", sorted(VELENI), ids=sorted(VELENI))
def test_load_all_parsers_non_perde_i_sani_per_un_avvelenato(cartella, veleno):
    """Contro-guardia sul runtime: un nome avvelenato in lista non azzera gli altri."""
    _parser_sano(cartella)
    _scrivi_veleno(cartella, VELENI[veleno], nome="Veleno.json")
    cfg = {"parser_list_by_chat": {"1": ["Veleno", "Sano"]}}

    caricati = parser_manager.load_all_parsers(cfg, chat_id="1", dir_path=cartella)

    assert [d.name for d in caricati] == ["Sano"]


# ── ③ l'elenco della GUI (parser_builder.saved_parsers) ──────────────────────

@pytest.mark.parametrize("veleno", sorted(VELENI), ids=sorted(VELENI))
def test_saved_parsers_ripiega_sul_nome_del_file(cartella, veleno):
    """Il pannello Parser: il file rotto compare col nome del file, i sani restano."""
    _parser_sano(cartella)
    _scrivi_veleno(cartella, VELENI[veleno])

    nomi = [it["name"] for it in parser_builder.ParserBuilder.saved_parsers(cartella)]

    assert "Sano" in nomi, "il file avvelenato ha svuotato l'elenco del pannello"
    assert "z_veleno" in nomi, "il file rotto deve restare visibile col nome del file"


# ── ④ apertura esplicita di UN parser (ParserBuilder.load + consumatore GUI) ──

@pytest.mark.parametrize("veleno", sorted(VELENI), ids=sorted(VELENI))
def test_parser_builder_load_solleva_un_errore_che_la_gui_CATTURA(cartella, veleno):
    """Regola 2-bis — il consumatore, non il sito.

    `custom_parser_gui._load_selected` avvolge `ParserBuilder.load(path)` in
    ``except (OSError, ValueError)`` per mostrare «❌ Errore caricamento». Se la load
    solleva una classe fuori da quella tupla, la GUI non mostra nulla: **crasha**.

    Qui si asserisce il contratto dal punto di vista di CHI CHIAMA, non della funzione:
    l'errore dev'essere catturabile con la tupla che il chiamante usa davvero.
    """
    path = _scrivi_veleno(cartella, VELENI[veleno])

    with pytest.raises((OSError, ValueError)):
        parser_builder.ParserBuilder.load(path)


# ── ⑤ import da un percorso qualsiasi (parser_io.import_parser) ──────────────

@pytest.mark.parametrize("veleno", sorted(VELENI), ids=sorted(VELENI))
def test_import_parser_solleva_ValueError_come_promette_il_docstring(cartella, veleno):
    """`import_parser` dichiara «Solleva ValueError se il file è corrotto». Un file
    ostile che ne solleva un'altra rompe il contratto scritto, non solo il codice."""
    sorgente = _scrivi_veleno(cartella, VELENI[veleno], nome="da_importare.json")

    with pytest.raises(ValueError):
        parser_io.import_parser(sorgente, cartella)


# ── ⑥ collisione di nome in salvataggio (custom_parser.save_parser) ──────────

@pytest.mark.parametrize("veleno", sorted(VELENI), ids=sorted(VELENI))
def test_save_parser_non_esplode_se_il_file_al_path_e_avvelenato(cartella, veleno):
    """Salvare «Sano» quando `Sano.json` sul disco è già avvelenato.

    Il controllo anti-collisione rilegge il file esistente per capire se è lo stesso
    parser: se quella rilettura esplode, l'utente non può più salvare — ed è bloccato
    proprio dall'operazione che gli permetterebbe di riparare il file rotto.
    """
    _scrivi_veleno(cartella, VELENI[veleno], nome="Sano.json")

    _parser_sano(cartella)   # deve riuscire, non sollevare

    ricaricato = parser_manager._load_by_name("Sano", cartella)
    assert ricaricato is not None and ricaricato.name == "Sano"


# ── ⑦ rinomina di un profilo di mappatura (_rename_profile_in_files) ─────────

@pytest.mark.parametrize("veleno", sorted(VELENI), ids=sorted(VELENI))
def test_rename_profilo_aggiorna_i_sani_e_salta_l_avvelenato(cartella, veleno):
    """Un file rotto non deve impedire la rinomina del profilo negli altri parser."""
    _parser_sano(cartella, nome="ConProfilo", name_mapping_profiles=["Vecchio"])
    _scrivi_veleno(cartella, VELENI[veleno])

    updated, failed = cp.rename_mapping_profile_in_files("Vecchio", "Nuovo", cartella)

    assert updated == ["ConProfilo"], f"rinomina non applicata ai sani (failed={failed})"
    assert cp.parsers_using_mapping_profile("Nuovo", cartella) == ["ConProfilo"]


# ── ⑧ chi-usa-quel-profilo (_profile_usage / _parsers_using_profile) ─────────

@pytest.mark.parametrize("veleno", sorted(VELENI), ids=sorted(VELENI))
def test_parsers_using_profile_conta_i_sani_col_veleno_in_cartella(cartella, veleno):
    """Alimenta l'avviso «questo profilo è usato da N parser» prima di eliminarlo.

    Se esplode, l'utente elimina un profilo **senza** l'avviso: ogni segnale di quei
    parser diventerebbe `MAPPING_MISSING` (scartato) senza che nessuno l'abbia detto.
    """
    _parser_sano(cartella, nome="ConProfilo", name_mapping_profiles=["Premier"])
    _scrivi_veleno(cartella, VELENI[veleno])

    assert cp.parsers_using_mapping_profile("Premier", cartella) == ["ConProfilo"]


# ── ⑨ chi-usa-quel-provider (provider_usage) ─────────────────────────────────

@pytest.mark.parametrize("veleno", sorted(VELENI), ids=sorted(VELENI))
def test_provider_usage_conta_i_sani_col_veleno_in_cartella(cartella, veleno):
    """Badge «🧩 N» dei provider (#182 PR E) e avviso prima di eliminarne uno."""
    defn = cp.CustomParserDef(
        name="ConProvider",
        rules=[
            cp.FieldRule(target="EventName", start_after="Match:", end_before="\n"),
            cp.FieldRule(target="Provider", fixed_value="AcmeTips"),
        ],
    )
    cp.save_parser(defn, cartella)
    _scrivi_veleno(cartella, VELENI[veleno])

    assert cp.provider_usage(cartella) == {"AcmeTips": ["ConProvider"]}
    assert cp.parsers_using_provider("AcmeTips", cartella) == ["ConProvider"]


# ── contro-guardie: senza veleno nulla cambia ────────────────────────────────

def test_senza_veleno_tutto_come_prima(cartella):
    """Il non-regresso che rende leggibili gli otto test sopra: senza file ostili il
    comportamento è quello di sempre. Senza questo, «passa» non distinguerebbe una
    correzione da un'API che ha smesso di leggere i file."""
    _parser_sano(cartella, nome="Uno", name_mapping_profiles=["Premier"])
    _parser_sano(cartella, nome="Due")

    assert parser_manager.available_parser_names(cartella) == ["Due", "Uno"]
    assert cp.parsers_using_mapping_profile("Premier", cartella) == ["Uno"]
    assert parser_manager._load_by_name("Uno", cartella).name == "Uno"
    assert {it["name"] for it in parser_builder.ParserBuilder.saved_parsers(cartella)} == {
        "Uno", "Due"}


def test_un_json_semplicemente_rotto_resta_gestito_come_prima(cartella):
    """Il caso già coperto prima della PR-H (JSON troncato → ValueError) non deve
    regredire: è la prova che la correzione ALLARGA e non SOSTITUISCE la gestione."""
    _parser_sano(cartella)
    _scrivi_veleno(cartella, '{"name": "Rotto", "rules": [', nome="z_rotto.json")

    assert parser_manager.available_parser_names(cartella) == ["Sano"]


def test_fuzz_strutturale_nessuna_classe_inattesa(cartella):
    """Corruzione **strutturale**: JSON sintatticamente validi, con tipi sbagliati.

    Nasce da un rilievo di GPT-5.5 sulla PR #240: il docstring di `load_parser` prometteva
    «nessun'altra classe esce da qui», ma la tupla normalizza solo le due classi misurate;
    un JSON valido con campi del tipo sbagliato potrebbe far uscire un `TypeError` dagli
    stessi chiamanti che catturano solo ``(OSError, ValueError)``.

    Il rilievo non si riproduce — `from_dict` è difensivo alla fonte, ogni campo è
    validato o coercito — ma «non si riproduce oggi» non è una garanzia finché non c'è un
    test che lo ri-misura. Questo lo ri-misura a ogni CI: se un campo NUOVO introdurrà un
    percorso non difeso, qui diventa rosso, e la frase nel docstring va riscritta.

    Copre esattamente i casi che il rilievo nominava — `version` lista/stringa non
    numerica, `rules` non lista, regole con campi di tipo errato — più tutto il resto
    dello schema.
    """
    valori = [None, True, False, 0, -1, 1.5, float("nan"), "", "x", [], [1], {}, {"a": 1},
              [[]], [{"target": []}], 12345678901234567890]
    chiavi = ["name", "description", "version", "mode", "rules", "name_mapping_profiles",
              "team_separator", "market_mapping_profiles", "sport", "source_language",
              "multi_market_enabled", "multi_selection_enabled", "multi_markets",
              "multi_selections", "conditions", "conditions_mode"]
    percorso = os.path.join(cartella, "fuzz.json")

    def _casi():
        for chiave in chiavi:
            for valore in valori:
                yield {"name": "F", "rules": [{"target": "EventName"}], chiave: valore}
        for campo in ("target", "start_after", "required", "transform", "value_map"):
            for valore in valori:
                yield {"name": "F", "rules": [{"target": "EventName", campo: valore}]}

    sfuggite, provati = [], 0
    for documento in _casi():
        with open(percorso, "w", encoding="utf-8") as f:
            json.dump(documento, f)
        provati += 1
        try:
            cp.load_parser(percorso)
        except (OSError, ValueError):
            pass                                # il contratto dichiarato: va bene
        except Exception as exc:                # noqa: BLE001 — è ciò che si sta misurando
            sfuggite.append((type(exc).__name__, str(documento)[:80]))

    assert provati >= 300, f"il fuzz si è ridotto a {provati} casi: non copre più lo schema"
    assert not sfuggite, f"classi fuori da (OSError, ValueError): {sfuggite[:5]}"


def test_il_veleno_e_davvero_veleno(cartella):
    """Guardia sul CORPUS, non sul prodotto: dimostra che questi file sollevano ancora
    qualcosa fuori da ``(OSError, ValueError)`` in `json`/`from_dict`.

    Serve perché se un domani CPython smettesse di accettare il letterale `Infinity`, o
    alzasse il limite di ricorsione, i test qui sopra diventerebbero verdi **senza
    esercitare nulla** — la peggior specie di test: uno che ha smesso di mordere e non
    lo dice. Questo lo dice.
    """
    fuori_tupla = []
    for nome, testo in VELENI.items():
        try:
            cp.CustomParserDef.from_json(testo)
        except (OSError, ValueError):
            pass
        except Exception as exc:            # noqa: BLE001 — è esattamente ciò che si misura
            fuori_tupla.append((nome, type(exc).__name__))

    assert sorted(fuori_tupla) == [
        ("annidamento_profondo", "RecursionError"),
        ("version_infinita", "OverflowError"),
    ], f"il corpus non solleva più le classi attese: {fuori_tupla}"
