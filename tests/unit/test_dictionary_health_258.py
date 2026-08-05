"""#258 — il semaforo Dizionari dice quello che succede, non quanti conflitti ci sono.

Le due regole che ne determinano l'onestà, e i test che le tengono:

1. **conta solo ciò che costa segnali** — lo STESSO conflitto è 🔴 se un parser usa quel
   profilo e 🟡 se il profilo è orfano;
2. **«non controllato» non è «pulito»** — un profilo in uso mai esaminato (tetto/budget) non
   può dare verde, perché nessuno ha guardato.

Niente soglie numeriche: la gravità di un conflitto non dipende da quanti sono, ma da se un
parser usa quel profilo. Una soglia tarata a mano andrebbe ritarata a ogni dizionario, e nel
frattempo direbbe una cosa diversa da quella che succede.
"""

import pytest

from xtrader_bridge import dictionary_health as dh
from xtrader_bridge import health_check
from xtrader_bridge import market_mapping_store as mms
from xtrader_bridge import name_mapping_store as nms

# Due righe che mandano lo stesso alias a due nomi Betfair diversi: `resolve_team` fail-closa.
_CFG_CONFLITTO_NOMI = {"name_mappings": {"P": [
    {"provider": "Juve", "betfair": "Juventus"},
    {"provider": "Juve", "betfair": "Juventus FC"},
]}}


def _usati(nomi=(), mercati=(), illeggibili=()):
    return {"nomi": set(nomi), "mercati": set(mercati), "illeggibili": list(illeggibili)}


def test_258_lo_STESSO_conflitto_e_rosso_se_usato_e_giallo_se_orfano():
    """Il cuore della issue, in un test solo: cambia **solo** chi usa il profilo.

    Se il colore dipendesse dal numero di conflitti — come prevedeva la stesura iniziale con le
    soglie — questi due casi sarebbero identici. Sono invece opposti: nel primo ogni segnale che
    nomina «Juve» viene scartato adesso, nel secondo non si perde nulla.
    """
    usato = dh.stato_dizionari(_CFG_CONFLITTO_NOMI, _usati(nomi=["P"]))
    orfano = dh.stato_dizionari(_CFG_CONFLITTO_NOMI, _usati())

    assert usato["stato"] == health_check.RED, usato
    assert "SCARTATI" in usato["titolo"], usato["titolo"]
    assert usato["dettagli"], "il rosso deve elencare i conflitti, non solo contarli"

    assert orfano["stato"] == health_check.YELLOW, orfano
    assert "NESSUN parser usa" in orfano["titolo"], orfano["titolo"]


def test_258_config_pulita_e_verde():
    """Contro-guardia: senza, un'implementazione che non mostra mai verde passerebbe il test
    qui sopra — e un semaforo perennemente giallo si impara a ignorare come uno rotto."""
    sana = {"name_mappings": {"P": [{"provider": "Juve", "betfair": "Juventus"}]}}
    esito = dh.stato_dizionari(sana, _usati(nomi=["P"]))
    assert esito["stato"] == health_check.GREEN, esito
    assert esito["dettagli"] == []


def test_258_profilo_in_uso_NON_controllato_non_puo_essere_verde(monkeypatch):
    """La seconda regola. Il profilo è **in uso** e non ha conflitti elencati — ma non li ha
    perché nessuno li ha cercati: il controllo si è fermato al tetto.

    Verde qui sarebbe la rassicurazione senza copertura che questa serie di PR esiste per
    togliere: l'utente leggerebbe «dizionari a posto» da un controllo che non ha guardato.
    """
    monkeypatch.setattr(mms, "_MAX_VOCI_CONTROLLO_AMBIGUITA", 2)
    voci = [{"phrase": f"p{i}", "market_name": f"M{i}", "selection_name": f"S{i}"}
            for i in range(5)]
    cfg = {"market_mappings": {"Grande": voci}}

    esito = dh.stato_dizionari(cfg, _usati(mercati=["Grande"]))

    assert esito["stato"] == health_check.YELLOW, esito
    assert "controllo NON eseguito" in esito["titolo"], esito["titolo"]
    assert "«Grande»" in esito["titolo"], "va detto QUALE profilo non è stato guardato"


