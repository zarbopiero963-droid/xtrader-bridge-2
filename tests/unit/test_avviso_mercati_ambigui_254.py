"""#254 — il Dizionario mercati fail-closa sulle frasi ambigue senza dirlo.

`resolve_market` fa la cosa giusta: due voci che combaciano con la stessa frase ma indicano
mercati **diversi** danno `ambiguous`, e il segnale viene scartato invece di piazzare un
mercato a caso (design §5.2, fail-closed D2). Ma nessuno lo dice all'utente: il conflitto si
scopre solo da un segnale che sparisce.

È **B21 sull'altro dizionario**. La #253 ha chiuso quel silenzio sui nomi; qui era ancora
intero — e sui mercati è più facile inciamparci, perché le voci si scrivono a frasi libere
(«gg», «over 2,5», «goal») e due frasi finiscono per combaciare senza che l'utente se ne accorga
molto più facilmente di due squadre con lo stesso alias.

**La lezione della #253 è nella forma della soluzione, non solo nel fatto che esista.** Lì
l'avviso *simulava* il resolver, e in quattro giri di review sono emersi quattro modi diversi in
cui le due detection divergevano — incluso un avviso che taceva su un conflitto vivo e uno che
mandava a correggere un dizionario sano. Qui l'avviso **chiede a `resolve_market`**: costruisce
dalla voce stessa il testo minimo che la farebbe combaciare e gli domanda l'esito. Stessa
estrazione, stesso match a confini di token, stessa canonicalizzazione, stesso tier lingua.
"""

import pytest

from xtrader_bridge import market_mapping_store as mms


def _voce(frase, market_name, selection_name, *, start_after="Mercato:", end_before="\n",
          language=""):
    return {"start_after": start_after, "end_before": end_before, "phrase": frase,
            "market_type": "", "market_name": market_name, "selection_name": selection_name,
            "language": language}


# Due voci, stessa frase «gg», mercati DIVERSI: il caso della issue.
_CONFLITTO = [_voce("gg", "Entrambe le squadre a segno", "Sì"),
              _voce("gg", "1º tempo - Totale goal 0,5", "Over 0,5 goal")]


def _cfg(voci):
    return {"market_mappings": {"M": list(voci)}}


def test_254_il_conflitto_che_il_runtime_scarta_deve_essere_ANNUNCIATO():
    """Il cuore della issue, con la misura che l'ha aperta.

    Prima della correzione:

        runtime                  -> ambiguous   (segnale scartato, fail-closed)
        avvisi al load (mercati) -> NESSUNO
    """
    cfg = _cfg(_CONFLITTO)
    prof = mms.entries_for_profiles(cfg, ["M"])
    assert mms.resolve_market("Mercato: gg\n", prof).status == "ambiguous"   # il runtime scarta
    avvisi = mms.ambiguous_phrase_warnings(cfg)
    assert avvisi, "il runtime scarta il segnale e l'utente non lo sa"
    [avviso] = avvisi
    # Il messaggio deve dire COSA e DOVE, non solo che qualcosa non va: senza il profilo e la
    # frase l'utente non sa quale riga aprire.
    assert "«M»" in avviso and "«gg»" in avviso, avviso
    assert "Entrambe le squadre a segno" in avviso and "1º tempo - Totale goal 0,5" in avviso, avviso


def test_254_un_dizionario_SANO_non_viene_accusato():
    """L'altra metà, e non è meno importante: un avviso che accusa una configurazione corretta
    smette di essere letto. Due frasi diverse non sono un conflitto."""
    cfg = _cfg([_voce("gg", "Entrambe le squadre a segno", "Sì"),
                _voce("over 2,5", "Over/Under 2,5 gol", "Over 2,5 goal")])
    assert mms.ambiguous_phrase_warnings(cfg) == []


def test_254_due_voci_che_indicano_lo_STESSO_mercato_non_sono_ambigue():
    """Stessa frase su due voci che risolvono alla STESSA tupla canonica: il runtime ritorna
    `ok`, non `ambiguous` — e l'avviso deve tacere, o accuserebbe un doppione innocuo."""
    cfg = _cfg([_voce("gg", "Entrambe le squadre a segno", "Sì"),
                _voce("gg", "entrambe le squadre a segno", "sì")])   # solo case diverso
    assert mms.resolve_market("Mercato: gg\n", mms.entries_for_profiles(cfg, ["M"])).status == "ok"
    assert mms.ambiguous_phrase_warnings(cfg) == []


