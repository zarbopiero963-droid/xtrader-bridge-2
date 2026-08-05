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


# ── Il reporting deve dire il vero quanto la detection ──────────────────────
#
# Rilievo di GPT-5.5 e Fable 5, indipendentemente, sulla #255: la detection chiedeva al
# runtime, ma l'elenco dei mercati in conflitto lo ricostruiva confrontando le frasi come
# STRINGHE. Due difetti opposti dalla stessa causa — ed è la classe corretta quattro volte
# sulla #253, reintrodotta proprio nella PR che ne documenta la lezione.

def test_255_frasi_equivalenti_per_CASE_devono_comparire_ENTRAMBE():
    """Il runtime combacia case-insensitive, il reporting confrontava `==` dopo `strip()`.

    Misurato prima della correzione, con voci «GG» e «gg» verso mercati diversi:

        «...frase «GG»: combacia con 1 mercati diversi («Entrambe le squadre a segno»)...»

    Un mercato solo, e un «1 mercati diversi» che non significa niente: l'avviso manda
    l'operatore alla riga sbagliata proprio nel conflitto che dovrebbe spiegare."""
    cfg = _cfg([_voce("GG", "Entrambe le squadre a segno", "Sì"),
                _voce("gg", "1º tempo - Totale goal 0,5", "Over 0,5 goal")])
    assert mms.resolve_market("Mercato: gg\n", mms.entries_for_profiles(cfg, ["M"])).status == "ambiguous"
    [avviso] = mms.ambiguous_phrase_warnings(cfg)
    assert "Entrambe le squadre a segno" in avviso, avviso
    assert "1º tempo - Totale goal 0,5" in avviso, avviso
    assert "1 coppie" not in avviso, avviso


def test_255_una_voce_SANA_con_altri_delimitatori_non_va_elencata_come_contendente():
    """L'altra metà dello stesso difetto (Fable 5): due voci in conflitto sulla frase «gg»,
    più una terza con la STESSA frase ma delimitatori diversi — che con loro non combacia mai.

    Elencarla fra i contendenti accuserebbe una riga sana, mandando a «correggere» ciò che
    funziona. Il reporting deve chiedere al runtime **quali voci hanno davvero combaciato con
    questa sonda**, non quali condividono il testo della frase."""
    cfg = _cfg([_voce("gg", "Entrambe le squadre a segno", "Sì"),
                _voce("gg", "1º tempo - Totale goal 0,5", "Over 0,5 goal"),
                _voce("gg", "Over/Under 2,5 gol", "Over 2,5 goal",
                      start_after="Extra:", end_before="\n")])
    avvisi = mms.ambiguous_phrase_warnings(cfg)
    assert avvisi, "il conflitto vero c'è ancora"
    testo = " ".join(avvisi)
    assert "Entrambe le squadre a segno" in testo and "1º tempo - Totale goal 0,5" in testo, testo
    assert "Over/Under 2,5 gol" not in testo, f"accusa una voce sana: {testo}"