def test_258_profilo_ORFANO_non_controllato_non_accende_l_avviso(monkeypatch):
    """Contro-guardia della precedente: l'incompletezza conta solo sui profili **in uso**.

    Un profilo che nessun parser usa e che non è stato esaminato non costa segnali, e far
    scattare «non so» anche lì riempirebbe il pannello di gialli che non chiedono nulla — il
    modo più rapido per insegnare a ignorarlo.
    """
    monkeypatch.setattr(mms, "_MAX_VOCI_CONTROLLO_AMBIGUITA", 2)
    voci = [{"phrase": f"p{i}", "market_name": f"M{i}", "selection_name": f"S{i}"}
            for i in range(5)]
    cfg = {"market_mappings": {"Grande": voci}}

    esito = dh.stato_dizionari(cfg, _usati())      # nessun parser lo usa

    assert esito["stato"] == health_check.GREEN, esito
    assert "controllo NON eseguito" not in esito["titolo"]


def test_258_un_parser_ILLEGGIBILE_toglie_il_verde():
    """Se non si riesce a leggere un parser non si sa quali profili usi, quindi non si può
    escludere che un conflitto lo tocchi. Dirlo è l'unica risposta vera; il verde sarebbe una
    deduzione da un dato mancante."""
    sana = {"name_mappings": {"P": [{"provider": "Juve", "betfair": "Juventus"}]}}
    esito = dh.stato_dizionari(sana, _usati(nomi=["P"], illeggibili=["rotto.json"]))

    assert esito["stato"] == health_check.YELLOW, esito
    assert "rotto.json" in esito["titolo"], "va detto QUALE parser non si legge"


def test_258_i_dettagli_sono_capati_ma_MAI_in_silenzio():
    """Un elenco di centinaia di righe non si legge, e un elenco che nessuno scorre informa
    quanto il silenzio. Ma il taglio va **dichiarato**: un cap muto si legge come «non ce ne
    sono altri», ed è la stessa convenzione che `market_mapping_store` già applica ai suoi
    avvisi."""
    righe = []
    for i in range(dh.MAX_DETTAGLI + 5):
        righe.append({"provider": f"Nome{i}", "betfair": f"A{i}"})
        righe.append({"provider": f"Nome{i}", "betfair": f"B{i}"})
    cfg = {"name_mappings": {"P": righe}}

    esito = dh.stato_dizionari(cfg, _usati(nomi=["P"]))

    assert esito["stato"] == health_check.RED
    assert len(esito["dettagli"]) == dh.MAX_DETTAGLI
    assert esito["nascosti"] > 0, "il numero dei nascosti va riportato, non taciuto"
    # il titolo conta TUTTI i conflitti, non solo quelli mostrati: altrimenti il cap si
    # travestirebbe da conteggio reale
    assert str(len(esito["dettagli"]) + esito["nascosti"]) in esito["titolo"], esito["titolo"]


def test_258_config_malformata_non_fa_cadere_il_pannello():
    """Il pannello Salute chiama questa funzione all'apertura della finestra. La config è un
    file editabile a mano: se sollevasse, un dizionario manomesso spegnerebbe la diagnostica
    invece di descriverla — e chiavi di tipo misto sollevavano davvero (#261)."""
    for cfg in (None, {}, {"name_mappings": None}, {"market_mappings": "non-un-dict"},
                {"name_mappings": {"A": "non-una-lista"}},
                {"market_mappings": {"A": [{"phrase": "p", "market_name": "M",
                                            "selection_name": "S"}], 3: [{}]}}):
        esito = dh.stato_dizionari(cfg, _usati(nomi=["A"], mercati=["A"]))
        assert esito["stato"] in (health_check.GREEN, health_check.YELLOW, health_check.RED), cfg


