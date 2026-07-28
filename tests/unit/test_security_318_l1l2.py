"""Test hard #318 — L2-2 (`_is_placeholder` permissivo).

Esercitano il codice reale:
- L2-2: `value_maps._is_placeholder` usa ora `or` (non `and`): un placeholder PARZIALE/troncato
  è comunque escluso dalla value-map (fail-closed).

Nota (P3-15 #76): i test L1-4 (anti-ReDoS del parser P.Bet hardcoded) vivevano in questo
file e sono stati RIMOSSI insieme al modulo `xtrader_bridge/parser.py` (decisione del
proprietario: rimozione, il modulo era fuori dal flusso live da CP-09b). La guardia
anti-reintroduzione è in `tests/unit/test_pbet_removed_76.py`.
"""

import pytest

from xtrader_bridge import custom_parser_engine, source_manager, transforms
from xtrader_bridge import value_maps as vm

# Cifre non-ASCII che `\d` matcha e che i costruttori Python convertono senza batter ciglio:
# `int("٢") == 2`, `float("١٩") == 19.0`. Sono raggiungibili da un vero messaggio Telegram.
ARABO_INDIANE = "٢-٠"      # U+0662, U+0660
FULLWIDTH = "１-０"          # U+FF11, U+FF10


# ── L2-2: `_is_placeholder` fail-closed (`or`, non `and`) ──────────────────────

def test_is_placeholder_riconosce_anche_i_parziali():
    assert vm._is_placeholder("{HOME_TEAM}") is True    # completo
    assert vm._is_placeholder("{HOME_TEAM") is True     # troncato: manca `}` → ora RICONOSCIUTO
    assert vm._is_placeholder("HOME_TEAM}") is True      # manca `{` → riconosciuto
    assert vm._is_placeholder("Milan") is False          # valore reale
    assert vm._is_placeholder("") is False
    assert vm._is_placeholder(None) is False


def test_value_map_esclude_placeholder_parziale():
    # Un valore col placeholder PARZIALE non deve entrare nella value-map come valore reale.
    m = vm.value_map_from_pairs([("gg", "Goal/Goal"), ("bad", "{HOME_TEAM"), ("ok", "Milan")])
    assert m.get("gg") == "Goal/Goal"
    assert m.get("ok") == "Milan"
    # `value_map_from_pairs` non filtra i placeholder (lo fa il chiamante via `_is_placeholder`):
    # qui verifichiamo che, filtrando come in produzione, il parziale sparisce.
    pairs = [("gg", "Goal/Goal"), ("bad", "{HOME_TEAM"), ("ok", "Milan")]
    filtered = vm.value_map_from_pairs([(a, v) for a, v in pairs if not vm._is_placeholder(v)])
    assert "bad" not in filtered and filtered.get("gg") == "Goal/Goal"


# ── L2-1 residuo (#166 P3-cp1): le regex scritte a mano rimaste fuori dal fix #318 ─────────────
# Il fix #318 aveva chiuso il fail-open sostituendo `\d` con `[0-9]` nella fonte unica
# `numbers_re.DECIMAL`, coprendo validator / custom_pipeline / csv_writer / parser. Tre regex
# però sono scritte a mano e non compongono da lì: due sui PUNTEGGI e una sul CHAT_ID. Erano
# rimaste indietro, e non in modo innocuo — vedi i tre test qui sotto.

def test_i_punteggi_non_ascii_non_generano_una_selezione_piazzabile():
    """Il caso più grave: `extract_scores` NORMALIZZA al formato del dizionario XTrader, quindi
    «٢-٠» usciva come «2 - 0» — una selezione Correct Score valida e **piazzabile**, da un
    messaggio che la stringa «2-0» non la contiene affatto.

    Fail-closed: un punteggio deve essere scritto in cifre ASCII o non è un punteggio."""
    assert custom_parser_engine.extract_scores("Risultati: 2-0") == ["2 - 0"]
    assert custom_parser_engine.extract_scores(f"Risultati: {ARABO_INDIANE}") == []
    assert custom_parser_engine.extract_scores(f"Risultati: {FULLWIDTH}") == []


def test_la_linea_over_non_nasce_da_cifre_non_ascii():
    """Stessa radice sul secondo consumer: `score_to_over` somma i gol e produce la linea Over
    che finisce nel CSV. «٦-٠» dava «Over 6,5» — una linea inventata."""
    assert transforms.apply("6-0", "score_to_over") == "Over 6,5"
    assert transforms.apply("٦-٠", "score_to_over") == ""
    assert transforms.apply("６-０", "score_to_over") == ""


