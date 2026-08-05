"""#256 punto 2 — il tetto anti-costo era per PROFILO, non globale.

`ambiguous_phrase_warnings` si fermava a 300 voci **per profilo**, ma nulla limitava il totale:
N profili al tetto sommavano il costo allo START, e il costo è lineare nelle voci esaminate
(~2,2 ms l'una, misurato). Con profili tutti al tetto:

    1 profilo  =  300 voci ->  0,66 s ·  150 avvisi
    3 profili  =  900 voci ->  1,92 s ·  450 avvisi
    5 profili  = 1500 voci ->  3,31 s ·  750 avvisi
    8 profili  = 2400 voci ->  5,39 s · 1200 avvisi

**Due problemi distinti, non uno.** Il tempo è quello ovvio; l'altro è che 1200 avvisi nel log
non si leggono — e un avviso che non si legge non informa nessuno, cioè fallisce esattamente
come il silenzio che la #254 aveva tolto. Perciò i tetti sono due: uno sul **lavoro** e uno sugli
**avvisi**.

Entrambi **dichiarati, mai silenziosi**: è la regola stabilita dalla #254 e ribadita dalla #255 —
un cap che tace si legge come «nessun conflitto», che è la bugia da evitare.
"""

from xtrader_bridge import market_mapping_store as mms


def _voce(frase, mn="Entrambe le squadre a segno", sn="Sì"):
    return {"start_after": "Mercato:", "end_before": "\n", "phrase": frase,
            "market_type": "", "market_name": mn, "selection_name": sn, "language": ""}


def _profilo_in_conflitto(prefisso, n_coppie):
    """Profilo con `n_coppie` conflitti reali (due voci stessa frase, mercati diversi)."""
    voci = []
    for i in range(n_coppie):
        voci.append(_voce(f"{prefisso}{i}"))
        voci.append(_voce(f"{prefisso}{i}", "Over/Under 2,5 gol", "Over 2,5 goal"))
    return voci


def _cfg_molti_profili(n_profili, coppie_per_profilo):
    return {"market_mappings": {f"P{k}": _profilo_in_conflitto(f"f{k}_", coppie_per_profilo)
                                for k in range(n_profili)}}


def test_256_il_lavoro_TOTALE_ha_un_tetto_e_lo_DICE():
    """Il cuore del punto 2. Prima della correzione nessun limite globale: 8 profili al tetto
    per-profilo costavano 5,4 s allo START, tutti spesi prima che la finestra rispondesse."""
    # ben oltre il budget globale, ma ogni profilo resta SOTTO il tetto per-profilo
    cfg = _cfg_molti_profili(8, 150)
    totale = sum(len(v) for v in cfg["market_mappings"].values())
    assert totale > mms._MAX_VOCI_TOTALI_CONTROLLO, "la fixture non supera il budget globale"

    avvisi = mms.ambiguous_phrase_warnings(cfg)
    testo = "\n".join(avvisi)
    assert "budget" in testo.lower() or "tetto complessivo" in testo.lower(), testo
    # deve NOMINARE i profili non controllati: senza, l'utente non sa cosa NON è stato guardato
    assert "P" in testo, testo


def test_256_sotto_il_budget_globale_NULLA_cambia():
    """Contro-guardia: la stragrande maggioranza delle config reali sta ampiamente sotto il
    budget, e per loro il comportamento dev'essere identico a prima — nessun avviso in più,
    nessun conflitto in meno."""
    cfg = _cfg_molti_profili(2, 3)          # 12 voci in tutto
    avvisi = mms.ambiguous_phrase_warnings(cfg)
    assert len(avvisi) == 6, avvisi          # 3 conflitti per profilo, 2 profili
    for a in avvisi:
        assert "budget" not in a.lower() and "non elencati" not in a.lower(), a


def test_256_il_numero_di_AVVISI_ha_un_tetto_e_lo_DICE():
    """Il secondo problema, indipendente dal tempo: 1200 righe di ⚠️ nel log non si leggono.

    Un elenco che nessuno scorre informa quanto il silenzio che la #254 aveva tolto — quindi si
    tronca, ma **dicendo quanti** ne restano, altrimenti si ricrea la bugia del cap muto.
    """
    # un solo profilo, sotto il tetto per-profilo e sotto il budget globale, ma con TANTI
    # conflitti distinti: il tempo non è il problema, il numero di avvisi sì
    cfg = {"market_mappings": {"M": _profilo_in_conflitto("f", 140)}}
    assert len(cfg["market_mappings"]["M"]) <= mms._MAX_VOCI_CONTROLLO_AMBIGUITA
    avvisi = mms.ambiguous_phrase_warnings(cfg)

    assert len(avvisi) <= mms._MAX_AVVISI_AMBIGUITA + 1, len(avvisi)   # +1 = la riga di sintesi
    coda = avvisi[-1]
    assert "non elencati" in coda.lower(), coda
    # la riga di sintesi deve dire QUANTI ne mancano, non «altri»
    assert any(ch.isdigit() for ch in coda), coda


def test_256_sotto_il_tetto_avvisi_non_compare_la_riga_di_sintesi():
    """Contro-guardia della precedente: pochi conflitti → nessuna coda, nessun rumore."""
    cfg = {"market_mappings": {"M": _profilo_in_conflitto("f", 3)}}
    avvisi = mms.ambiguous_phrase_warnings(cfg)
    assert len(avvisi) == 3, avvisi
    assert not any("non elencati" in a.lower() for a in avvisi), avvisi