def test_258_profili_usati_conta_i_parser_illeggibili_invece_di_cadere():
    """`load_parser` solleva `ValueError` su file corrotto e `OSError` su accesso: un parser
    rotto non deve far sparire la vista di tutti gli altri."""
    class _Def:
        name_mapping_profiles = ["P"]
        market_mapping_profiles = ["M"]

    def _carica(percorso):
        if "rotto" in percorso:
            raise ValueError("json corrotto")
        return _Def()

    esito = dh.profili_usati(elenca=lambda *a: ["/x/buono.json", "/x/rotto.json"],
                             carica=_carica)

    assert esito["nomi"] == {"P"} and esito["mercati"] == {"M"}
    assert esito["illeggibili"] == ["rotto.json"], esito


def test_258_una_cartella_parser_ILLEGGIBILE_non_puo_produrre_verde():
    """Bloccante Fable 5 sulla PR #276, e la stesura precedente lo cementava in un test.

    Se la cartella dei parser non è leggibile non si sa **quali profili siano in uso**: senza
    profili in uso non ci sono conflitti da attribuire, e il semaforo mostrava 🟢 «nessun
    conflitto sui profili in uso» — verde dedotto da un errore, in contraddizione col design
    handoff di questa stessa PR che promette 🟡 «non calcolabile».

    Ora l'`OSError` **sale** al confine unico del pannello, che mostra il giallo. Un test che
    asseriva il ritorno silenzioso stava proteggendo il difetto invece del comportamento.

    NB: una cartella *inesistente* è un'altra cosa — `list_parser_files` torna `[]` di
    proposito, e «nessun parser configurato» è uno stato noto, non un'incognita.
    """
    def _esplode(*a, **k):
        raise OSError("cartella illeggibile (permessi)")

    with pytest.raises(OSError):
        dh.profili_usati(elenca=_esplode, carica=_esplode)


def test_258_un_profilo_saltato_dal_budget_allo_START_resta_non_controllato_nel_pannello(
        monkeypatch):
    """Rilievo Fable 5 sulla PR #276 — ripristinato dopo che una mia riscrittura del file ne
    aveva troncato la coda, cancellando questo test senza che me ne accorgessi (rilevato da
    Fable e GPT-5.5 sul giro successivo: copertura persa in silenzio).

    Il budget globale è **globale**: se il pannello ricalcolasse il piano sulla sola sotto-config
    dei profili in uso, un profilo saltato per budget allo START rientrerebbe nel budget del
    sottoinsieme e verrebbe esaminato — dicendo «controllato» dove il log eventi dice «NON
    controllato». Due diagnostiche che si contraddicono sullo stesso profilo.
    """
    monkeypatch.setattr(mms, "_MAX_VOCI_CONTROLLO_AMBIGUITA", 50)
    monkeypatch.setattr(mms, "_MAX_VOCI_TOTALI_CONTROLLO", 45)
    cfg = {"market_mappings": {"A": [{"phrase": f"a{i}", "market_name": f"M{i}",
                                      "selection_name": f"S{i}"} for i in range(40)],
                               "Z": [{"phrase": f"z{i}", "market_name": f"M{i}",
                                      "selection_name": f"S{i}"} for i in range(10)]}}

    assert mms.profili_non_controllati(cfg) == ["Z"], "premessa: lo START salta Z"

    esito = dh.stato_dizionari(cfg, _usati(mercati=["Z"]))

    assert esito["stato"] == health_check.YELLOW, esito
    assert "controllo NON eseguito" in esito["titolo"], esito["titolo"]
    assert "«Z»" in esito["titolo"], esito["titolo"]