def test_un_chat_id_non_ascii_non_e_un_chat_id_valido():
    """`is_valid_chat_id` esiste per impedire la sorgente «configurata ma morta» (P3-29 #76):
    un valore che passa la validazione ma non combacia mai con l'`effective_chat.id` runtime.

    Con `\\d` accettava «١٢٣٤٥٦٧٨٩», che è esattamente quel caso — la regex ricreava il bug che
    era stata scritta per prevenire."""
    assert source_manager.is_valid_chat_id("-1001234567890") is True
    assert source_manager.is_valid_chat_id("123456789") is True
    assert source_manager.is_valid_chat_id("١٢٣٤٥٦٧٨٩") is False
    assert source_manager.is_valid_chat_id("１２３４５６７８９") is False


@pytest.mark.parametrize("testo,atteso", [
    ("1-0", ["1 - 0"]),
    ("1–0", ["1 - 0"]),                    # EN DASH (#76 P3-13: tastiere iOS)
    ("01 - 0", ["1 - 0"]),                 # zeri iniziali rimossi
    ("1-0, 2-1", ["1 - 0", "2 - 1"]),      # lista
    ("100-1", []),                         # numero più lungo → non è un punteggio
    ("0-0.5", []),                         # handicap decimale (#341)
    ("0-0,5", []),                         # idem, virgola italiana
    ("3\n- 0", []),                        # cifre di righe adiacenti non si fondono
])
def test_i_punteggi_ascii_legittimi_restano_invariati(testo, atteso):
    """Nessuna regressione: tutte le forme che il parser già supportava — e tutte quelle che già
    rifiutava — devono comportarsi esattamente come prima. Il fix restringe l'alfabeto delle
    cifre, non la grammatica dei punteggi."""
    assert custom_parser_engine.extract_scores(testo) == atteso


def test_i_confini_restano_unicode_di_proposito():
    """Asimmetria deliberata: il CORPO della regex accetta solo `[0-9]`, ma i lookaround
    `(?<!\\d)`/`(?!\\d)` restano Unicode.

    Motivo: una cifra non-ASCII **adiacente** significa che quel «2» fa parte di un numero più
    lungo e scritto in modo misto — quindi il match va rifiutato, non accettato. Restringere
    anche i confini a `[0-9]` li renderebbe più PERMISSIVI, non più severi: «١2-0» tornerebbe a
    produrre «2 - 0». Le due scelte puntano nella stessa direzione fail-closed."""
    assert custom_parser_engine.extract_scores("١2-0") == []
    assert custom_parser_engine.extract_scores("2-0١") == []


def test_chat_id_a_cifre_miste_rifiutato_per_intero():
    """Sanity check chiesto da Fugu Ultra (#167): la validazione deve ancorare l'INTERO valore.

    `is_valid_chat_id` usa `fullmatch`, quindi «12٣» non passa per il prefisso ASCII «12». Se
    un domani diventasse `match`, un id misto verrebbe accettato sulla sola parte iniziale e
    tornerebbe la sorgente morta."""
    for misto in ("12٣", "١2", "-100١", "12 3"):
        assert source_manager.is_valid_chat_id(misto) is False, misto


def test_una_config_esistente_con_chat_id_non_ascii_da_un_errore_esplicito():
    """Migrazione (rilievo GPT-5.5 #167): chi ha già in config una chat con cifre non-ASCII non
    deve trovarsi la sorgente rifiutata *in silenzio*.

    La validazione produce un errore che NOMINA il valore e dice cosa usare al suo posto: il fix
    trasforma una morte silenziosa in un messaggio azionabile — che è il punto, visto che prima
    quella sorgente risultava «configurata» e non riceveva nulla."""
    errori = source_manager.validate_sources(
        [{"chat_id": "١٢٣٤٥٦٧٨٩", "name": "Canale", "mode": "PRE"}])
    testo = " ".join(errori)
    assert "chat_id non numerico" in testo
    assert "١٢٣٤٥٦٧٨٩" in testo          # nomina il valore colpevole
    assert "-1001234567890" in testo      # e mostra la forma corretta


def test_il_normalizzatore_migliaia_resta_scartato_a_valle():
    """Il secondo sanity check di Fugu: `custom_pipeline._decimal_sep_to_point` accetta cifre
    non-ASCII (usa `\\d` e `str.isdigit()`, entrambi Unicode) e NON è stato toccato in questo fix.

    La ragione è qui, eseguibile invece che affermata in un commento: il validatore a valle usa
    `numbers_re.SIGNED_DECIMAL` (`[0-9]`) e scarta comunque il risultato, quindi cambiarlo non
    modificherebbe alcun comportamento osservabile. Se un domani quel confine si spostasse,
    questo test diventa rosso e la decisione va rivista."""
    import re

    from xtrader_bridge import numbers_re
    from xtrader_bridge.custom_pipeline import _decimal_sep_to_point

    uscita = _decimal_sep_to_point("١.٢٣٤,٥٦")
    assert uscita == "١٢٣٤.٥٦"            # normalizza, come per gli ASCII
    accettato = re.compile(r"^" + numbers_re.SIGNED_DECIMAL + r"$").fullmatch(uscita)
    assert accettato is None, "il validatore deve continuare a scartarlo: è ciò che rende innocua la non-modifica"