def test_255_oltre_il_tetto_il_controllo_si_FERMA_e_lo_dice(monkeypatch):
    """Il costo cresce col quadrato delle voci, e oltre ~512 frasi distinte la cache dei regex
    compilati di `_phrase_in_text` va in thrashing. Misurato allo START:

        100 voci 0,09 s · 300 voci 0,70 s · 400 voci 1,2 s · **800 voci 54 s**

    Un minuto di finestra bloccata all'avvio sarebbe un danno peggiore del difetto che questo
    avviso diagnostica — la stessa trappola della #253, dove la diagnostica corretta costava
    48 s allo START.

    Il tetto **non è silenzioso**: un cap che tace si legge come «nessun conflitto», che è
    esattamente la bugia da evitare in una diagnostica di sicurezza.

    **Si conta il lavoro, non i secondi** (rilievo GPT-5.5 e Fable 5): un'asserzione a orologio
    è flaky su un runner Windows condiviso, e per giunta misura la cosa sbagliata. Contare le
    chiamate a `resolve_market` è deterministico e dice di più — che oltre il tetto il lavoro
    è **zero**, non solo veloce."""
    chiamate = []
    reale = mms.resolve_market
    monkeypatch.setattr(mms, "resolve_market",
                        lambda *a, **k: (chiamate.append(1), reale(*a, **k))[1])

    def _molte(n):
        return [_voce(f"frase{i}", "Entrambe le squadre a segno", "Sì") for i in range(n)]

    sotto = _cfg(_molte(mms._MAX_VOCI_CONTROLLO_AMBIGUITA))
    assert mms.ambiguous_phrase_warnings(sotto) == []       # sotto il tetto: controllo eseguito
    assert chiamate, "sotto il tetto il controllo non ha interrogato il runtime"
    sotto_il_tetto = len(chiamate)

    chiamate.clear()
    sopra = _cfg(_molte(mms._MAX_VOCI_CONTROLLO_AMBIGUITA + 1))
    [avviso] = mms.ambiguous_phrase_warnings(sopra)
    assert chiamate == [], f"oltre il tetto ha comunque lavorato: {len(chiamate)} chiamate"
    assert "oltre il tetto" in avviso and "NON eseguito" in avviso, avviso
    assert str(mms._MAX_VOCI_CONTROLLO_AMBIGUITA) in avviso, avviso
    # E sotto il tetto il lavoro resta lineare nelle sonde, non esplosivo: una risoluzione per
    # voce (le sonde duplicate sono deduplicate, e il ciclo dei contendenti parte solo sui
    # conflitti veri — qui non ce ne sono).
    assert sotto_il_tetto <= mms._MAX_VOCI_CONTROLLO_AMBIGUITA, sotto_il_tetto


def test_255_selezioni_OPPOSTE_dello_stesso_mercato_compaiono_entrambe():
    """Over e Under dello stesso mercato: due tuple canoniche diverse, quindi un conflitto vero.

    Il difetto misurato prima della correzione — l'elenco dei contendenti deduplicava per
    `market_name` invece che per la tupla `(tipo, mercato, selezione)`:

        «...combacia con 1 mercati diversi («Over/Under 2,5 gol»)...»

    Un mercato solo per un conflitto fra i **due lati opposti della scommessa**, e nessun modo
    per l'operatore di capire quale delle due righe togliere. È il caso più pericoloso del
    dizionario mercati: piazzare Over invece di Under non è un segnale perso, è la scommessa
    contraria.

    Qui si pretende che il messaggio nomini **entrambe** le selezioni, e che il conteggio dica
    `2` — il che richiede anche il wording «coppie mercato/selezione», perché «2 mercati» con un
    solo nome di mercato elencato due volte sembrerebbe un errore dell'avviso."""
    cfg = _cfg([_voce("o25", "Over/Under 2,5 gol", "Over 2,5 goal"),
                _voce("o25", "Over/Under 2,5 gol", "Under 2,5 goal")])
    prof = mms.entries_for_profiles(cfg, ["M"])
    assert mms.resolve_market("Mercato: o25\n", prof).status == "ambiguous"   # il runtime scarta
    [avviso] = mms.ambiguous_phrase_warnings(cfg)
    assert "Over 2,5 goal" in avviso, avviso
    assert "Under 2,5 goal" in avviso, avviso
    assert "2 coppie" in avviso, avviso