def test_258_righe_MALFORMATE_su_un_profilo_escluso_dal_budget_restano_ROSSE(monkeypatch):
    """Secondo bloccante Fugu Ultra sulla PR #276, ed è la distinzione che regge tutto.

    `malformed_entry_warnings` **non ha tetti**: è sempre completo. Escluderlo insieme al
    controllo ambiguità declassava a 🟡 «non controllato» un profilo con righe malformate
    **reali** — voci che il resolver scarta adesso, ogni volta.

    Il «non so» vale per ciò che **non è stato guardato**, non per ciò che è stato guardato e
    trovato. Nascondere un conflitto noto dietro un'incertezza è il difetto simmetrico a
    mostrare verde su un controllo mancato: entrambi dicono qualcosa di diverso da ciò che si sa.
    """
    monkeypatch.setattr(mms, "_MAX_VOCI_CONTROLLO_AMBIGUITA", 2)
    voci = [{"phrase": f"p{i}", "market_name": f"M{i}", "selection_name": f"S{i}",
             "language": "klingon"} for i in range(5)]      # lingua non riconosciuta: MALFORMATE
    cfg = {"market_mappings": {"Grande": voci}}

    esito = dh.stato_dizionari(cfg, _usati(mercati=["Grande"]))

    assert esito["stato"] == health_check.RED, (
        f"un conflitto NOTO è stato declassato a {esito['stato']}: {esito['titolo']}")
    assert esito["dettagli"], "i conflitti noti vanno elencati anche se l'ambiguità non è stata controllata"


def test_258_le_righe_malformate_non_vengono_contate_DUE_volte(monkeypatch):
    """Rilievo Fable 5: dopo aver separato malformate e ambiguità, un profilo che sta in
    entrambe le viste potrebbe far comparire lo stesso conflitto due volte.

    Un conteggio gonfiato è un difetto della stessa famiglia degli altri di questa PR: il
    numero nel titolo smetterebbe di corrispondere a quello che succede, e chi conta i
    conflitti nel dizionario per correggerli non li ritroverebbe.
    """
    voci = [{"phrase": "p1", "market_name": "M", "selection_name": "S", "language": "klingon"}]
    cfg = {"market_mappings": {"Piccolo": voci}}      # dentro i tetti: sta in ENTRAMBE le viste

    esito = dh.stato_dizionari(cfg, _usati(mercati=["Piccolo"]))

    assert esito["stato"] == health_check.RED, esito
    totale = len(esito["dettagli"]) + esito["nascosti"]
    assert totale == 1, f"la stessa voce malformata contata {totale} volte: {esito['dettagli']}"


def test_258_il_controllo_sui_NOMI_non_salta_profili_grandi(monkeypatch):
    """Rilievo Fable 5 (asimmetria nomi/mercati), con la guardia rifatta dopo GPT-5.5.

    La separazione fra «malformate» e «ambiguità» serve ai mercati perché lì il controllo ha
    dei tetti e può saltare interi profili. Sui nomi non serve **se e solo se** nessun profilo
    viene mai saltato.

    Una prima stesura lo verificava cercando `_MAX_VOCI` nel **sorgente** del modulo. GPT-5.5
    ha fatto notare che è il livello sbagliato: un tetto introdotto con un altro nome avrebbe
    lasciato il test verde — una guardia che sembra sorvegliare e si aggira rinominando, cioè
    lo stesso difetto che questa PR insegue.

    Qui si verifica il **comportamento**: un profilo nomi grande, ben oltre i tetti che i
    mercati applicano (300 per profilo), con un conflitto vero in fondo. Se un domani i nomi
    guadagnassero un tetto — con qualunque nome — quel conflitto smetterebbe di essere
    riportato e questo test diventerebbe rosso.
    """
    righe = [{"provider": f"Squadra{i}", "betfair": f"Team{i}"} for i in range(400)]
    righe.append({"provider": "Ambiguo", "betfair": "Alfa"})
    righe.append({"provider": "Ambiguo", "betfair": "Beta"})      # conflitto, in FONDO
    cfg = {"name_mappings": {"Grande": righe}}

    avvisi = nms.ambiguous_alias_warnings(cfg)

    assert any("Ambiguo" in a for a in avvisi), (
        f"il conflitto in fondo a un profilo di {len(righe)} righe non è stato riportato: il "
        "controllo sui nomi ha guadagnato un tetto, e allora anche per i nomi le righe "
        "malformate vanno separate dall'ambiguità come per i mercati "
        "(vedi il commento in dictionary_health.stato_dizionari)")

    # …e il pannello lo vede come ROSSO, non come un «non so»: e' la conseguenza che conta.
    esito = dh.stato_dizionari(cfg, _usati(nomi=["Grande"]))
    assert esito["stato"] == health_check.RED, esito