def test_254_delimitatori_DIVERSI_non_creano_un_falso_conflitto():
    """Due voci con la stessa frase ma delimitatori diversi non combaciano mai sullo stesso
    campo: non sono in conflitto, e l'avviso non deve inventarne uno.

    È il motivo per cui la sonda si costruisce **dai delimitatori della voce**, invece di
    cercare la frase in tutto il messaggio: cercarla ovunque è precisamente l'errore che il
    design §5.5 ha già corretto una volta sul percorso runtime."""
    cfg = _cfg([_voce("gg", "Entrambe le squadre a segno", "Sì",
                      start_after="Mercato:", end_before="\n"),
                _voce("gg", "1º tempo - Totale goal 0,5", "Over 0,5 goal",
                      start_after="Extra:", end_before="\n")])
    assert mms.ambiguous_phrase_warnings(cfg) == []


def test_254_lingue_diverse_non_sono_un_conflitto_ma_la_STESSA_lingua_si():
    """Il tier lingua (slice 5c) vale anche qui: due voci di lingue diverse sono distinguibili
    dalla lingua-fonte, quindi non sono un conflitto. Due voci della **stessa** lingua lo sono.

    È la lezione di B21 applicata: l'ambiguità dipende da **chi interroga**, quindi si prova
    ogni lingua che il dizionario stesso contiene, più il chiamante senza filtro."""
    diverse = _cfg([_voce("gg", "Entrambe le squadre a segno", "Sì", language="IT"),
                    _voce("gg", "1º tempo - Totale goal 0,5", "Over 0,5 goal", language="EN")])
    uguali = _cfg([_voce("gg", "Entrambe le squadre a segno", "Sì", language="IT"),
                   _voce("gg", "1º tempo - Totale goal 0,5", "Over 0,5 goal", language="IT")])
    prof_div = mms.entries_for_profiles(diverse, ["M"])
    # Con la lingua dichiarata il runtime risolve: il tier sceglie la voce giusta.
    assert mms.resolve_market("Mercato: gg\n", prof_div, language="IT").status == "ok"
    assert mms.resolve_market("Mercato: gg\n", prof_div, language="EN").status == "ok"
    # ...ma un parser SENZA lingua-fonte non può scegliere: quello è un conflitto vero, e va detto.
    assert mms.resolve_market("Mercato: gg\n", prof_div).status == "ambiguous"
    assert mms.ambiguous_phrase_warnings(diverse), "un parser senza lingua-fonte perde il segnale"
    assert mms.ambiguous_phrase_warnings(uguali), "stessa lingua: nessun parser può distinguerle"


def test_254_config_spazzatura_non_esplode():
    """Fail-safe: la config arriva da un file che l'utente può aver modificato a mano. Un avviso
    diagnostico non deve MAI impedire l'avvio dell'app (stesso contratto di
    `malformed_entry_warnings` e di `ambiguous_alias_warnings`)."""
    for rotta in ({"market_mappings": None}, {"market_mappings": []},
                  {"market_mappings": {"M": None}}, {"market_mappings": {"M": ["non-un-dict"]}},
                  {"market_mappings": {"M": [{}]}}, {}, None):
        assert mms.ambiguous_phrase_warnings(rotta) == []


def test_254_avvisi_deterministici_e_uno_per_conflitto():
    """Più profili → un avviso per conflitto, in ordine stabile: un log eventi che si rimescola
    a ogni avvio non si legge (stessa garanzia del gemello sui nomi)."""
    cfg = {"market_mappings": {
        "Alfa": list(_CONFLITTO),
        "Beta": [_voce("goal", "Entrambe le squadre a segno", "Sì"),
                 _voce("goal", "Over/Under 2,5 gol", "Over 2,5 goal")]}}
    avvisi = mms.ambiguous_phrase_warnings(cfg)
    assert len(avvisi) == 2, avvisi
    assert avvisi == mms.ambiguous_phrase_warnings(cfg)          # stabile fra due chiamate
    assert any("Alfa" in a for a in avvisi) and any("Beta" in a for a in avvisi)


@pytest.mark.parametrize("frase", ["gg", "GG", "  gg  "])
def test_254_il_conflitto_si_rileva_come_lo_rileva_il_RUNTIME(frase):
    """Case e spazi: il match del runtime è case-insensitive a confini di token, quindi anche
    la rilevazione deve esserlo. Se divergessero, l'avviso tacerebbe su un conflitto vivo —
    l'errore esatto trovato quattro volte sulla #253."""
    cfg = _cfg([_voce(frase, "Entrambe le squadre a segno", "Sì"),
                _voce("gg", "1º tempo - Totale goal 0,5", "Over 0,5 goal")])
    prof = mms.entries_for_profiles(cfg, ["M"])
    assert mms.resolve_market("Mercato: gg\n", prof).status == "ambiguous"
    assert mms.ambiguous_phrase_warnings(cfg), f"frase {frase!r}: il runtime scarta, l'avviso tace"