def test_256_il_budget_globale_non_e_silenzioso_neanche_a_zero_conflitti():
    """Un profilo saltato per budget va detto **anche se non aveva conflitti**: chi legge non
    può sapere che era sano, e «nessun avviso» significherebbe «controllato e pulito»."""
    grosso = [_voce(f"unica{i}") for i in range(mms._MAX_VOCI_CONTROLLO_AMBIGUITA)]
    cfg = {"market_mappings": {f"P{k}": list(grosso) for k in range(5)}}   # 1500 voci, 0 conflitti
    avvisi = mms.ambiguous_phrase_warnings(cfg)
    assert avvisi, "profili non controllati e nessun avviso: sembra 'tutto pulito'"
    assert any("budget" in a.lower() for a in avvisi), avvisi


def test_256_i_tetti_sono_deterministici():
    """Stessa config → stessi avvisi, compresi quelli di troncamento: un log che si rimescola a
    ogni avvio non si legge (stessa garanzia della #254)."""
    cfg = _cfg_molti_profili(8, 150)
    assert mms.ambiguous_phrase_warnings(cfg) == mms.ambiguous_phrase_warnings(cfg)


def test_256_il_taglio_per_budget_non_dipende_dall_ORDINE_della_config():
    """Rilievo GPT-5.5 sulla #261.

    Il budget decide *quali* profili vengono controllati, quindi finché si itera nell'ordine di
    inserimento del dict l'ordine diventa **parte del risultato**: la stessa identica config,
    riscritta o mergiata con le chiavi in ordine diverso, taglierebbe profili diversi e
    segnalerebbe conflitti diversi. Un avviso che cambia senza che i dati siano cambiati non è
    una diagnostica, è rumore — ed è la stessa classe di difetto (la vista che non corrisponde
    ai fatti) per cui questa PR esiste.

    Qui: quattro profili identici a coppie, inseriti in ordine opposto nei due dict.
    """
    profili = {f"P{k}": _profilo_in_conflitto(f"f{k}_", 150) for k in range(4)}   # 1200 voci
    assert sum(len(v) for v in profili.values()) > mms._MAX_VOCI_TOTALI_CONTROLLO, \
        "senza superare il budget il taglio non avviene e il test non dimostra nulla"

    diretto = {"market_mappings": dict(profili.items())}
    inverso = {"market_mappings": dict(reversed(list(profili.items())))}
    assert list(diretto["market_mappings"]) != list(inverso["market_mappings"]), "stesso ordine"

    assert mms.ambiguous_phrase_warnings(diretto) == mms.ambiguous_phrase_warnings(inverso)


def test_256_un_profilo_SALTATO_non_consuma_il_budget_globale():
    """Rilievo Fable 5 sulla #261, ed è un difetto logico, non di stile.

    Il budget globale veniva scalato **prima** del controllo sul tetto per-profilo: un profilo
    troppo grande — quindi mai esaminato — consumava comunque il suo peso, e poteva far saltare
    profili successivi **sani** con un «budget esaurito» che non era vero. Il budget deve
    contare le voci **davvero esaminate**, altrimenti mente sul motivo per cui si è fermato.

    Qui: un profilo da 400 voci (oltre il tetto per-profilo di 300, quindi saltato) seguito da
    uno da 600 con conflitti veri. 400 + 600 = 1000 > 900, quindi col difetto il secondo veniva
    saltato per budget — pur essendo il solo dei due che il controllo poteva davvero guardare.
    """
    # «Grosso» oltre il tetto PER PROFILO (quindi mai esaminato); «Sano» sotto entrambi i
    # tetti. I numeri sono scelti perche' il difetto MORDA: 700 + 280 = 980 > 900, quindi col
    # bug «Sano» veniva saltato per budget; da solo (280) ci sta comodamente.
    grosso = [_voce(f"g{i}") for i in range(700)]
    conflitti = _profilo_in_conflitto("b", 140)          # 280 voci, 140 conflitti
    assert len(grosso) > mms._MAX_VOCI_CONTROLLO_AMBIGUITA, "«Grosso» deve saltare per tetto profilo"
    assert len(conflitti) <= mms._MAX_VOCI_CONTROLLO_AMBIGUITA, "«Sano» deve essere esaminabile"
    assert len(grosso) + len(conflitti) > mms._MAX_VOCI_TOTALI_CONTROLLO, "il difetto non morderebbe"
    assert len(conflitti) <= mms._MAX_VOCI_TOTALI_CONTROLLO

    avvisi = mms.ambiguous_phrase_warnings({"market_mappings": {"Grosso": grosso,
                                                               "Sano": conflitti}})
    testo = "\n".join(avvisi)
    # il profilo grosso è saltato per il TETTO PER PROFILO, e lo dice
    assert "«Grosso»" in testo and "oltre il tetto" in testo, testo
    # ...ma «Sano» dev'essere stato CONTROLLATO: i suoi conflitti ci sono
    assert any("«Sano»" in a and "combacia" in a for a in avvisi), testo
    # e nessuno lo accusa di essere fuori budget
    assert "«Sano»" not in testo.split("budget complessivo")[-1] if "budget complessivo" in testo else True