def test_255_conflitti_su_frasi_DIVERSE_non_collassano_in_un_solo_avviso():
    """Due frasi distinte in conflitto sugli **stessi** due mercati sono due righe diverse da
    correggere, quindi due avvisi.

    La chiave di dedup non includeva la sonda, solo `(profilo, contendenti)`. Misurato su una
    config con 150 conflitti distinti: **1 avviso**, 149 nascosti. Una diagnostica che ne mostra
    uno su 150 è peggio di nessuna, perché chi legge crede di aver visto il problema — è la
    stessa classe «il reporting dice meno della detection» corretta quattro volte sulla #253.

    Qui in piccolo e deterministico: tre frasi, tre avvisi, uno per frase."""
    frasi = ("gg", "goal", "segnano")
    cfg = _cfg([v for f in frasi
                for v in (_voce(f, "Entrambe le squadre a segno", "Sì"),
                          _voce(f, "1º tempo - Totale goal 0,5", "Over 0,5 goal"))])
    avvisi = mms.ambiguous_phrase_warnings(cfg)
    assert len(avvisi) == len(frasi), avvisi
    for f in frasi:
        assert any(f"«{f}»" in a for a in avvisi), f"conflitto sulla frase «{f}» nascosto: {avvisi}"


def test_255_ogni_esito_ok_porta_le_TRE_chiavi_canoniche():
    """Contratto di `resolve_market`: un esito `ok` ha SEMPRE `market_type`, `market_name` e
    `selection_name`.

    `ambiguous_phrase_warnings` ci accede diretto (`m["market_type"]`) per costruire la tupla
    canonica, e due reviewer (GPT-5.5 e Fugu Ultra) hanno chiesto se un `ok` potesse arrivare
    senza una di quelle chiavi → `KeyError` allo START, cioè l'avvio dell'app rotto da una
    diagnostica. Leggendo il codice non è raggiungibile: c'è **un solo** `return` con
    `status="ok"` e costruisce il dict come letterale con le tre chiavi.

    Ma «vero per costruzione» dura finché qualcuno non aggiunge un secondo `return`. Questo test
    lo àncora: se un domani nascesse un percorso `ok` con un dict parziale, fallisce qui invece
    di far esplodere lo START. Si prova su mercati diversi, con e senza `market_type` esplicito
    nella voce di config, e con e senza filtro-lingua."""
    casi = [
        (_voce("gg", "Entrambe le squadre a segno", "Sì"), "Mercato: gg\n", None),
        (_voce("o25", "Over/Under 2,5 gol", "Under 2,5 goal"), "Mercato: o25\n", None),
        (_voce("gg", "Entrambe le squadre a segno", "Sì", language="IT"), "Mercato: gg\n", "IT"),
    ]
    for voce, testo, lingua in casi:
        # anche con un `market_type` grezzo stantio nella voce: il canonico lo ricalcola
        voce = dict(voce, market_type="MERCATO_INESISTENTE")
        esito = mms.resolve_market(testo, mms.entries_for_profiles(_cfg([voce]), ["M"]),
                                   language=lingua)
        assert esito.status == "ok", (voce, esito)
        assert set(esito.market) >= {"market_type", "market_name", "selection_name"}, esito.market
        # e i valori sono stringhe utilizzabili, non `None`: il CSV non deve mai vedere un None
        for chiave in ("market_type", "market_name", "selection_name"):
            assert isinstance(esito.market[chiave], str), (chiave, esito.market)
        assert esito.market["market_name"] and esito.market["selection_name"], esito.market


def test_255_sonde_identiche_non_vengono_risondate():
    """La protezione contro il caso «300 voci tutte in conflitto sulla stessa frase» esiste e
    sta PRIMA del ciclo costoso (rilievo Fable 5): sonde identiche si interrogano una volta
    sola. Misurato: 300 voci con la stessa frase → 0,074 s, contro 0,94 s con frasi tutte
    diverse. Qui la stessa cosa contata invece che cronometrata."""
    chiamate = []
    reale = mms.resolve_market
    from unittest import mock
    with mock.patch.object(mms, "resolve_market",
                           side_effect=lambda *a, **k: (chiamate.append(1), reale(*a, **k))[1]):
        # 50 voci, UNA sola frase: una sonda sola da provare.
        voci = [_voce("gg", "Entrambe le squadre a segno", "Sì") for _ in range(50)]
        mms.ambiguous_phrase_warnings(_cfg(voci))
    assert len(chiamate) <= 2, f"sonde identiche risondate {len(chiamate)} volte"
